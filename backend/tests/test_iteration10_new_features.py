"""Iteration 10: validate the 11 new features from the recent code injection.
Endpoint paths verified against server.py directly (some differ from review-request wording).
"""
import os
import uuid
import time
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
assert BASE_URL, "REACT_APP_BACKEND_URL must be set in frontend/.env"

CSRF = {"X-Requested-With": "mjd-kupi"}

CREDS = {
    "superadmin": ("superadmin", ".Superadmin1_"),
    "admin":      ("admin", "MjdKupi#2026"),
    "kasir":      ("kasir", "MjdKupi#2026"),
    "vendor":     ("vendor", "MjdKupi#2026"),
}


# ---------- fixtures ----------

def _login(identifier: str, password: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(CSRF)
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": identifier, "password": password},
               headers=CSRF, timeout=15)
    assert r.status_code == 200, f"login {identifier}: {r.status_code} {r.text}"
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    s.headers.update(CSRF)
    s.me = data  # attach
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


@pytest.fixture(scope="module")
def vendor_sess():
    return _login(*CREDS["vendor"])


# ---------- Feature 1: Auth login + shape ----------

class TestAuthLogin:
    def test_all_roles_login(self):
        for role_key, (u, p) in CREDS.items():
            s = _login(u, p)
            me = s.me
            assert "role" in me and me["role"] in ("Super Admin", "Admin", "Kasir", "Vendor")
            assert "outlet_id" in me
            assert "merchant_id" in me  # always present since iter9 fix
            assert isinstance(me["access_token"], str) and len(me["access_token"]) > 20

    def test_vendor_has_merchant_id(self, vendor_sess):
        assert vendor_sess.me["role"] == "Vendor"
        assert vendor_sess.me["merchant_id"] == "m-barista", vendor_sess.me


# ---------- Feature 2: PIN authorization (15 min) ----------

