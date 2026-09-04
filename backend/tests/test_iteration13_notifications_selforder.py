"""Iteration 13 (MJD Kupi Batch B) — Notification Center + SelfOrder customer_phone + variant/notes handling."""
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
    "kasir":      ("kasir", "MjdKupi#2026"),
}
ALLOWED_TYPES = {"stock", "shift", "order"}
ALLOWED_SEVERITY = {"critical", "warning", "info"}


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
def kasir_sess():
    s = _login(*CREDS["kasir"])
    cur = s.get(f"{BASE_URL}/api/shifts/current").json()
    if not cur:
        r = s.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000, "note": "iter13"})
        assert r.status_code == 200, r.text
    return s


# ---------- Notifications endpoint ----------
class TestNotifications:
    def test_super_admin_aggregate_all_outlets(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/notifications")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "unread_count" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["unread_count"], int)
        assert data["unread_count"] == len(data["items"])
        # items shape
        for it in data["items"]:
            assert set(["id", "type", "severity", "title", "detail", "created_at", "action"]).issubset(it.keys())
            assert it["type"] in ALLOWED_TYPES
            assert it["severity"] in ALLOWED_SEVERITY
            assert isinstance(it["title"], str) and len(it["title"]) > 0

    def test_sorted_newest_first(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/notifications")
        items = r.json()["items"]
        if len(items) >= 2:
            for a, b in zip(items, items[1:]):
                assert a["created_at"] >= b["created_at"], f"not sorted desc: {a['created_at']} < {b['created_at']}"

    def test_scope_filter_outlet_id(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/notifications", params={"outlet_id": "outlet-kemang"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data["items"], list)
        # detail of stock items must reference outlet 'Kemang'
        for it in data["items"]:
            if it["type"] == "stock":
                assert "Kemang" in it["detail"], f"stock detail should reference Kemang: {it['detail']}"

    def test_kasir_scoped_to_own_outlet(self, kasir_sess):
        r = kasir_sess.get(f"{BASE_URL}/api/notifications")
        assert r.status_code == 200, r.text
        data = r.json()
        # Kasir outlet is outlet-sudirman by default. Server should force their outlet regardless of param.
        r2 = kasir_sess.get(f"{BASE_URL}/api/notifications", params={"outlet_id": "outlet-kemang"})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        # Stock items are stable (not created by other parallel tests). Compare stock-scoped semantics.
        stock1 = sorted([it["id"] for it in data["items"] if it["type"] == "stock"])
        stock2 = sorted([it["id"] for it in d2["items"] if it["type"] == "stock"])
        assert stock1 == stock2, f"Kasir stock scope differs on outlet param — RBAC leak. {stock1} vs {stock2}"
        # No stock notification referencing Kemang for Kasir on outlet-sudirman
        for it in data["items"]:
            if it["type"] == "stock":
                assert "Kemang" not in it["detail"], f"Kasir sees Kemang stock: {it}"

    def test_max_items_bound(self, super_sess):
        # Spec: max 10 items after sort (post-fix)
        r = super_sess.get(f"{BASE_URL}/api/notifications")
        items = r.json()["items"]
        assert len(items) <= 10, f"expected <=10 items after sort+truncate, got {len(items)}"


# ---------- SelfOrder customer_phone ----------
class TestSelfOrderCustomerPhone:
    def _get_product(self, super_sess, outlet_id="outlet-sudirman"):
        r = super_sess.get(f"{BASE_URL}/api/products", params={"outlet_id": outlet_id})
        assert r.status_code == 200, r.text
        products = r.json()
        assert products, "need at least one product"
        # Prefer product with variants if any exists
        with_variants = [p for p in products if p.get("variants")]
        return (with_variants[0] if with_variants else products[0])

    def test_accepts_customer_phone(self, super_sess, kasir_sess):
        # kasir_sess fixture guarantees an open shift at outlet-sudirman
        p = self._get_product(super_sess)
        payload = {
            "table": "Meja TEST_PHONE",
            "outlet_id": "outlet-sudirman",
            "customer_name": "TEST_Phone_User",
            "customer_phone": "6281234567890",
            "total": float(p["price"]),
            "lines": [{
                "product_id": p["id"],
                "name": p["name"],
                "quantity": 1,
                "price": float(p["price"]),
                "vendor": p.get("vendor", "MJD Kupi"),
                "notes": "no ice",
            }],
        }
        # public endpoint - use plain requests
        r = requests.post(f"{BASE_URL}/api/self-order", json=payload, headers=CSRF, timeout=30)
        assert r.status_code == 200, r.text
        order = r.json()
        assert "id" in order
        # persistence via status endpoint
        stat = requests.get(f"{BASE_URL}/api/self-order/{order['id']}/status", timeout=15)
        assert stat.status_code == 200
        assert stat.json()["customer_name"] == "TEST_Phone_User"

    def test_accept_variant_price_authoritative_and_notes_stored(self, super_sess, kasir_sess):
        # Find a product with active variants
        r = super_sess.get(f"{BASE_URL}/api/products", params={"outlet_id": "outlet-sudirman"})
        products = r.json()
        prod_with_var = next((p for p in products if p.get("variants") and any(v.get("active", True) for v in p["variants"])), None)
        if not prod_with_var:
            pytest.skip("no product with active variants available")
        variant = next(v for v in prod_with_var["variants"] if v.get("active", True))
        # Client sends WRONG price on purpose (much lower); server must recompute from variant.price
        wrong_price = 1.0
        payload = {
            "table": "Meja TEST_VAR",
            "outlet_id": "outlet-sudirman",
            "customer_name": "TEST_Variant_User",
            "customer_phone": "628999",
            "total": wrong_price,
            "lines": [{
                "product_id": prod_with_var["id"],
                "name": prod_with_var["name"],
                "quantity": 2,
                "price": wrong_price,
                "variant_id": variant["id"],
                "variant_name": variant.get("name", ""),
                "notes": "extra hot please",
            }],
        }
        r = requests.post(f"{BASE_URL}/api/self-order", json=payload, headers=CSRF, timeout=30)
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]
        # Kasir accepts - server should use variant price authoritatively
        acc = kasir_sess.post(f"{BASE_URL}/api/self-order/{order_id}/accept")
        # NOTE: If backend returns 400 "Pesanan sudah Pesanan Diterima", it means the accept endpoint's
        # allowed-status list is outdated — new self-orders default to "Pesanan Diterima" (per migration
        # at server.py:1916) but accept requires ("Menunggu kasir","Menunggu konfirmasi"). Report as bug.
        if acc.status_code == 400 and "Pesanan sudah" in acc.text:
            pytest.fail(
                "BACKEND BUG: /api/self-order/{id}/accept rejects newly-created self-orders because "
                "default status is 'Pesanan Diterima' but accept allows only ('Menunggu kasir','Menunggu konfirmasi'). "
                "Fix: include 'Pesanan Diterima' in allowed statuses at server.py:1216."
            )
        assert acc.status_code == 200, acc.text
        sale = acc.json()
        expected_price = float(variant["price"])
        assert sale["subtotal"] == expected_price * 2, f"expected {expected_price*2}, got {sale['subtotal']}"
        assert sale["total"] == expected_price * 2
        # Note stored in sale lines
        lines = sale.get("lines") or []
        assert lines, "sale lines empty"
        assert lines[0]["price"] == expected_price
        assert lines[0]["variant_id"] == variant["id"]
        assert lines[0]["variant_name"] == variant.get("name", "")
        assert lines[0]["notes"] == "extra hot please"

    def test_missing_customer_name_rejected(self):
        payload = {
            "table": "Meja X",
            "outlet_id": "outlet-sudirman",
            "customer_name": "",
            "customer_phone": "628",
            "total": 0,
            "lines": [],
        }
        r = requests.post(f"{BASE_URL}/api/self-order", json=payload, headers=CSRF, timeout=15)
        assert r.status_code == 400
