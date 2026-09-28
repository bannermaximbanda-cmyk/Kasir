"""
Iter36 — Vendor Payout Center enhancements.

Verifies:
  1. GET /api/settlement/preview returns per-merchant items breakdown
     (aggregated by product+variant).
  2. POST /api/settlement/payouts persists items snapshot, extra_fees,
     extra_fees_total, and net = gross - commission - extra_fees_total.
  3. Sales already included in a prior payout are EXCLUDED from a new
     preview (single-source-of-truth: mjd_payouts.sale_ids).
  4. GET /api/settlement/payouts returns merchant_name enrichment.

All test data prefixed TEST_ and cleaned up in teardown.
"""

import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL}/api"
HEADERS_CSRF = {"X-Requested-With": "mjd-kupi", "Content-Type": "application/json"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password},
                      headers=HEADERS_CSRF, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_auth():
    tok = _login("superadmin", ".Superadmin1_")
    return {"Authorization": f"Bearer {tok}", **HEADERS_CSRF}


@pytest.fixture(scope="module")
def kasir_auth():
    tok = _login("kasir", "MjdKupi#2026")
    return {"Authorization": f"Bearer {tok}", **HEADERS_CSRF}


def _force_close_shift(kasir_auth):
    requests.post(f"{API}/shifts/close", json={"closing_cash": 0}, headers=kasir_auth, timeout=30)


def _open_shift(kasir_auth):
    r = requests.post(f"{API}/shifts/open", json={"opening_cash": 0}, headers=kasir_auth, timeout=30)
    return r.json().get("id")


def _create_merchant(admin_auth, name, commission_percent=10):
    r = requests.post(f"{API}/merchants", json={
        "name": name, "commission_scheme": "percent",
        "commission_percent": commission_percent, "commission_fixed": 0,
    }, headers=admin_auth, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_product(admin_auth, name, price, mid):
    r = requests.post(f"{API}/products", json={
        "name": name, "category": "Snack", "price": price, "cost": price / 2,
        "stock": 999, "vendor": name.replace("TEST_", ""), "merchant_id": mid,
    }, headers=admin_auth, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_sale(kasir_auth, pid, mid, price, qty):
    body = {
        "table": "Meja TEST",
        "lines": [{"product_id": pid, "name": "TEST", "quantity": qty, "price": price,
                   "vendor": "MJD Kupi", "merchant_id": mid}],
        "subtotal": price * qty, "tax": 0, "total": price * qty,
        "payment_method": "Cash", "cash_received": price * qty, "change_amount": 0,
        "idempotency_key": str(uuid.uuid4()),
    }
    r = requests.post(f"{API}/sales", json=body, headers=kasir_auth, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_payout_full_flow(admin_auth, kasir_auth):
    """End-to-end: preview → pay with extra fees → preview excludes paid sales."""
    _force_close_shift(kasir_auth)
    shift_id = _open_shift(kasir_auth)
    mid = _create_merchant(admin_auth, f"TEST_M_{uuid.uuid4().hex[:6]}", commission_percent=10)
    pid = _create_product(admin_auth, f"TEST_Batagor_{uuid.uuid4().hex[:6]}", price=15000, mid=mid)

    # 2 sales: 1×15k + 1×30k (qty 2)
    sale1 = _create_sale(kasir_auth, pid, mid, 15000, 1)
    sale2 = _create_sale(kasir_auth, pid, mid, 15000, 2)
    period_from = "2020-01-01"
    period_to = "2099-12-31"

    # 1) Preview
    pr = requests.get(f"{API}/settlement/preview",
                      params={"date_from": period_from, "date_to": period_to},
                      headers=admin_auth, timeout=30).json()
    ours = next((b for b in pr["breakdown"] if b["merchant_id"] == mid), None)
    assert ours is not None, "merchant missing from preview"
    assert ours["gross"] == 45000  # 15k + 30k
    assert ours["commission"] == 4500  # 10%
    assert ours["item_count"] == 3
    assert set(ours["sale_ids"]) == {sale1, sale2}
    # Items should be aggregated to 1 line: 3× TEST_Batagor @ 15k = 45k
    assert len(ours["items"]) == 1
    it = ours["items"][0]
    assert it["quantity"] == 3 and it["price"] == 15000 and it["subtotal"] == 45000

    # 2) Pay with 2 extra fees (10k + 5k)
    payout_body = {
        "merchant_id": mid,
        "period_start": period_from,
        "period_end": period_to,
        "note": "TEST_payout_note",
        "extra_fees": [
            {"name": "Uang kebersihan", "amount": 10000},
            {"name": "Biaya listrik", "amount": 5000},
        ],
    }
    p = requests.post(f"{API}/settlement/payouts", json=payout_body, headers=admin_auth, timeout=30)
    assert p.status_code == 200, p.text
    payout = p.json()
    assert payout["gross"] == 45000
    assert payout["commission"] == 4500
    assert payout["extra_fees_total"] == 15000
    assert payout["net"] == 45000 - 4500 - 15000  # 25500
    assert len(payout["extra_fees"]) == 2
    assert payout["extra_fees"][0]["name"] == "Uang kebersihan"
    # Items snapshot frozen
    assert len(payout["items"]) == 1
    assert payout["items"][0]["quantity"] == 3

    # 3) After payout: preview should exclude these sales (BELUM DIBAYAR list clean)
    pr2 = requests.get(f"{API}/settlement/preview",
                       params={"date_from": period_from, "date_to": period_to},
                       headers=admin_auth, timeout=30).json()
    ours2 = next((b for b in pr2["breakdown"] if b["merchant_id"] == mid), None)
    assert ours2 is None, f"merchant still in preview after payout: {ours2}"

    # 4) POST again for the same period should fail (no unpaid omset left)
    p2 = requests.post(f"{API}/settlement/payouts", json=payout_body, headers=admin_auth, timeout=30)
    assert p2.status_code == 400, f"expected 400 double-pay guard, got {p2.status_code}: {p2.text}"

    # 5) List includes merchant_name enrichment + status
    lst = requests.get(f"{API}/settlement/payouts",
                       params={"merchant_id": mid}, headers=admin_auth, timeout=30).json()
    assert len(lst) >= 1
    row = next(r for r in lst if r["id"] == payout["id"])
    assert row["merchant_name"].startswith("TEST_M_")
    assert row["status"] == "paid"
    assert row["extra_fees_total"] == 15000

    # cleanup
    _force_close_shift(kasir_auth)
    # Delete the payout to make it repeatable + product/merchant
    # (No DELETE payout endpoint — clean via DB in module teardown script if needed.)
    requests.delete(f"{API}/products/{pid}", headers=admin_auth, timeout=30)
    requests.delete(f"{API}/merchants/{mid}", headers=admin_auth, timeout=30)


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-s"] + sys.argv[1:])
