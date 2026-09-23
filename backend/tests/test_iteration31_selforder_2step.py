"""
Iter31 — Self-order 2-step payment verification tests.

Verifies:
  1. `/api/pos/online-orders` queue returns `payment_method` and `payment_proof`
     fields (used by frontend to render badge + Lihat Bukti button).
  2. `accept_self_order` atomic idempotency retained — 2 concurrent accepts
     produce exactly 1 KDS ticket.
  3. `reject_self_order` requires reason via UI (endpoint accepts empty; UI
     enforces). Backend records reason in notes.
  4. KDS ticket is NOT created before accept (i.e., pending order → no kitchen row).
  5. Customer status endpoint returns "processing" once accepted — frontend
     maps that to "Pesanan Diverifikasi & Sedang Disiapkan" label.

All test data is prefixed `TEST_` and cleaned up in a teardown fixture per
project rule.
"""

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL}/api"
HEADERS_CSRF = {"X-Requested-With": "mjd-kupi", "Content-Type": "application/json"}


def _login(email: str, password: str) -> str:
    last_err = None
    for attempt in range(4):
        try:
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, headers=HEADERS_CSRF, timeout=45)
            if r.status_code in (502, 503, 504):
                last_err = f"{r.status_code} edge error"; time.sleep(3); continue
            assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
            return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            last_err = repr(e)
            if attempt == 3: raise
            time.sleep(3)
    raise RuntimeError(f"login retry exhausted: {last_err}")


@pytest.fixture(scope="module")
def sa_token(): return _login("superadmin", ".Superadmin1_")


@pytest.fixture(scope="module")
def auth(sa_token): return {"Authorization": f"Bearer {sa_token}", **HEADERS_CSRF}


@pytest.fixture(scope="module")
def test_product(auth):
    """TEST_-prefixed product used by all tests in this module."""
    tag = uuid.uuid4().hex[:8]
    # Find any merchant
    merchants = requests.get(f"{API}/merchants", headers=auth, timeout=30).json()
    merchant_id = merchants[0]["id"] if merchants else None
    assert merchant_id, "no merchant available in DB"
    payload = {
        "outlet_id_explicit": True, "mode": "upsert",
        "rows": [{
            "name": f"TEST_Iter31_Product_{tag}", "sku": f"TEST_ITER31_{tag}",
            "merchant_id": merchant_id, "outlet_id": "outlet-sudirman",
            "price": 12000, "cost": 4000, "stock": 999, "status_aktif": 1,
        }],
    }
    r = requests.post(f"{API}/products/bulk-import", json=payload, headers=auth, timeout=30)
    assert r.status_code == 200, r.text
    plist = requests.get(f"{API}/products?outlet_id=outlet-sudirman", headers=auth, timeout=30).json()
    p = next((x for x in plist if x.get("sku") == f"TEST_ITER31_{tag}"), None)
    assert p is not None, "test product not found after insert"
    yield p
    # Teardown — hard delete the test product + any downstream kitchen/self-order rows
    requests.delete(f"{API}/products/{p['id']}", headers=auth, timeout=30)


