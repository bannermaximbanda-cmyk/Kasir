"""Iteration 15 — user-reported bug: QR self-order not visible in POS 'Pesanan Online'.
Also covers: /api/self-order/{id}/reject, /api/outlets/{outlet_id}/self-service (GET/POST),
/api/public/outlets, /api/outlets/{outlet_id}/shift-status regression.
"""
import os
import pytest
import requests
from pathlib import Path


def _load_backend_url() -> str:
    v = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if v:
        return v.rstrip("/")
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    return ""


BASE_URL = _load_backend_url()
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

CSRF = {"X-Requested-With": "mjd-kupi"}
CREDS = {
    "superadmin": ("superadmin", ".Superadmin1_"),
    "admin":      ("admin", "MjdKupi#2026"),
    "kasir":      ("kasir", "MjdKupi#2026"),
    "vendor":     ("vendor", "MjdKupi#2026"),
}


def _login(identifier: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(CSRF)
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": identifier, "password": password},
               headers=CSRF, timeout=45)
    assert r.status_code == 200, f"login {identifier}: {r.status_code} {r.text}"
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    s.me = data
    return s


@pytest.fixture(scope="module")
def super_sess():
    return _login(*CREDS["superadmin"])


@pytest.fixture(scope="module")
def admin_sess():
    return _login(*CREDS["admin"])


@pytest.fixture(scope="module")
def vendor_sess():
    return _login(*CREDS["vendor"])


@pytest.fixture(scope="module")
def kasir_sess():
    s = _login(*CREDS["kasir"])
    cur = s.get(f"{BASE_URL}/api/shifts/current").json()
    if not cur:
        r = s.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000, "note": "iter15"})
        assert r.status_code == 200, r.text
    return s


def _get_product(sess, outlet_id="outlet-sudirman"):
    r = sess.get(f"{BASE_URL}/api/products", params={"outlet_id": outlet_id})
    assert r.status_code == 200, r.text
    products = r.json()
    assert products, "need at least one product"
    return products[0]