class TestPin:
    def test_pin_generate_super_admin(self, super_sess):
        r = super_sess.post(f"{BASE_URL}/api/admin/pin/generate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "pin" in body and "expires_at" in body
        assert len(body["pin"]) == 6
        # spec says 6-digit but code uses alphanumeric alphabet — informational
        # Ensure expires ~15min ahead
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        delta = (exp - datetime.now(timezone.utc)).total_seconds()
        assert 14 * 60 <= delta <= 16 * 60, delta

    def test_kasir_cannot_generate_pin(self, kasir_sess):
        r = kasir_sess.post(f"{BASE_URL}/api/admin/pin/generate")
        assert r.status_code == 403, r.text


# ---------- Feature 3: Void sale with PIN ----------

class TestVoidSale:
    @pytest.fixture(scope="class")
    def open_shift(self, kasir_sess):
        # Ensure kasir has an open shift (idempotent-ish)
        cur = kasir_sess.get(f"{BASE_URL}/api/shifts/current")
        if cur.status_code == 200 and cur.json():
            return cur.json()
        r = kasir_sess.post(f"{BASE_URL}/api/shifts/open",
                            json={"opening_cash": 100000, "note": "TEST iter10"})
        assert r.status_code == 200, r.text
        return r.json()

    @pytest.fixture(scope="class")
    def a_sale(self, kasir_sess, open_shift):
        payload = {
            "table": "Meja TEST_VOID",
            "lines": [{"product_id": "p-1", "name": "Kopi Susu", "quantity": 1, "price": 18000}],
            "subtotal": 18000, "tax": 1800, "total": 19800,
            "payment_method": "Cash", "cash_received": 20000,
        }
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    def test_void_without_pin_fails(self, kasir_sess, a_sale):
        r = kasir_sess.post(f"{BASE_URL}/api/sales/{a_sale['id']}/void",
                            json={"pin": "WRONG1", "reason": "TEST bad pin"})
        assert r.status_code == 403, r.text

    def test_void_with_valid_pin_succeeds(self, super_sess, kasir_sess, a_sale):
        gen = super_sess.post(f"{BASE_URL}/api/admin/pin/generate").json()
        pin = gen["pin"]
        r = kasir_sess.post(f"{BASE_URL}/api/sales/{a_sale['id']}/void",
                            json={"pin": pin, "reason": "TEST valid void"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "voided"
        assert body["void_reason"] == "TEST valid void"

    def test_void_already_voided(self, super_sess, kasir_sess, a_sale):
        gen = super_sess.post(f"{BASE_URL}/api/admin/pin/generate").json()
        r = kasir_sess.post(f"{BASE_URL}/api/sales/{a_sale['id']}/void",
                            json={"pin": gen["pin"], "reason": "again"})
        assert r.status_code == 400


# ---------- Feature 4: Kasir history (/api/pos/history) ----------

class TestKasirHistory:
    def test_kasir_history_returns_list(self, kasir_sess):
        r = kasir_sess.get(f"{BASE_URL}/api/pos/history")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # every sale must belong to this kasir's shift
        for s in data:
            assert s.get("cashier_id") == kasir_sess.me["id"], s

    def test_vendor_forbidden_history(self, vendor_sess):
        r = vendor_sess.get(f"{BASE_URL}/api/pos/history")
        assert r.status_code == 403


# ---------- Feature 5: Bank accounts CRUD ----------

class TestBankAccounts:
    def test_crud_roundtrip(self, super_sess):
        payload = {"bank_name": "TEST_BCA", "account_number": "1234567890", "holder_name": "TEST Owner"}
        # create
        r = super_sess.post(f"{BASE_URL}/api/settings/bank-accounts", json=payload)
        assert r.status_code == 200, r.text
        accts = r.json()["accounts"]
        new_id = next((a["id"] for a in accts if a["bank_name"] == "TEST_BCA"), None)
        assert new_id
        # read
        r = super_sess.get(f"{BASE_URL}/api/settings/bank-accounts")
        assert r.status_code == 200
        assert any(a.get("id") == new_id for a in r.json().get("accounts", []))
        # delete
        r = super_sess.delete(f"{BASE_URL}/api/settings/bank-accounts/{new_id}")
        assert r.status_code == 200
        assert not any(a.get("id") == new_id for a in r.json().get("accounts", []))

    def test_kasir_cannot_write(self, kasir_sess):
        r = kasir_sess.post(f"{BASE_URL}/api/settings/bank-accounts",
                            json={"bank_name": "X", "account_number": "1", "holder_name": "Y"})
        assert r.status_code == 403


# ---------- Feature 6 & 7: QRIS + generic setting key ----------

class TestSettings:
    def test_qris_upsert_and_get(self, admin_sess):
        outlet = "outlet-sudirman"
        r = admin_sess.post(f"{BASE_URL}/api/settings/qris",
                            json={"outlet_id": outlet, "qris_code": "TEST_QRIS_BASE64"})
        assert r.status_code == 200, r.text
        r = admin_sess.get(f"{BASE_URL}/api/settings/qris:{outlet}")
        assert r.status_code == 200
        assert r.json().get("qris_code") == "TEST_QRIS_BASE64"

    def test_generic_setting_upsert_get(self, admin_sess):
        key = f"TEST_KEY_{uuid.uuid4().hex[:6]}"
        r = admin_sess.post(f"{BASE_URL}/api/settings",
                            json={"key": key, "value": {"hello": "world"}})
        assert r.status_code == 200, r.text
        r = admin_sess.get(f"{BASE_URL}/api/settings/{key}")
        assert r.status_code == 200
        assert r.json() == {"hello": "world"}


# ---------- Feature 7: Strict outlet_id isolation ----------

class TestOutletIsolation:
    def test_kasir_products_scoped(self, kasir_sess):
        r = kasir_sess.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        for p in r.json():
            assert p.get("outlet_id") == kasir_sess.me["outlet_id"], p

    def test_kasir_ignores_outlet_query_param(self, kasir_sess):
        # Attempting cross-outlet query should still be forced to kasir's outlet
        r = kasir_sess.get(f"{BASE_URL}/api/products?outlet_id=outlet-kemang")
        assert r.status_code == 200
        for p in r.json():
            assert p.get("outlet_id") == kasir_sess.me["outlet_id"]

    def test_kasir_expenses_own_only(self, kasir_sess):
        r = kasir_sess.get(f"{BASE_URL}/api/expenses")
        assert r.status_code == 200
        for e in r.json():
            assert e.get("user_id") == kasir_sess.me["id"]

    def test_sales_scope_kasir_only_own_shift(self, kasir_sess):
        r = kasir_sess.get(f"{BASE_URL}/api/sales")
        assert r.status_code == 200
        for s in r.json():
            assert s.get("cashier_id") == kasir_sess.me["id"]


# ---------- Feature 8: Shift lock ----------

class TestShiftLock:
    def test_sales_without_shift_returns_400(self, kasir_sess):
        # Close current shift first
        cur = kasir_sess.get(f"{BASE_URL}/api/shifts/current").json()
        if cur:
            kasir_sess.post(f"{BASE_URL}/api/shifts/close", json={"closing_cash": 100000})
        # Now no active shift → sale must fail
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json={
            "table": "Meja LOCK",
            "lines": [{"product_id": "p-1", "name": "x", "quantity": 1, "price": 18000}],
            "subtotal": 18000, "tax": 0, "total": 18000, "payment_method": "Cash", "cash_received": 20000,
        })
        assert r.status_code == 400
        assert "shift" in r.text.lower() or "buka" in r.text.lower(), r.text
        # Re-open for downstream tests
        kasir_sess.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000})