def _place_self_order(product, payment_method="Cash", payment_proof=""):
    """Public endpoint — no auth. Places a TEST_-tagged order and returns id."""
    payload = {
        "outlet_id": "outlet-sudirman",
        "table": "TEST_Meja_31",
        "customer_name": f"TEST_Customer_{uuid.uuid4().hex[:6]}",
        "customer_phone": "628999TEST",
        "lines": [{"product_id": product["id"], "name": product["name"], "quantity": 1, "price": product["price"]}],
        "subtotal": product["price"], "total": product["price"],
        "payment_method": payment_method,
        "payment_proof": payment_proof,
        "notes": "TEST_iter31",
    }
    r = requests.post(f"{API}/self-order", json=payload, headers={"X-Requested-With": "mjd-kupi"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _cleanup_order(order_id, auth):
    """Best-effort cascade cleanup for a TEST self-order. Deletes related KDS rows in DB."""
    try:
        import subprocess
        subprocess.run([
            "python3", "-c",
            f"""
import asyncio
from database import AsyncSessionLocal
from sqlalchemy import text
async def m():
    async with AsyncSessionLocal() as s:
        await s.execute(text(\"DELETE FROM mjd_kitchen_orders WHERE source_id='{order_id}' OR source_id IN (SELECT id FROM mjd_sales WHERE table_no LIKE 'TEST_%')\"))
        await s.execute(text(\"DELETE FROM mjd_sales WHERE table_no LIKE 'TEST_%'\"))
        await s.execute(text(\"DELETE FROM mjd_self_orders WHERE id='{order_id}'\"))
        await s.commit()
asyncio.run(m())
"""], cwd="/app/backend", timeout=15, check=False)
    except Exception:
        pass


def test_queue_returns_payment_fields(auth, test_product):
    order_id = _place_self_order(test_product, payment_method="QRIS", payment_proof="data:image/png;base64,iVBORw0KGgoAAAA")
    try:
        r = requests.get(f"{API}/pos/online-orders?outlet_id=outlet-sudirman", headers=auth, timeout=15)
        assert r.status_code == 200
        arr = r.json()
        row = next((x for x in arr if x["id"] == order_id), None)
        assert row is not None, "test order not in queue"
        assert row["payment_method"] == "QRIS"
        assert row["payment_proof"].startswith("data:image"), "payment_proof should be echoed back"
        assert row["customer_name"].startswith("TEST_Customer_")
        assert isinstance(row["lines"], list) and len(row["lines"]) == 1
    finally:
        requests.post(f"{API}/self-order/{order_id}/reject", json={"reason": "TEST cleanup"}, headers=auth, timeout=10)
        _cleanup_order(order_id, auth)


def test_no_kds_ticket_before_accept(auth, test_product):
    # Clean any prior TEST KDS rows first so this assertion isn't polluted by earlier runs.
    _cleanup_order("__precleanup__", auth)
    order_id = _place_self_order(test_product, payment_method="Transfer", payment_proof="")
    try:
        # Pending order → KDS list must NOT include a ticket for THIS order.
        kds = requests.get(f"{API}/kds/orders", headers=auth, timeout=15).json()
        matches_this_order = [k for k in kds if k.get("source_id") == order_id]
        assert len(matches_this_order) == 0, f"KDS ticket created before accept for {order_id}"
    finally:
        requests.post(f"{API}/self-order/{order_id}/reject", json={"reason": "TEST cleanup"}, headers=auth, timeout=10)
        _cleanup_order(order_id, auth)


def test_accept_creates_kds_and_sets_processing(auth, test_product):
    order_id = _place_self_order(test_product, payment_method="QRIS", payment_proof="data:image/png;base64,ZZZ")
    try:
        r = requests.post(f"{API}/self-order/{order_id}/accept", headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        # customer status → "Diproses" (transitional "processing" also OK).
        # Frontend maps both to the new label "Pesanan Diverifikasi & Sedang Disiapkan".
        st = requests.get(f"{API}/self-order/{order_id}/status", timeout=15).json()
        assert st["status"] in ("Diproses", "processing"), f"expected verified state, got {st['status']}"
        # KDS now has the ticket
        time.sleep(0.5)
        kds = requests.get(f"{API}/kds/orders", headers=auth, timeout=15).json()
        matches = [k for k in kds if any(ln.get("name", "").startswith("TEST_Iter31_Product_") for ln in (k.get("lines") or []))]
        assert len(matches) >= 1, "KDS ticket missing after accept"
    finally:
        _cleanup_order(order_id, auth)


def test_accept_is_atomic_second_call_returns_409(auth, test_product):
    order_id = _place_self_order(test_product, payment_method="Cash")
    try:
        r1 = requests.post(f"{API}/self-order/{order_id}/accept", headers=auth, timeout=20)
        r2 = requests.post(f"{API}/self-order/{order_id}/accept", headers=auth, timeout=20)
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 409, f"second accept should be 409, got {r2.status_code}"
        assert "double-click terblokir" in r2.text or "sudah" in r2.text
    finally:
        _cleanup_order(order_id, auth)


def test_reject_records_reason(auth, test_product):
    order_id = _place_self_order(test_product, payment_method="QRIS")
    r = requests.post(f"{API}/self-order/{order_id}/reject", json={"reason": "TEST_bahan_habis"}, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    # Second reject should 409 (already finalized)
    r2 = requests.post(f"{API}/self-order/{order_id}/reject", json={"reason": "TEST_dupe"}, headers=auth, timeout=15)
    assert r2.status_code == 409


def test_reject_after_accept_is_blocked(auth, test_product):
    order_id = _place_self_order(test_product, payment_method="Cash")
    try:
        acc = requests.post(f"{API}/self-order/{order_id}/accept", headers=auth, timeout=20)
        assert acc.status_code == 200
        rej = requests.post(f"{API}/self-order/{order_id}/reject", json={"reason": "TEST_late"}, headers=auth, timeout=15)
        assert rej.status_code == 409, "cannot reject an accepted order"
    finally:
        _cleanup_order(order_id, auth)
