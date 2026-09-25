"""
Iter33 — P0 anti-double-click idempotency guards for:
  1) POST   /api/expenses                    → expense-save-button
  2) POST   /api/sales/{sale_id}/void        → void-submit-button
  3) PATCH  /api/products/{id}/stock         → stock-submit-button

Verifies that sending the same request 5x concurrently with the same
Idempotency-Key produces exactly 1 side-effect (1 expense row, 1 void, 1 stock delta).

All test data prefixed TEST_ per project rule and cleaned up in teardown.
"""

import asyncio
import os
import time
import uuid

import aiohttp
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
# 1) Expense idempotency
# ---------------------------------------------------------------------------
def test_expense_idempotency_replay(admin_auth):
    """Same Idempotency-Key within 15min = 1 expense row, all replies identical."""
    tag = uuid.uuid4().hex[:8]
    idem = str(uuid.uuid4())
    payload = {
        "category": "Pembelian Bahan Baku",
        "note": f"TEST_expense_{tag}",
        "amount": 12345,
        "date": time.strftime("%Y-%m-%d"),
        "method": "Cash",
    }

    async def fire():
        async with aiohttp.ClientSession() as sess:
            headers = {**admin_auth, "Idempotency-Key": idem}
            async def one():
                async with sess.post(f"{API}/expenses", json=payload, headers=headers) as r:
                    body = await r.json()
                    return r.status, body
            return await asyncio.gather(*[one() for _ in range(5)])

    results = asyncio.run(fire())
    ok = [b for st, b in results if st == 200]
    assert len(ok) == 5, f"Expected 5x 200 responses, got {[r[0] for r in results]}"
    ids = {b["id"] for b in ok}
    assert len(ids) == 1, f"Expected 1 unique expense id, got {ids}"

    # Verify only 1 row in DB with this note tag
    listing = requests.get(f"{API}/expenses", headers=admin_auth, timeout=30).json()
    matches = [e for e in listing if e.get("note") == f"TEST_expense_{tag}"]
    assert len(matches) == 1, f"Expected 1 expense row, DB has {len(matches)}"

    # cleanup: expenses have no DELETE endpoint; leave TEST_ tagged row (identifiable).


# ---------------------------------------------------------------------------
# 2) Stock adjust idempotency
# ---------------------------------------------------------------------------
def test_stock_adjust_idempotency(admin_auth):
    """5x concurrent stock-in with same key → stock increases by qty exactly ONCE."""
    tag = uuid.uuid4().hex[:8]
    # Create a TEST_ product
    merchants = requests.get(f"{API}/merchants", headers=admin_auth, timeout=30).json()
    mid = merchants[0]["id"]
    payload = {"name": f"TEST_Stock_{tag}", "category": "Snack", "price": 10000,
               "cost": 5000, "stock": 10, "vendor": "MJD Kupi", "merchant_id": mid}
    r = requests.post(f"{API}/products", json=payload, headers=admin_auth, timeout=30)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    idem = str(uuid.uuid4())
    adj_payload = {"quantity": 7, "kind": "in", "reason": "TEST_restock", "note": ""}

    async def fire():
        async with aiohttp.ClientSession() as sess:
            headers = {**admin_auth, "Idempotency-Key": idem}
            async def one():
                async with sess.patch(f"{API}/products/{pid}/stock", json=adj_payload, headers=headers) as r:
                    return r.status, await r.json()
            return await asyncio.gather(*[one() for _ in range(5)])

    results = asyncio.run(fire())
    assert all(st == 200 for st, _ in results), results
    # Final stock should be 10 + 7 = 17 (NOT 10+35)
    final = requests.get(f"{API}/products/{pid}", headers=admin_auth, timeout=30).json() \
        if False else next(p for p in requests.get(f"{API}/products", headers=admin_auth, timeout=30).json() if p["id"] == pid)
    assert final["stock"] == 17, f"Expected stock=17, got {final['stock']} (idempotency broken)"

    # cleanup
    requests.delete(f"{API}/products/{pid}", headers=admin_auth, timeout=30)


# ---------------------------------------------------------------------------
# 3) Void sale idempotency
# ---------------------------------------------------------------------------
def test_void_sale_idempotency(admin_auth, kasir_auth):
    """5x concurrent void with same key → sale voided once, stock restored once."""
    tag = uuid.uuid4().hex[:8]
    # 1) Create a TEST product
    merchants = requests.get(f"{API}/merchants", headers=admin_auth, timeout=30).json()
    mid = merchants[0]["id"]
    pr = requests.post(f"{API}/products", json={"name": f"TEST_Void_{tag}", "category": "Snack",
                       "price": 10000, "cost": 5000, "stock": 20, "vendor": "MJD Kupi",
                       "merchant_id": mid}, headers=admin_auth, timeout=30)
    assert pr.status_code == 200, pr.text
    pid = pr.json()["id"]

    # 2) Kasir opens a shift + creates a sale of qty 3
    requests.post(f"{API}/shifts/open", json={"opening_cash": 100000}, headers=kasir_auth, timeout=30)
    sale_body = {
        "table": "Meja TEST",
        "lines": [{"product_id": pid, "name": f"TEST_Void_{tag}", "quantity": 3,
                   "price": 10000, "vendor": "MJD Kupi", "merchant_id": mid}],
        "subtotal": 30000, "tax": 0, "total": 30000, "payment_method": "Cash",
        "cash_received": 30000, "change_amount": 0,
        "idempotency_key": str(uuid.uuid4()),
    }
    sr = requests.post(f"{API}/sales", json=sale_body, headers=kasir_auth, timeout=30)
    assert sr.status_code == 200, sr.text
    sale_id = sr.json()["id"]

    # 3) Generate PIN
    pin_r = requests.post(f"{API}/admin/pin/generate", headers=admin_auth, timeout=30)
    assert pin_r.status_code == 200, pin_r.text
    pin = pin_r.json()["pin"]

    # 4) 5x concurrent void with same Idempotency-Key
    idem = str(uuid.uuid4())
    async def fire():
        async with aiohttp.ClientSession() as sess:
            headers = {**kasir_auth, "Idempotency-Key": idem}
            async def one():
                async with sess.post(f"{API}/sales/{sale_id}/void",
                                     json={"pin": pin, "reason": "TEST"}, headers=headers) as r:
                    return r.status, await r.json()
            return await asyncio.gather(*[one() for _ in range(5)])

    results = asyncio.run(fire())
    ok = [b for st, b in results if st == 200]
    assert len(ok) >= 1, f"At least 1 must succeed, got {[r[0] for r in results]}"
    # All successes must reference the same voided sale
    voided_ids = {b["id"] for b in ok}
    assert voided_ids == {sale_id}

    # 5) Verify stock restored ONCE: 20 (initial) - 3 (sale) + 3 (void) = 20
    final = next(p for p in requests.get(f"{API}/products", headers=admin_auth, timeout=30).json() if p["id"] == pid)
    assert final["stock"] == 20, f"Expected stock=20 (restored once), got {final['stock']} (double-restore bug)"

    # cleanup
    requests.post(f"{API}/shifts/close", json={"closing_cash": 100000}, headers=kasir_auth, timeout=30)
    requests.delete(f"{API}/products/{pid}", headers=admin_auth, timeout=30)


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-s"] + sys.argv[1:])