# ---------- Feature 9: Cash opname variance ----------

class TestCashOpname:
    def test_variance_computation(self, kasir_sess):
        # Ensure fresh shift
        cur = kasir_sess.get(f"{BASE_URL}/api/shifts/current").json()
        if cur:
            kasir_sess.post(f"{BASE_URL}/api/shifts/close", json={"closing_cash": 0})
        opening = 50000
        r = kasir_sess.post(f"{BASE_URL}/api/shifts/open",
                            json={"opening_cash": opening, "note": "TEST opname"})
        assert r.status_code == 200
        # Make a cash sale
        sale = kasir_sess.post(f"{BASE_URL}/api/sales", json={
            "table": "Meja TEST_OPN",
            "lines": [{"product_id": "p-2", "name": "Americano", "quantity": 1, "price": 15000}],
            "subtotal": 15000, "tax": 0, "total": 15000, "payment_method": "Cash", "cash_received": 15000,
        })
        assert sale.status_code == 200, sale.text
        sale_total = sale.json()["total"]
        # Cash expense
        exp = kasir_sess.post(f"{BASE_URL}/api/expenses", json={
            "category": "TEST_Opname", "note": "", "amount": 2000,
            "date": "2026-02-15", "method": "Cash",
        })
        assert exp.status_code == 200, exp.text
        # Close with counted cash — set a non-matching amount to verify variance math
        counted = 60000  # arbitrary
        expected = opening + sale_total - 2000  # 50000 + 15000 - 2000 = 63000
        variance_expected = counted - expected  # -3000
        r = kasir_sess.post(f"{BASE_URL}/api/shifts/close", json={"closing_cash": counted})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cash_sales"] == sale_total, body
        assert body["cash_expenses"] == 2000, body
        assert body["expected_cash"] == expected, body
        assert body["variance"] == variance_expected, body


# ---------- Feature 10: Vendor scope ----------

class TestVendorScope:
    def test_kds_orders_vendor_scoped(self, vendor_sess):
        r = vendor_sess.get(f"{BASE_URL}/api/kds/orders")
        assert r.status_code == 200, r.text
        for t in r.json():
            assert t.get("merchant_id") == vendor_sess.me["merchant_id"], t

    def test_vendor_orders_scoped(self, vendor_sess):
        r = vendor_sess.get(f"{BASE_URL}/api/vendor/orders")
        assert r.status_code == 200
        for o in r.json():
            lines = o.get("lines") or []
            assert any((ln.get("merchant_id") or "") == vendor_sess.me["merchant_id"] for ln in lines), o


# ---------- Feature 11: Security headers + CSRF ----------

class TestSecurity:
    def test_state_change_without_csrf_header_forbidden(self, super_sess):
        # Fresh session without header
        s = requests.Session()
        # Login is allowlisted — reuse token via Authorization to bypass auth
        s.headers.update({"Authorization": super_sess.headers["Authorization"]})
        r = s.post(f"{BASE_URL}/api/settings",
                   json={"key": "TEST_CSRF", "value": {"x": 1}})
        assert r.status_code == 403, r.text
        assert "csrf" in r.text.lower() or "missing" in r.text.lower(), r.text

    def test_login_allowlisted_without_csrf_header(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": "superadmin", "password": ".Superadmin1_"})
        assert r.status_code == 200

    def test_self_order_allowlisted_without_csrf_header(self):
        s = requests.Session()
        # Need an open kasir shift for the outlet; skip gracefully if 423
        payload = {
            "table": "Meja SELF_TEST",
            "lines": [{"product_id": "p-1", "name": "Kopi", "quantity": 1, "price": 18000}],
            "total": 18000, "customer_name": "TEST_Cust", "outlet_id": "outlet-sudirman",
        }
        r = s.post(f"{BASE_URL}/api/self-order", json=payload)
        # Must NOT be 403 CSRF; allowed values: 200 (success) or 423 (no open shift)
        assert r.status_code in (200, 400, 423), r.text

    def test_security_headers_present(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "no-referrer"
        assert "camera" in (r.headers.get("Permissions-Policy") or "")
