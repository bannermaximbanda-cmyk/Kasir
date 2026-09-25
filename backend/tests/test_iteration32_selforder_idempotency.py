"""
Iter32 — Self-order idempotency guard (critical production bug fix).

Reproduces the reported bug: 3 duplicate "Meja 001 · 3× Es Kosong" orders from a
single customer tap-flood. With this fix in place, 5 concurrent POSTs with the
same idempotency_key produce exactly 1 SelfOrder row.

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
def auth():
    tok = _login("superadmin", ".Superadmin1_")
    return {"Authorization": f"Bearer {tok}", **HEADERS_CSRF}


@pytest.fixture(scope="module")
def test_product(auth):
    tag = uuid.uuid4().hex[:8]
    merchants = requests.get(f"{API}/merchants", headers=auth, timeout=30).json()
    merchant_id = merchants[0]["id"]
    r = requests.post(f"{API}/products/bulk-import", json={
        "outlet_id_explicit": True, "mode": "upsert",
        "rows": [{"name": f"TEST_Iter32_{tag}", "sku": f"TEST_ITER32_{tag}",
                  "merchant_id": merchant_id, "outlet_id": "outlet-sudirman",
                  "price": 2000, "cost": 500, "stock": 999, "status_aktif": 1}],
    }, headers=auth, timeout=30)
    assert r.status_code == 200, r.text
    plist = requests.get(f"{API}/products?outlet_id=outlet-sudirman", headers=auth, timeout=30).json()
    p = next((x for x in plist if x.get("sku") == f"TEST_ITER32_{tag}"), None)
    assert p is not None
    yield p
    requests.delete(f"{API}/products/{p['id']}", headers=auth, timeout=30)


@pytest.fixture(scope="module")
def open_shift(auth):
    """Self-order endpoint requires an open shift in the outlet — provision one."""
    shifts = requests.get(f"{API}/shifts?outlet_id=outlet-sudirman", headers=auth, timeout=45).json()
    open_ones = [s for s in shifts if s.get("status") == "open"]
    if open_ones:
        yield open_ones[0]["id"]
        return
    r = requests.post(f"{API}/shifts/open", json={"opening_balance": 100000, "note": "TEST_iter32"},
                      headers=auth, timeout=45)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    yield sid
    requests.post(f"{API}/shifts/{sid}/close", json={"closing_balance": 100000, "note": "TEST_iter32 close"},
                  headers=auth, timeout=45)


def _cleanup(auth, idem_key):
    import subprocess
    subprocess.run(["python3", "-c", f"""
