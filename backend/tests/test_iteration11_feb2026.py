"""Iteration 11 — Feb 2026 batch: Variants, White-Label, Feature Toggles, Branding, Subscription."""
import os
import uuid
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
    s.headers.update(CSRF)
    s.me = data
    return s


@pytest.fixture(scope="module")
def super_sess():
    return _login(*CREDS["superadmin"])


@pytest.fixture(scope="module")
def admin_sess():
    return _login(*CREDS["admin"])


@pytest.fixture(scope="module")
def kasir_sess():
    return _login(*CREDS["kasir"])


@pytest.fixture(scope="module", autouse=True)
def _restore_vendor_active(super_sess):
    """Guarantee vendor merchant subscription is 'active' before AND after this module."""
    def restore():
        r = super_sess.get(f"{BASE_URL}/api/merchants")
        assert r.status_code == 200
        vm = next((m for m in r.json() if m["id"] == "m-barista"), None)
        assert vm, "m-barista merchant missing"
        if vm.get("subscription_status") != "active":
            super_sess.put(f"{BASE_URL}/api/merchants/m-barista", json={
                "name": vm["name"], "subscription_status": "active",
            })
    restore()
    yield
    restore()


# ================== Feature Toggles ==================

class TestFeatureToggles:
    def test_get_defaults_shape(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/feature-toggles")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "defaults" in body and "matrix" in body
        for k in ("pos", "kds", "self_order", "inventory", "expenses", "reports"):
            assert k in body["defaults"], f"missing default key {k}"

    def test_post_matrix_persists(self, super_sess):
        payload = {"matrix": {"role:Kasir": {"pos": False, "kds": True}}}
        r = super_sess.post(f"{BASE_URL}/api/feature-toggles", json=payload)
        assert r.status_code == 200, r.text
        # GET back
        g = super_sess.get(f"{BASE_URL}/api/feature-toggles")
        assert g.status_code == 200
        matrix = g.json()["matrix"]
        assert matrix.get("role:Kasir", {}).get("pos") is False
        assert matrix.get("role:Kasir", {}).get("kds") is True

    def test_admin_cannot_save(self, admin_sess):
        r = admin_sess.post(f"{BASE_URL}/api/feature-toggles", json={"matrix": {}})
        assert r.status_code == 403, r.text

    def test_cleanup_reset_matrix(self, super_sess):
        # Clean up so subsequent runs / other suites aren't affected
        r = super_sess.post(f"{BASE_URL}/api/feature-toggles", json={"matrix": {}})
        assert r.status_code == 200


# ================== Product Variants ==================

class TestProductVariants:
    @pytest.fixture(scope="class")
    def product_with_variants(self, super_sess):
        # Locate an existing merchant product to update (p-1 seeded)
        r = super_sess.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        p1 = next((p for p in r.json() if p["id"] == "p-1"), None)
        assert p1, "seed product p-1 missing"
        variants = [
            {"name": "Panas", "price": 18000, "cost": 6500, "active": True},
            {"name": "Ice",   "price": 20000, "cost": 7000, "active": True},
        ]
        payload = {
            "name": p1["name"], "category": p1["category"], "vendor": p1["vendor"],
            "merchant_id": p1.get("merchant_id"), "outlet_id": p1.get("outlet_id", "outlet-sudirman"),
            "price": p1["price"], "cost": p1["cost"], "stock": p1["stock"],
            "color": p1.get("color", "#fff0e6"), "image_url": p1.get("image_url", ""),
            "modifiers": p1.get("modifiers", []), "variants": variants,
        }
        r = super_sess.put(f"{BASE_URL}/api/products/p-1", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    def test_variants_persisted(self, super_sess, product_with_variants):
        # GET and verify persistence
        r = super_sess.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        p1 = next((p for p in r.json() if p["id"] == "p-1"), None)
        assert p1, "product p-1 vanished"
        vs = p1.get("variants") or []
        assert len(vs) == 2, vs
        names = {v["name"] for v in vs}
        assert names == {"Panas", "Ice"}
        for v in vs:
            assert "id" in v and v["id"], f"variant missing id: {v}"

    def test_sale_uses_variant_price(self, kasir_sess, super_sess, product_with_variants):
        # Ensure kasir has open shift
        cur = kasir_sess.get(f"{BASE_URL}/api/shifts/current").json()
        if not cur:
            r = kasir_sess.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000, "note": "iter11"})
            assert r.status_code == 200, r.text
        # Get ICE variant id
        prods = super_sess.get(f"{BASE_URL}/api/products").json()
        p1 = next(p for p in prods if p["id"] == "p-1")
        ice = next(v for v in p1["variants"] if v["name"] == "Ice")
        # Create sale with variant_id — client lies about price=1 to prove server recomputes
        payload = {
            "table": "Meja TEST_VAR",
            "lines": [{
                "product_id": "p-1", "name": "Kopi Susu",
                "quantity": 2, "price": 1,  # server should ignore & use variant price 20000
                "variant_id": ice["id"], "notes": "less sugar please",
            }],
            "subtotal": 2, "tax": 0, "total": 2,
            "payment_method": "Cash", "cash_received": 50000,
        }
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        # 2 * 20000 = 40000 subtotal. Server accepts client tax (0) since 0 <= computed*1.05.
        assert sale["subtotal"] == 40000, sale
        assert sale["total"] == 40000, sale
        lines = sale["lines"]
        assert lines[0]["price"] == 20000
        assert lines[0]["variant_id"] == ice["id"]
        assert lines[0]["variant_name"] == "Ice"
        assert lines[0]["notes"] == "less sugar please"

    def test_sale_rejects_invalid_variant(self, kasir_sess, product_with_variants):
        cur = kasir_sess.get(f"{BASE_URL}/api/shifts/current").json()
        if not cur:
            kasir_sess.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000})
        payload = {
            "table": "Meja BAD_VAR",
            "lines": [{
                "product_id": "p-1", "name": "Kopi",
                "quantity": 1, "price": 1, "variant_id": "does-not-exist-xyz",
            }],
            "subtotal": 1, "tax": 0, "total": 1,
            "payment_method": "Cash", "cash_received": 20000,
        }
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 400, r.text

    def test_notes_truncated_at_200(self, kasir_sess, product_with_variants):
        cur = kasir_sess.get(f"{BASE_URL}/api/shifts/current").json()
        if not cur:
            kasir_sess.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000})
        long_note = "n" * 300
        payload = {
            "table": "Meja NOTES",
            "lines": [{"product_id": "p-1", "name": "Kopi", "quantity": 1, "price": 1, "notes": long_note}],
            "subtotal": 1, "tax": 0, "total": 1,
            "payment_method": "Cash", "cash_received": 50000,
        }
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        assert len(r.json()["lines"][0]["notes"]) == 200


