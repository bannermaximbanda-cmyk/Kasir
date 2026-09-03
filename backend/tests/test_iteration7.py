"""Iteration 7 backend tests: username login, RBAC on /admin/users, /outlets CRUD,
expense auto-binding, role migration ('Merchant Admin' -> 'Admin')."""
import os
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

# username, password, expected role
CREDS = {
    "super":  ("superadmin", ".Superadmin1_", "Super Admin"),
    "admin":  ("admin",      "MjdKupi#2026", "Admin"),
    "vendor": ("vendor",     "MjdKupi#2026", "Vendor"),
    "kasir":  ("kasir",      "MjdKupi#2026", "Kasir"),
}


def _login(session: requests.Session, key: str) -> dict:
    ident, password, _ = CREDS[key]
    r = session.post(f"{API}/auth/login", json={"email": ident, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {key} failed: {r.status_code} {r.text}"
    data = r.json()
    session.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    return data


@pytest.fixture
def super_client():
    s = requests.Session(); _login(s, "super"); return s

@pytest.fixture
def admin_client():
    s = requests.Session(); _login(s, "admin"); return s

@pytest.fixture
def vendor_client():
    s = requests.Session(); _login(s, "vendor"); return s

@pytest.fixture
def kasir_client():
    s = requests.Session(); _login(s, "kasir"); return s


# --------------------------------------------------------------------
# Auth: username + email dual login, role migration
# --------------------------------------------------------------------
class TestUsernameLogin:
    @pytest.mark.parametrize("key", list(CREDS.keys()))
    def test_login_via_username(self, key):
        s = requests.Session()
        data = _login(s, key)
        assert data["role"] == CREDS[key][2], f"role mismatch for {key}: {data['role']}"

    def test_login_via_email_still_works(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": "superadmin@mjd-kupi.local", "password": ".Superadmin1_"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "Super Admin"

    def test_admin_email_login_role_is_admin_not_merchant_admin(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": "manager@mjd-kupi.local", "password": "MjdKupi#2026"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "Admin"

    def test_login_bad_password(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": "superadmin", "password": "wrong"}, timeout=30)
        assert r.status_code == 401


# --------------------------------------------------------------------
# /admin/users RBAC + CRUD
# --------------------------------------------------------------------
class TestAdminUsers:
    def test_list_users_super_ok_has_plain_password(self, super_client):
        r = super_client.get(f"{API}/admin/users", timeout=30)
        assert r.status_code == 200, r.text
        users = r.json()
        assert isinstance(users, list) and len(users) >= 4
        for u in users:
            assert "plain_password" in u
            assert "username" in u
        # at least demo users have plain_password populated
        demo = [u for u in users if u.get("username") in {"superadmin", "admin", "kasir", "vendor"}]
        assert demo and all(u["plain_password"] for u in demo)

    @pytest.mark.parametrize("role_key", ["admin", "kasir", "vendor"])
    def test_list_users_non_super_403(self, role_key):
        s = requests.Session(); _login(s, role_key)
        r = s.get(f"{API}/admin/users", timeout=30)
        assert r.status_code == 403

    def test_create_user_and_login(self, super_client):
        suffix = uuid.uuid4().hex[:6]
        payload = {
            "email": f"TEST_{suffix}@mjd-kupi.local",
            "username": f"TEST_{suffix}",
            "password": "TestPass#2026",
            "role": "Kasir",
            "name": f"TEST User {suffix}",
        }
        r = super_client.post(f"{API}/admin/users", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        created = r.json()
        uid = created["id"]
        # verify appears in listing with plain_password
        lst = super_client.get(f"{API}/admin/users", timeout=30).json()
        found = next((u for u in lst if u["id"] == uid), None)
        assert found and found["plain_password"] == "TestPass#2026"
        # login new user via username
        r2 = requests.post(f"{API}/auth/login",
                           json={"email": payload["username"], "password": "TestPass#2026"}, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["role"] == "Kasir"
        # cleanup
        super_client.delete(f"{API}/admin/users/{uid}", timeout=30)

    def test_create_user_invalid_role_400(self, super_client):
        payload = {
            "email": f"TEST_bad_{uuid.uuid4().hex[:6]}@x.com",
            "username": f"TEST_bad_{uuid.uuid4().hex[:6]}",
            "password": "x", "role": "Hacker", "name": "x",
        }
        r = super_client.post(f"{API}/admin/users", json=payload, timeout=30)
        assert r.status_code == 400

    def test_reset_password_flow(self, super_client):
        suffix = uuid.uuid4().hex[:6]
        create = super_client.post(f"{API}/admin/users", json={
            "email": f"TEST_rp_{suffix}@x.com", "username": f"TEST_rp_{suffix}",
            "password": "OldPass#1", "role": "Kasir", "name": "rp"}, timeout=30).json()
        uid = create["id"]
        r = super_client.post(f"{API}/admin/users/{uid}/reset-password",
                              json={"new_password": "NewPass#2"}, timeout=30)
        assert r.status_code == 200, r.text
        # verify old fails, new works
        old = requests.post(f"{API}/auth/login",
                            json={"email": f"TEST_rp_{suffix}", "password": "OldPass#1"}, timeout=30)
        assert old.status_code == 401
        new = requests.post(f"{API}/auth/login",
                            json={"email": f"TEST_rp_{suffix}", "password": "NewPass#2"}, timeout=30)
        assert new.status_code == 200
        # plain_password updated
        lst = super_client.get(f"{API}/admin/users", timeout=30).json()
        found = next(u for u in lst if u["id"] == uid)
        assert found["plain_password"] == "NewPass#2"
        super_client.delete(f"{API}/admin/users/{uid}", timeout=30)

    def test_toggle_and_delete(self, super_client):
        suffix = uuid.uuid4().hex[:6]
        create = super_client.post(f"{API}/admin/users", json={
            "email": f"TEST_td_{suffix}@x.com", "username": f"TEST_td_{suffix}",
            "password": "p", "role": "Kasir", "name": "td"}, timeout=30).json()
        uid = create["id"]
        r = super_client.patch(f"{API}/admin/users/{uid}/toggle", timeout=30)
        assert r.status_code == 200
        # active flipped
        after = r.json()
        assert "active" in after
        # delete
        d = super_client.delete(f"{API}/admin/users/{uid}", timeout=30)
        assert d.status_code == 200
        # confirm gone
        lst = super_client.get(f"{API}/admin/users", timeout=30).json()
        assert not any(u["id"] == uid for u in lst)

    def test_cannot_delete_self(self, super_client):
        me = super_client.get(f"{API}/auth/me", timeout=30).json()
        r = super_client.delete(f"{API}/admin/users/{me['id']}", timeout=30)
        assert r.status_code == 400


# --------------------------------------------------------------------
# /outlets CRUD RBAC
# --------------------------------------------------------------------
class TestOutlets:
    def test_super_can_create_update_delete_outlet(self, super_client):
        payload = {"id": f"TEST_out_{uuid.uuid4().hex[:6]}",
                   "name": "TEST Outlet", "address": "Jl. Test", "phone": "081"}
        r = super_client.post(f"{API}/outlets", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        u = super_client.put(f"{API}/outlets/{oid}",
                             json={"name": "TEST Updated", "address": "New", "phone": "082"}, timeout=30)
        assert u.status_code == 200, u.text
        assert u.json()["name"] == "TEST Updated"
        d = super_client.delete(f"{API}/outlets/{oid}", timeout=30)
        assert d.status_code == 200

    @pytest.mark.parametrize("role_key", ["admin", "kasir"])
    def test_non_super_cannot_modify_outlet(self, role_key):
        s = requests.Session(); _login(s, role_key)
        r = s.put(f"{API}/outlets/outlet-sudirman",
                  json={"name": "x", "address": "y", "phone": "z"}, timeout=30)
        assert r.status_code == 403
        r2 = s.delete(f"{API}/outlets/outlet-sudirman", timeout=30)
        assert r2.status_code == 403


# --------------------------------------------------------------------
# Logo settings
# --------------------------------------------------------------------
class TestLogoSetting:
    def test_logo_roundtrip(self, super_client):
        payload = {"logo_data": "data:image/png;base64,AAA"}
        r = super_client.post(f"{API}/settings",
                              json={"key": "logo", "value": payload}, timeout=30)
        assert r.status_code == 200
        g = requests.get(f"{API}/settings/logo", timeout=30)
        assert g.status_code == 200
        assert g.json() == payload


# --------------------------------------------------------------------
# Expense auto-binding
# --------------------------------------------------------------------
class TestExpenseAutoBind:
    def _ensure_shift(self, client):
        cur = client.get(f"{API}/shifts/current", timeout=30).json()
        if not cur:
            r = client.post(f"{API}/shifts/open", json={"opening_cash": 0}, timeout=30)
            assert r.status_code == 200, r.text
            return r.json()
        return cur

    def test_kasir_expense_binds_user_and_shift(self, kasir_client):
        shift = self._ensure_shift(kasir_client)
        me = kasir_client.get(f"{API}/auth/me", timeout=30).json()
        payload = {
            "category": "TEST_bind",
            "note": "TEST autobind",
            "amount": 5000,
            "date": "2026-01-15",
            "method": "Cash",
            # attempt to forge
            "user_id": "hacker-id",
            "user_name": "Hacker",
            "shift_id": "hacker-shift",
        }
        r = kasir_client.post(f"{API}/expenses", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        exp = r.json()
        assert exp["user_id"] == me["id"], f"user_id not auto-bound: {exp['user_id']}"
        assert exp["user_name"] == me["name"]
        assert exp["shift_id"] == shift["id"]
        # cleanup
        kasir_client.post(f"{API}/shifts/close", json={"closing_cash": 0}, timeout=30)

    def test_kasir_expense_specifically_dina(self, kasir_client):
        me = kasir_client.get(f"{API}/auth/me", timeout=30).json()
        # per spec, seeded Kasir name is 'Dina Kasir'
        assert me["name"] == "Dina Kasir", f"seeded kasir name changed: {me['name']}"