import asyncio
from database import AsyncSessionLocal
from sqlalchemy import text
async def m():
    async with AsyncSessionLocal() as s:
        await s.execute(text(\"DELETE FROM mjd_self_orders WHERE idempotency_key='{idem_key}'\"))
        await s.commit()
asyncio.run(m())
"""], cwd="/app/backend", timeout=15, check=False)


def test_five_rapid_taps_create_only_one_order(auth, test_product, open_shift):
    """SIMULATION OF PROD BUG: 5 concurrent POSTs with the same idempotency_key → 1 row."""
    idem_key = f"test-idem-{uuid.uuid4().hex}"
    payload = {
        "idempotency_key": idem_key,
        "outlet_id": "outlet-sudirman",
        "table": "TEST_Meja_001",
        "customer_name": f"TEST_Tap_{uuid.uuid4().hex[:6]}",
        "customer_phone": "628999999TEST",
        "lines": [{"product_id": test_product["id"], "name": test_product["name"], "quantity": 3, "price": 2000}],
        "subtotal": 6000, "total": 6000,
        "payment_method": "QRIS",
        "payment_proof": "data:image/svg+xml;base64,PHN2Zy8+",
        "notes": "TEST_iter32_rapid_tap",
    }

    async def fire_all():
        async with aiohttp.ClientSession(headers={"X-Requested-With": "mjd-kupi", "Content-Type": "application/json"}) as sess:
            tasks = [sess.post(f"{API}/self-order", json=payload) for _ in range(5)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            out = []
            for r in results:
                if isinstance(r, Exception):
                    out.append({"error": repr(r)}); continue
                data = await r.json(); data["_status"] = r.status; out.append(data)
                r.close()
            return out

    results = asyncio.run(fire_all())
    try:
        # All should return 200 (never error)
        statuses = [r.get("_status") for r in results]
        assert all(s == 200 for s in statuses), f"unexpected statuses: {statuses}"
        # Every response must reference the SAME order id — replays included.
        ids = [r.get("id") for r in results if r.get("id")]
        assert len(ids) == 5, f"expected 5 successful responses, got: {results}"
        unique_ids = set(ids)
        assert len(unique_ids) == 1, f"5 rapid taps produced {len(unique_ids)} different orders (must be 1): {unique_ids}"
        # At least 4 of the 5 responses must carry _idempotent_replay=True (the first insert may not, race-dependent).
        replay_count = sum(1 for r in results if r.get("_idempotent_replay") is True)
        assert replay_count >= 4, f"replay flag missing on too many responses: {replay_count}/5"

        # DB truth check: exactly 1 SelfOrder for this key.
        import subprocess
        proc = subprocess.run(["python3", "-c", f"""
import asyncio
from database import AsyncSessionLocal
from sqlalchemy import text
async def m():
    async with AsyncSessionLocal() as s:
        r = await s.execute(text(\"SELECT COUNT(*) FROM mjd_self_orders WHERE idempotency_key='{idem_key}'\"))
        print(r.scalar())
asyncio.run(m())
"""], cwd="/app/backend", capture_output=True, text=True, timeout=15)
        assert proc.returncode == 0, proc.stderr
        count = int(proc.stdout.strip())
        assert count == 1, f"expected 1 row, got {count}"
    finally:
        _cleanup(auth, idem_key)


def test_different_keys_create_different_orders(auth, test_product, open_shift):
    """Sanity: idempotency is scoped by key, not by customer/table."""
    keys = [f"test-idem-{uuid.uuid4().hex}" for _ in range(2)]
    try:
        for k in keys:
            r = requests.post(f"{API}/self-order", json={
                "idempotency_key": k,
                "outlet_id": "outlet-sudirman", "table": "TEST_Meja_002",
                "customer_name": "TEST_DiffKeys", "customer_phone": "6281200000",
                "lines": [{"product_id": test_product["id"], "name": test_product["name"], "quantity": 1, "price": 2000}],
                "subtotal": 2000, "total": 2000, "payment_method": "Cash",
            }, headers={"X-Requested-With": "mjd-kupi"}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json().get("_idempotent_replay") is not True
    finally:
        for k in keys:
            _cleanup(auth, k)


def test_replay_returns_same_id_within_window(auth, test_product, open_shift):
    """A repeat POST with the same key >0s later must still return the same order."""
    idem_key = f"test-idem-{uuid.uuid4().hex}"
    payload = {
        "idempotency_key": idem_key,
        "outlet_id": "outlet-sudirman", "table": "TEST_Meja_003",
        "customer_name": "TEST_Replay", "customer_phone": "6281300000",
        "lines": [{"product_id": test_product["id"], "name": test_product["name"], "quantity": 1, "price": 2000}],
        "subtotal": 2000, "total": 2000, "payment_method": "QRIS",
    }
    try:
        r1 = requests.post(f"{API}/self-order", json=payload, headers={"X-Requested-With": "mjd-kupi"}, timeout=15)
        assert r1.status_code == 200
        time.sleep(1.5)
        r2 = requests.post(f"{API}/self-order", json=payload, headers={"X-Requested-With": "mjd-kupi"}, timeout=15)
        assert r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"], "replay must return same order id"
        assert r2.json().get("_idempotent_replay") is True
    finally:
        _cleanup(auth, idem_key)
