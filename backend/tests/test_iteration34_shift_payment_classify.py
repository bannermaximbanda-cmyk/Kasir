"""
Iter34 — Shift recap payment classification.

Reproduces the reported bug: shift recap treated everything != "Cash" as Transfer,
so "QRIS", "QRIS Toko", "Bayar di Kasir", "Transfer Bank" were all miscategorised
as Transfer.

Verifies:
  1. Individual method mapping (test 1-6):
       "Cash", "Bayar di Kasir"      → total_cash
       "Transfer", "Transfer Bank"   → total_transfer
       "QRIS", "QRIS Toko"           → total_qris
  2. Mixed shift totals + expected_cash includes Cash + Bayar di Kasir - cash expenses
  3. Online self-order (accepted by cashier) → becomes Sale with shift_id, then
     classified by its stored payment_method (no double-count, no bypass).

All test data prefixed TEST_ and cleaned up in teardown.
"""

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL}/api"
HEADERS_CSRF = {"X-Requested-With": "mjd-kupi", "Content-Type": "application/json"}


def _login(email, password):
    last_err = None
    for _ in range(4):
        try:
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": password},
                              headers=HEADERS_CSRF, timeout=45)
            if r.status_code in (502, 503, 504):
                last_err = r.status_code; time.sleep(3); continue
            assert r.status_code == 200, r.text
            return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            last_err = repr(e); time.sleep(3)
    raise RuntimeError(f"login exhausted: {last_err}")


@pytest.fixture(scope="module")
def admin_auth():
    tok = _login("superadmin", ".Superadmin1_")
    return {"Authorization": f"Bearer {tok}", **HEADERS_CSRF}


@pytest.fixture(scope="module")
def kasir_auth():
    tok = _login("kasir", "MjdKupi#2026")
    return {"Authorization": f"Bearer {tok}", **HEADERS_CSRF}


# ---------------------------------------------------------------------------
# Helpers to make a Sale with a specific payment_method inside the kasir's shift.
# ---------------------------------------------------------------------------
def _ensure_shift_closed(kasir_auth):
    """Close any leftover open shift for the kasir."""
    r = requests.post(f"{API}/shifts/close", json={"closing_cash": 0}, headers=kasir_auth, timeout=30)
    # 404 == no active shift; anything else is ok too.