# ================== Merchant White-Label ==================

class TestWhiteLabel:
    def test_put_white_label_fields_persist(self, super_sess):
        # Use m-barista but with a temp slug (revert after)
        original = next(m for m in super_sess.get(f"{BASE_URL}/api/merchants").json() if m["id"] == "m-barista")
        temp_slug = f"barista-test-{uuid.uuid4().hex[:6]}"
        payload = {
            "name": original["name"],
            "slug": temp_slug,
            "logo_url": "https://cdn.example/logo.png",
            "theme_color": "#00A86B",
            "banner_url": "https://cdn.example/banner.png",
            "receipt_header": "Selamat Datang",
            "receipt_footer": "Terima Kasih",
            "wifi_password": "wifi1234",
            "subscription_status": "active",
            "features_enabled": {"pos": True, "kds": True, "self_order": False},
        }
        r = super_sess.put(f"{BASE_URL}/api/merchants/m-barista", json=payload)
        assert r.status_code == 200, r.text
        # GET verify
        merchants = super_sess.get(f"{BASE_URL}/api/merchants").json()
        m = next(x for x in merchants if x["id"] == "m-barista")
        assert m["slug"] == temp_slug
        assert m["logo_url"] == payload["logo_url"]
        assert m["theme_color"] == "#00A86B"
        assert m["banner_url"] == payload["banner_url"]
        assert m["receipt_header"] == "Selamat Datang"
        assert m["receipt_footer"] == "Terima Kasih"
        assert m["wifi_password"] == "wifi1234"
        assert m["features_enabled"].get("self_order") is False
        # restore slug (keep it functional though — tests below need slug lookup)
        # keep the temp_slug for the by-slug test
        pytest.merchant_temp_slug = temp_slug

    def test_branding_by_slug_ok(self, super_sess):
        slug = getattr(pytest, "merchant_temp_slug", None)
        assert slug, "run test_put_white_label_fields_persist first"
        # Public/unauth also should work (no auth dependency)
        r = requests.get(f"{BASE_URL}/api/branding/by-slug/{slug}", timeout=45)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["slug"] == slug
        assert body["theme_color"] == "#00A86B"

    def test_branding_by_slug_404(self):
        r = requests.get(f"{BASE_URL}/api/branding/by-slug/no-such-slug-{uuid.uuid4().hex[:6]}", timeout=45)
        assert r.status_code == 404

    def test_branding_current_super_admin(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/branding/current")
        assert r.status_code == 200
        body = r.json()
        # Super admin has no merchant → platform default
        assert body["name"] == "MJD Kupi"

    def test_branding_current_vendor(self, super_sess):
        vendor_sess = _login(*CREDS["vendor"])
        r = vendor_sess.get(f"{BASE_URL}/api/branding/current")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == "m-barista", body
        assert body["theme_color"] == "#00A86B"


# ================== Subscription Enforcement ==================

class TestSubscriptionEnforcement:
    EXPECTED_MSG = "Masa Langganan/Kerjasama Toko Telah Berakhir. Silakan Hubungi Platform Owner."

    def test_suspend_blocks_vendor_login(self, super_sess):
        # suspend
        r = super_sess.put(f"{BASE_URL}/api/merchants/m-barista", json={
            "name": "Barista Kopi", "subscription_status": "suspended",
        })
        assert r.status_code == 200, r.text
        # try vendor login
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": "vendor", "password": "MjdKupi#2026"}, timeout=45)
        assert r.status_code == 403, r.text
        detail = r.json().get("detail", "")
        assert detail == self.EXPECTED_MSG, f"detail mismatch: {detail!r}"

    def test_restore_active_allows_login(self, super_sess):
        r = super_sess.put(f"{BASE_URL}/api/merchants/m-barista", json={
            "name": "Barista Kopi", "subscription_status": "active",
        })
        assert r.status_code == 200
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": "vendor", "password": "MjdKupi#2026"}, timeout=45)
        assert r.status_code == 200, r.text