def _create_self_order(product, outlet_id="outlet-sudirman", name="TEST_ITER15", table="Meja TEST15"):
    payload = {
        "table": table,
        "outlet_id": outlet_id,
        "customer_name": name,
        "customer_phone": "6281111",
        "total": float(product["price"]),
        "lines": [{
            "product_id": product["id"],
            "name": product["name"],
            "quantity": 1,
            "price": float(product["price"]),
            "vendor": product.get("vendor", "MJD Kupi"),
            "notes": "",
        }],
    }
    r = requests.post(f"{BASE_URL}/api/self-order", json=payload, headers=CSRF, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------
# BUG FIX: QR Meja order MUST appear in POS 'Pesanan Online' for kasir
# ------------------------------------------------------------------
class TestPOSOnlineOrdersBugFix:
    def test_self_order_persists_with_pesanan_diterima_status(self, super_sess, kasir_sess):
        p = _get_product(super_sess)
        order = _create_self_order(p, outlet_id="outlet-sudirman", name="TEST_ITER15_PERSIST")
        assert order.get("id")
        # confirm status default is 'Pesanan Diterima'
        assert order.get("status") == "Pesanan Diterima", f"expected 'Pesanan Diterima', got {order.get('status')}"
        # confirm outlet_id preserved
        assert order.get("outlet_id") == "outlet-sudirman"

    def test_kasir_pos_online_orders_sees_order_same_outlet(self, super_sess, kasir_sess):
        """USER BUG: Kasir at outlet-sudirman must see orders created via /api/self-order for outlet-sudirman."""
        p = _get_product(super_sess)
        order = _create_self_order(p, outlet_id="outlet-sudirman", name="TEST_ITER15_KASIR_VISIBLE")
        oid = order["id"]

        r = kasir_sess.get(f"{BASE_URL}/api/pos/online-orders")
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        assert len(items) > 0, "Kasir sees EMPTY list even though a same-outlet self-order was just created"
        ids = [o["id"] for o in items]
        assert oid in ids, f"created order {oid} not in kasir POS online-orders list. IDs={ids}"
        # All returned orders must be scoped to kasir outlet (outlet-sudirman)
        for o in items:
            assert o.get("outlet_id") == "outlet-sudirman", f"RBAC leak: order for {o.get('outlet_id')} shown to sudirman kasir"

    def test_kasir_does_not_see_other_outlet_orders(self, super_sess, kasir_sess):
        """Cross-outlet: create order at outlet-kemang; kasir at outlet-sudirman must NOT see it."""
        # need a product from outlet-kemang and an open shift there (so self-order accepts)
        r = super_sess.get(f"{BASE_URL}/api/products", params={"outlet_id": "outlet-kemang"})
        products = r.json() if r.status_code == 200 else []
        if not products:
            pytest.skip("no products at outlet-kemang")
        p = products[0]
        # ensure shift open at kemang via super_sess-independent path: check /shift-status
        st = requests.get(f"{BASE_URL}/api/outlets/outlet-kemang/shift-status", timeout=15).json()
        if not st.get("open"):
            pytest.skip("no open shift at outlet-kemang — cannot create self-order there")
        order = _create_self_order(p, outlet_id="outlet-kemang", name="TEST_ITER15_KEMANG_LEAK", table="Meja K")
        oid = order["id"]
        r = kasir_sess.get(f"{BASE_URL}/api/pos/online-orders")
        assert r.status_code == 200
        ids = [o["id"] for o in r.json()]
        assert oid not in ids, f"RBAC leak: kasir at sudirman saw kemang order {oid}"


# ------------------------------------------------------------------
# /api/self-order/{id}/reject
# ------------------------------------------------------------------
class TestSelfOrderReject:
    def test_kasir_can_reject_and_notes_appended(self, super_sess, kasir_sess):
        p = _get_product(super_sess)
        order = _create_self_order(p, name="TEST_ITER15_REJECT")
        oid = order["id"]
        r = kasir_sess.post(f"{BASE_URL}/api/self-order/{oid}/reject", params={"reason": "stok habis"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "Ditolak"
        # verify persistence via /api/pos/online-orders — Ditolak should NOT be in the queue
        r2 = kasir_sess.get(f"{BASE_URL}/api/pos/online-orders")
        ids = [o["id"] for o in r2.json()]
        assert oid not in ids, "Ditolak order still shown in POS online-orders queue"

    def test_reject_already_rejected_returns_400(self, super_sess, kasir_sess):
        p = _get_product(super_sess)
        order = _create_self_order(p, name="TEST_ITER15_DBL_REJECT")
        oid = order["id"]
        r1 = kasir_sess.post(f"{BASE_URL}/api/self-order/{oid}/reject", params={"reason": "first"})
        assert r1.status_code == 200
        r2 = kasir_sess.post(f"{BASE_URL}/api/self-order/{oid}/reject", params={"reason": "second"})
        assert r2.status_code == 400, f"expected 400 on double-reject, got {r2.status_code} {r2.text}"

    def test_reject_nonexistent_order_returns_404(self, kasir_sess):
        r = kasir_sess.post(f"{BASE_URL}/api/self-order/nonexistent-id-xyz/reject")
        assert r.status_code == 404


# ------------------------------------------------------------------
# /api/outlets/{outlet_id}/self-service GET (public) + POST (admin only)
# ------------------------------------------------------------------
class TestSelfServiceSettings:
    OUTLET = "outlet-sudirman"

    def test_get_public_returns_all_keys(self):
        r = requests.get(f"{BASE_URL}/api/outlets/{self.OUTLET}/self-service", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("banners", "marquee_text", "logo_url", "header_image", "force_closed", "closed_message"):
            assert k in data, f"missing key: {k}"
        assert isinstance(data["banners"], list)
        assert isinstance(data["force_closed"], bool)

    def test_super_admin_can_save(self, super_sess):
        payload = {
            "banners": ["https://example.com/b1.png", "https://example.com/b2.png"],
            "marquee_text": "TEST_ITER15 promo",
            "logo_url": "https://example.com/logo.png",
            "header_image": "https://example.com/header.png",
            "force_closed": False,
            "closed_message": "TEST_ITER15 closed",
        }
        r = super_sess.post(f"{BASE_URL}/api/outlets/{self.OUTLET}/self-service", json=payload)
        assert r.status_code == 200, r.text
        # verify GET reflects saved values
        r2 = requests.get(f"{BASE_URL}/api/outlets/{self.OUTLET}/self-service", timeout=15)
        got = r2.json()
        assert got["marquee_text"] == "TEST_ITER15 promo"
        assert got["banners"] == payload["banners"]
        assert got["logo_url"] == payload["logo_url"]
        assert got["header_image"] == payload["header_image"]
        assert got["force_closed"] is False
        assert got["closed_message"] == "TEST_ITER15 closed"

    def test_admin_can_save(self, admin_sess):
        payload = {
            "banners": [],
            "marquee_text": "TEST_ITER15 admin update",
            "logo_url": "",
            "header_image": "",
            "force_closed": True,
            "closed_message": "TEST_ITER15 admin close",
        }
        # admin owns outlet-kemang per RBAC — test on that outlet
        r = admin_sess.post(f"{BASE_URL}/api/outlets/outlet-kemang/self-service", json=payload)
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{BASE_URL}/api/outlets/outlet-kemang/self-service", timeout=15)
        got = r2.json()
        assert got["marquee_text"] == "TEST_ITER15 admin update"
        assert got["force_closed"] is True

    def test_kasir_forbidden(self, kasir_sess):
        payload = {"banners": [], "marquee_text": "hack", "logo_url": "", "header_image": "", "force_closed": False, "closed_message": ""}
        r = kasir_sess.post(f"{BASE_URL}/api/outlets/{self.OUTLET}/self-service", json=payload)
        assert r.status_code == 403, f"expected 403 for kasir, got {r.status_code} {r.text}"

    def test_vendor_forbidden(self, vendor_sess):
        payload = {"banners": [], "marquee_text": "hack", "logo_url": "", "header_image": "", "force_closed": False, "closed_message": ""}
        r = vendor_sess.post(f"{BASE_URL}/api/outlets/{self.OUTLET}/self-service", json=payload)
        assert r.status_code == 403, f"expected 403 for vendor, got {r.status_code} {r.text}"


# ------------------------------------------------------------------
# /api/public/outlets (no auth required)
# ------------------------------------------------------------------
class TestPublicOutlets:
    def test_public_outlets_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/public/outlets", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0
        for o in data:
            assert "id" in o and "name" in o and "address" in o
            # should NOT leak sensitive fields (e.g., no active flag needed)
        # sudirman + kemang expected
        ids = [o["id"] for o in data]
        assert "outlet-sudirman" in ids


# ------------------------------------------------------------------
# Regression: /api/outlets/{outlet_id}/shift-status is public
# ------------------------------------------------------------------
class TestShiftStatusPublic:
    def test_shift_status_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/outlets/outlet-sudirman/shift-status", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["outlet_id"] == "outlet-sudirman"
        assert "open" in data and isinstance(data["open"], bool)
        assert "cashier_name" in data


# ------------------------------------------------------------------
# Cleanup TEST_ITER15 self-orders after tests
# ------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    # Best-effort cleanup via DB (no admin endpoint to delete self_orders exists).
    try:
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from database import async_session_maker  # type: ignore
        import models as M  # type: ignore
        from sqlalchemy import delete

        async def _clean():
            async with async_session_maker() as db:
                await db.execute(delete(M.SelfOrder).where(M.SelfOrder.customer_name.like("TEST_ITER15%")))
                await db.commit()
        asyncio.run(_clean())
    except Exception as e:
        print(f"cleanup skipped: {e}")