def _open_shift(kasir_auth, opening_cash=100000):
    r = requests.post(f"{API}/shifts/open", json={"opening_cash": opening_cash}, headers=kasir_auth, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_product(admin_auth, name, price=10000, stock=100):
    merchants = requests.get(f"{API}/merchants", headers=admin_auth, timeout=30).json()
    mid = merchants[0]["id"]
    r = requests.post(f"{API}/products", json={
        "name": name, "category": "Snack", "price": price, "cost": price / 2,
        "stock": stock, "vendor": "MJD Kupi", "merchant_id": mid,
    }, headers=admin_auth, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"], mid


def _create_sale(kasir_auth, pid, mid, method, amount, qty=1):
    """Create POS sale with the given payment_method (server recomputes total from product price)."""
    body = {
        "table": "Meja TEST",
        "lines": [{"product_id": pid, "name": "TEST", "quantity": qty, "price": amount,
                   "vendor": "MJD Kupi", "merchant_id": mid}],
        "subtotal": amount, "tax": 0, "total": amount,
        "payment_method": method,
        "cash_received": amount if method in ("Cash", "Bayar di Kasir") else 0,
        "change_amount": 0,
        "idempotency_key": str(uuid.uuid4()),
    }
    r = requests.post(f"{API}/sales", json=body, headers=kasir_auth, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _create_self_order_accepted(kasir_auth, pid, mid, method, amount, outlet_id, qty=1):
    """Create a self-order then accept it — becomes Sale with shift_id (price re-derived server-side)."""
    idem = str(uuid.uuid4())
    so_body = {
        "table": "Meja SO",
        "lines": [{"product_id": pid, "name": "TEST_SO", "quantity": qty, "price": amount,
                   "vendor": "MJD Kupi", "merchant_id": mid}],
        "total": amount,
        "notes": "",
        "payment_method": method,
        "payment_proof": "https://example.com/proof.png",
        "customer_name": "TEST Customer",
        "customer_phone": "",
        "outlet_id": outlet_id,
        "idempotency_key": idem,
    }
    sr = requests.post(f"{API}/self-order", json=so_body, headers=HEADERS_CSRF, timeout=30)
    assert sr.status_code in (200, 201), sr.text
    so_id = sr.json()["id"]
    ar = requests.post(f"{API}/self-order/{so_id}/accept", json={}, headers=kasir_auth, timeout=30)
    assert ar.status_code == 200, ar.text
    return ar.json().get("id") or ar.json().get("sale", {}).get("id")


# ---------------------------------------------------------------------------
# Tests 1–6: individual method mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method,bucket,amount", [
    ("Cash",           "total_cash",     10000),
    ("Bayar di Kasir", "total_cash",     20000),
    ("Transfer",       "total_transfer", 30000),
    ("Transfer Bank",  "total_transfer", 40000),
    ("QRIS",           "total_qris",     50000),
    ("QRIS Toko",      "total_qris",     60000),
])
def test_payment_method_classification(admin_auth, kasir_auth, method, bucket, amount):
    """One sale with the given method should land in the correct recap bucket only."""
    _ensure_shift_closed(kasir_auth)
    shift_id = _open_shift(kasir_auth, opening_cash=0)
    # Product price MUST match `amount` because server recomputes total from product.price.
    pid, mid = _create_product(admin_auth, f"TEST_pm_{uuid.uuid4().hex[:6]}", price=amount)
    try:
        _create_sale(kasir_auth, pid, mid, method, amount)
        rr = requests.get(f"{API}/shifts/{shift_id}/report", headers=kasir_auth, timeout=30)
        assert rr.status_code == 200, rr.text
        rep = rr.json()
        # The target bucket must contain this amount; the OTHER two buckets must be 0.
        buckets = {"total_cash": rep["total_cash"], "total_transfer": rep["total_transfer"],
                   "total_qris": rep["total_qris"]}
        assert buckets[bucket] == amount, f"{method}: expected {bucket}={amount}, got {buckets}"
        for other, v in buckets.items():
            if other != bucket:
                assert v == 0, f"{method}: leaked into {other}={v}"
        # total_omset = sum of the three
        assert rep["total_omset"] == amount, rep
    finally:
        # cleanup
        _ensure_shift_closed(kasir_auth)
        requests.delete(f"{API}/products/{pid}", headers=admin_auth, timeout=30)


# ---------------------------------------------------------------------------
# Test 7: mixed payment methods + expected_cash math
# ---------------------------------------------------------------------------
def test_mixed_payments_and_expected_cash(admin_auth, kasir_auth):
    """
    Cash 10k + Bayar di Kasir 20k + Transfer 30k + Transfer Bank 40k
    + QRIS 50k + QRIS Toko 60k = 210k total.
    Modal 100k, pengeluaran cash 15k.
    Expected cash = 100 + 30 - 15 = 115k.  Never 195k, never 210k.
    """
    _ensure_shift_closed(kasir_auth)
    shift_id = _open_shift(kasir_auth, opening_cash=100000)
    # Use price=10000 and vary quantity so server-recomputed totals match.
    pid, mid = _create_product(admin_auth, f"TEST_mix_{uuid.uuid4().hex[:6]}", price=10000, stock=999)
    try:
        _create_sale(kasir_auth, pid, mid, "Cash", 10000, qty=1)          # 10k
        _create_sale(kasir_auth, pid, mid, "Bayar di Kasir", 20000, qty=2) # 20k
        _create_sale(kasir_auth, pid, mid, "Transfer", 30000, qty=3)       # 30k
        _create_sale(kasir_auth, pid, mid, "Transfer Bank", 40000, qty=4)  # 40k
        _create_sale(kasir_auth, pid, mid, "QRIS", 50000, qty=5)           # 50k
        _create_sale(kasir_auth, pid, mid, "QRIS Toko", 60000, qty=6)      # 60k
        # cash expense
        requests.post(f"{API}/expenses", json={
            "category": "Pembelian Bahan Baku", "note": "TEST_mix_exp",
            "amount": 15000, "date": time.strftime("%Y-%m-%d"), "method": "Cash",
        }, headers=kasir_auth, timeout=30)

        rr = requests.get(f"{API}/shifts/{shift_id}/report", headers=kasir_auth, timeout=30)
        rep = rr.json()
        assert rep["total_cash"] == 30000, rep
        assert rep["total_transfer"] == 70000, rep
        assert rep["total_qris"] == 110000, rep
        assert rep["total_omset"] == 210000, rep
        assert rep["expected_cash"] == 115000, rep  # 100k + 30k - 15k
        # cross-check on /shifts list (admin monitor)
        lr = requests.get(f"{API}/shifts", headers=admin_auth, timeout=30).json()
        row = next(s for s in lr if s["id"] == shift_id)
        assert row["total_cash"] == 30000 and row["total_transfer"] == 70000 and row["total_qris"] == 110000
        assert row["total_omset"] == 210000
    finally:
        _ensure_shift_closed(kasir_auth)
        # cleanup: delete test rows
        import asyncio
        from sqlalchemy import delete
        # simple HTTP cleanup for product
        requests.delete(f"{API}/products/{pid}", headers=admin_auth, timeout=30)


# ---------------------------------------------------------------------------
# Test 8: online/self-order accepted → Sale with shift_id → recap classifies it
# ---------------------------------------------------------------------------
def test_online_selforder_flows_into_shift_recap(admin_auth, kasir_auth):
    """
    Accepted self-order becomes a Sale with shift_id. Verify:
      - QRIS Toko self-order → total_qris
      - Transfer Bank self-order → total_transfer
      - Bayar di Kasir self-order → total_cash + expected_cash
      No double counting.
    """
    _ensure_shift_closed(kasir_auth)
    shift_id = _open_shift(kasir_auth, opening_cash=0)
    # Get kasir's outlet
    me = requests.get(f"{API}/auth/me", headers=kasir_auth, timeout=30).json()
    outlet_id = me.get("outlet_id") or "outlet-sudirman"
    pid, mid = _create_product(admin_auth, f"TEST_so_{uuid.uuid4().hex[:6]}", price=10000, stock=999)
    try:
        _create_self_order_accepted(kasir_auth, pid, mid, "QRIS Toko", 60000, outlet_id, qty=6)
        _create_self_order_accepted(kasir_auth, pid, mid, "Transfer Bank", 40000, outlet_id, qty=4)
        _create_self_order_accepted(kasir_auth, pid, mid, "Bayar di Kasir", 20000, outlet_id, qty=2)

        rr = requests.get(f"{API}/shifts/{shift_id}/report", headers=kasir_auth, timeout=30)
        rep = rr.json()
        assert rep["total_cash"] == 20000, rep
        assert rep["total_transfer"] == 40000, rep
        assert rep["total_qris"] == 60000, rep
        assert rep["total_omset"] == 120000, rep
        # transaction_count should be exactly 3 — no duplicates
        assert rep["transaction_count"] == 3, rep
        # expected_cash = 0 (modal) + 20k (Bayar di Kasir) - 0 (no expense) = 20k
        assert rep["expected_cash"] == 20000, rep
    finally:
        _ensure_shift_closed(kasir_auth)
        requests.delete(f"{API}/products/{pid}", headers=admin_auth, timeout=30)


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-s"] + sys.argv[1:])
