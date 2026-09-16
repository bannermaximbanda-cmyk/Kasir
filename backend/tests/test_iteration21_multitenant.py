"""Iteration 21 — Multi-outlet isolation & cascading validation.
Covers login cascade, outlet soft-delete + user auto-deactivation,
user create outlet enforcement, product global-outlet flag, shift open
outlet validation, and regressions (sales, dashboard, settlement).
"""
import os
import uuid
import time
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://kupi-kasir-pro.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
CSRF = {"X-Requested-With": "mjd-kupi"}

SUPER = {"email": "superadmin", "password": ".Superadmin1_"}
ADMIN = {"email": "admin", "password": "MjdKupi#2026"}
KASIR = {"email": "kasir", "password": "MjdKupi#2026"}

BANDA_ID = "outlet-banda-aceh"
SUDIRMAN_ID = "outlet-sudirman"


def _login(creds):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=creds, headers=CSRF)
    return s, r


@pytest.fixture(scope="module")
def sa():
    s, r = _login(SUPER)
    assert r.status_code == 200, f"SA login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module", autouse=True)
def ensure_banda(sa):
    """Ensure outlet-banda-aceh and outlet-sudirman exist and are active,
    and re-activate the seed admin/kasir accounts (in case a previous test
    run soft-deleted their outlet and cascaded them inactive)."""
    r = sa.get(f"{API}/outlets", params={"include_inactive": 1})
    assert r.status_code == 200
    outlets = {o["id"]: o for o in r.json()}
    for oid, name in ((BANDA_ID, "MJD Banda Aceh"), (SUDIRMAN_ID, "MJD Sudirman")):
        if oid not in outlets:
            r = sa.post(f"{API}/outlets", json={"id": oid, "name": name, "address": "", "active": True}, headers=CSRF)
            assert r.status_code == 200, r.text
        elif outlets[oid]["active"] is False:
            r = sa.put(f"{API}/outlets/{oid}",
                       json={"id": oid, "name": outlets[oid]["name"], "active": True}, headers=CSRF)
            assert r.status_code == 200, r.text
    # Re-activate seed admin & kasir if a previous cascade turned them off
    r = sa.get(f"{API}/admin/users")
    if r.status_code == 200:
        for u in r.json():
            if u["username"] in ("admin", "kasir") and u.get("active") is False:
                sa.patch(f"{API}/admin/users/{u['id']}/toggle", headers=CSRF)
    return BANDA_ID


# --------------------------------------------------------------------------
# (A) Create-user outlet enforcement
# --------------------------------------------------------------------------

class TestCreateUserOutletEnforcement:

    def _mk_payload(self, outlet_id, tag="ok"):
        uniq = uuid.uuid4().hex[:8]
        return {
            "email": f"TEST_kasir_{tag}_{uniq}@mjd-kupi.local",
            "username": f"TEST_kasir_{tag}_{uniq}",
            "password": "TestPass123!",
            "role": "Kasir",
            "name": f"TEST Kasir {tag}",
            "outlet_id": outlet_id,
            "active": True,
        }

    def test_create_kasir_banda_saves_correct_outlet(self, sa, ensure_banda):
        payload = self._mk_payload(BANDA_ID, "banda")
        r = sa.post(f"{API}/admin/users", json=payload, headers=CSRF)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["outlet_id"] == BANDA_ID, f"Expected {BANDA_ID}, got {data['outlet_id']}"
        assert data["outlet_id"] != SUDIRMAN_ID
        # Verify via GET list
        r2 = sa.get(f"{API}/admin/users")
        assert r2.status_code == 200
        u = next((u for u in r2.json() if u["id"] == data["id"]), None)
        assert u and u["outlet_id"] == BANDA_ID

    def test_create_kasir_missing_outlet_400(self, sa):
        payload = self._mk_payload(None, "missing")
        payload["outlet_id"] = None
        r = sa.post(f"{API}/admin/users", json=payload, headers=CSRF)
        assert r.status_code == 400, r.text
        assert "wajib" in r.json().get("detail", "").lower()

    def test_create_kasir_nonexistent_outlet_400(self, sa):
        payload = self._mk_payload("does-not-exist-xyz", "nx")
        r = sa.post(f"{API}/admin/users", json=payload, headers=CSRF)
        assert r.status_code == 400, r.text
        assert "tidak ditemukan" in r.json().get("detail", "").lower()

    def test_create_kasir_deactivated_outlet_400(self, sa):
        # Create a fresh outlet, deactivate it, then attempt user-create
        oid = f"test-outlet-inactive-{uuid.uuid4().hex[:6]}"
        r = sa.post(f"{API}/outlets", json={"id": oid, "name": f"TEST Inactive {oid}", "active": True}, headers=CSRF)
        assert r.status_code == 200, r.text
        r = sa.delete(f"{API}/outlets/{oid}", headers=CSRF)
        assert r.status_code == 200, r.text
        assert r.json().get("mode") == "deactivated"
        payload = self._mk_payload(oid, "inactive")
        r = sa.post(f"{API}/admin/users", json=payload, headers=CSRF)
        assert r.status_code == 400, r.text
        assert "dinonaktifkan" in r.json().get("detail", "").lower()


# --------------------------------------------------------------------------
# (B) Outlet soft-delete cascades user deactivation + login cascade
# --------------------------------------------------------------------------

class TestOutletSoftDeleteAndLoginCascade:

    def test_soft_delete_cascade_and_login_blocked_and_reactivate(self, sa):
        # Create fresh outlet + kasir bound to it
        oid = f"test-outlet-cascade-{uuid.uuid4().hex[:6]}"
        r = sa.post(f"{API}/outlets", json={"id": oid, "name": f"TEST Cascade {oid}", "active": True}, headers=CSRF)
        assert r.status_code == 200
        uniq = uuid.uuid4().hex[:6]
        upayload = {
            "email": f"TEST_cascade_{uniq}@mjd-kupi.local",
            "username": f"TEST_cascade_{uniq}",
            "password": "CascadePass1!",
            "role": "Kasir",
            "name": "TEST Cascade User",
            "outlet_id": oid,
            "active": True,
        }
        r = sa.post(f"{API}/admin/users", json=upayload, headers=CSRF)
        assert r.status_code == 200, r.text
        user_id = r.json()["id"]

        # Sanity: user can login now
        s2, r2 = _login({"email": upayload["username"], "password": upayload["password"]})
        assert r2.status_code == 200, f"Pre-cascade login should succeed: {r2.text}"

        # Soft-delete outlet
        r = sa.delete(f"{API}/outlets/{oid}", headers=CSRF)
        assert r.status_code == 200
        j = r.json()
        assert j["mode"] == "deactivated"
        assert j["affected_users"] >= 1, f"Expected >=1 affected users, got {j['affected_users']}"

        # Verify outlet.active is False in list (with include_inactive)
        r = sa.get(f"{API}/outlets", params={"include_inactive": 1})
        outlets = {o["id"]: o for o in r.json()}
        assert outlets[oid]["active"] is False

        # Verify user is now inactive
        r = sa.get(f"{API}/admin/users")
        u = next((u for u in r.json() if u["id"] == user_id), None)
        assert u is not None and u["active"] is False, "User should be auto-deactivated"

        # Login should now be blocked: either 403 (outlet cascade) OR 403 (account inactive)
        _, rlog = _login({"email": upayload["username"], "password": upayload["password"]})
        assert rlog.status_code == 403, f"Expected 403, got {rlog.status_code} {rlog.text}"
        detail = rlog.json().get("detail", "").lower()
        assert ("dinonaktifkan" in detail) or ("dihapus" in detail), detail

        # Reactivate outlet (active=True) — user should STILL be blocked (user.active still false)
        r = sa.put(f"{API}/outlets/{oid}",
                   json={"id": oid, "name": f"TEST Cascade {oid}", "active": True}, headers=CSRF)
        assert r.status_code == 200
        _, rlog2 = _login({"email": upayload["username"], "password": upayload["password"]})
        assert rlog2.status_code == 403, "User still inactive → login must fail"

        # Toggle user active back → login should succeed
        r = sa.patch(f"{API}/admin/users/{user_id}/toggle", headers=CSRF)
        assert r.status_code == 200, r.text
        assert r.json().get("active") is True
        _, rlog3 = _login({"email": upayload["username"], "password": upayload["password"]})
        assert rlog3.status_code == 200, f"Expected 200 after reactivation, got {rlog3.status_code} {rlog3.text}"

    def test_super_admin_login_immune_to_outlet_state(self, sa):
        # Just verify Super Admin login works (SA in seed has no outlet or exempt)
        _, r = _login(SUPER)
        assert r.status_code == 200


# --------------------------------------------------------------------------
# (C) Shift open validation
# --------------------------------------------------------------------------

class TestShiftOpenOutletValidation:

    def test_shift_open_with_deactivated_outlet_400(self, sa):
        # Create outlet + kasir + soft-delete outlet, then re-activate outlet ONLY
        # (leaving user inactive). Toggle user active back on. Then deactivate outlet again.
        oid = f"test-shift-deact-{uuid.uuid4().hex[:6]}"
        sa.post(f"{API}/outlets", json={"id": oid, "name": f"TEST Shift {oid}", "active": True}, headers=CSRF)
        uniq = uuid.uuid4().hex[:6]
        pw = "ShiftPass1!"
        creds_email = f"TEST_shift_{uniq}"
        r = sa.post(f"{API}/admin/users", json={
            "email": f"TEST_shift_{uniq}@mjd-kupi.local",
            "username": creds_email,
            "password": pw, "role": "Kasir",
            "name": "TEST Shift User", "outlet_id": oid, "active": True,
        }, headers=CSRF)
        assert r.status_code == 200, r.text
        user_id = r.json()["id"]

        # Login BEFORE deactivating outlet
        s2, r2 = _login({"email": creds_email, "password": pw})
        assert r2.status_code == 200

        # Now super admin deactivates outlet (also flips user active=false)
        sa.delete(f"{API}/outlets/{oid}", headers=CSRF)

        # Toggle user active=true again but leave outlet inactive
        r = sa.patch(f"{API}/admin/users/{user_id}/toggle", headers=CSRF)
        assert r.json().get("active") is True

        # Kasir needs fresh login token — but login will be blocked by outlet cascade.
        # Instead, use existing session s2 which still has valid cookie.
        r3 = s2.post(f"{API}/shifts/open", json={"opening_cash": 100000, "note": "test"}, headers=CSRF)
        assert r3.status_code == 400, f"Expected 400, got {r3.status_code} {r3.text}"
        assert "dinonaktifkan" in r3.json().get("detail", "").lower()

    def test_shift_open_normal_path(self, sa, ensure_banda):
        # Create kasir in outlet-banda-aceh
        uniq = uuid.uuid4().hex[:6]
        creds_user = f"TEST_shift_ok_{uniq}"
        pw = "NormalPass1!"
        r = sa.post(f"{API}/admin/users", json={
            "email": f"TEST_shift_ok_{uniq}@mjd-kupi.local",
            "username": creds_user, "password": pw,
            "role": "Kasir", "name": "TEST Shift OK", "outlet_id": BANDA_ID, "active": True,
        }, headers=CSRF)
        assert r.status_code == 200
        s2, r2 = _login({"email": creds_user, "password": pw})
        assert r2.status_code == 200
        me = r2.json()
        assert me["outlet_id"] == BANDA_ID
        # Close any existing open shift (defensive) — ignore errors
        s2.post(f"{API}/shifts/close", json={"closing_cash": 100000, "note": ""}, headers=CSRF)
        r3 = s2.post(f"{API}/shifts/open", json={"opening_cash": 150000, "note": "banda test"}, headers=CSRF)
        assert r3.status_code == 200, r3.text
        shift = r3.json()
        assert shift["outlet_id"] == BANDA_ID, f"Shift outlet mismatch: {shift['outlet_id']} != {BANDA_ID}"
        # Close it to keep state clean
        s2.post(f"{API}/shifts/close", json={"closing_cash": 150000, "note": ""}, headers=CSRF)


# --------------------------------------------------------------------------
# (D) Outlets list scoping
# --------------------------------------------------------------------------

class TestOutletListScope:

    def test_get_outlets_default_only_active(self, sa):
        r = sa.get(f"{API}/outlets")
        assert r.status_code == 200
        for o in r.json():
            assert o["active"] is True, f"Default list contains inactive: {o}"

    def test_get_outlets_include_inactive_super_admin(self, sa):
        r_all = sa.get(f"{API}/outlets", params={"include_inactive": 1})
        r_active = sa.get(f"{API}/outlets")
        assert r_all.status_code == 200 and r_active.status_code == 200
        assert len(r_all.json()) >= len(r_active.json())
        # If any inactive outlet exists, include_inactive should be strictly larger
        inactive_present = any(o["active"] is False for o in r_all.json())
        if inactive_present:
            assert len(r_all.json()) > len(r_active.json())

    def test_get_outlets_include_inactive_ignored_for_non_super(self):
        s, r = _login(ADMIN)
        assert r.status_code == 200
        r2 = s.get(f"{API}/outlets", params={"include_inactive": 1})
        assert r2.status_code == 200
        for o in r2.json():
            assert o["active"] is True, f"Non-SA got inactive outlet: {o}"


# --------------------------------------------------------------------------
# (E) Products: global (outlet_id=NULL) visibility
# --------------------------------------------------------------------------

class TestGlobalProduct:

    _global_pid = None

    def test_super_admin_creates_global_product(self, sa, ensure_banda):
        uniq = uuid.uuid4().hex[:6]
        payload = {
            "name": f"TEST_GLOBAL_{uniq}",
            "category": "Test",
            "price": 9000, "cost": 3000, "stock": 100,
            "sku": f"TESTG{uniq}",
            "outlet_id": None,
            "is_active": True,
        }
        r = sa.post(f"{API}/products", json=payload, headers=CSRF)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["outlet_id"] in (None, ""), f"Expected NULL/empty outlet_id for global, got {p['outlet_id']}"
        TestGlobalProduct._global_pid = p["id"]

    def test_super_admin_creates_global_via_empty_string(self, sa):
        uniq = uuid.uuid4().hex[:6]
        r = sa.post(f"{API}/products", json={
            "name": f"TEST_GLOBAL2_{uniq}", "price": 5000, "stock": 10, "outlet_id": "",
            "sku": f"TESTG2{uniq}", "is_active": True,
        }, headers=CSRF)
        assert r.status_code == 200, r.text
        assert r.json()["outlet_id"] in (None, "")

    def test_admin_cannot_create_global_product(self):
        s, r = _login(ADMIN)
        assert r.status_code == 200
        uniq = uuid.uuid4().hex[:6]
        r2 = s.post(f"{API}/products", json={
            "name": f"TEST_ADMIN_GLOBAL_{uniq}", "price": 1000, "stock": 1,
            "outlet_id": None, "sku": f"TESTA{uniq}", "is_active": True,
        }, headers=CSRF)
        # Admin passes outlet_id=None → code path forces to user.outlet_id (fallback);
        # per spec: "Admin cannot create global products" ⇒ should be 400.
        # If it silently succeeds by falling back to admin's outlet, that's a spec deviation.
        assert r2.status_code == 400, (
            f"Admin global-product create should be blocked, got {r2.status_code} {r2.text}"
        )

    def test_global_product_visible_in_outlet_a_list(self, sa, ensure_banda):
        # As Super Admin passing outlet_id=BANDA — outlet_scope for SA returns None unless explicit
        # Test via ANONYMOUS which forces outlet_id filter (the real "customer view")
        r = requests.get(f"{API}/products", params={"outlet_id": BANDA_ID})
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert TestGlobalProduct._global_pid in ids, "Global product NOT visible in outlet A list"

    def test_global_product_visible_in_outlet_b_list(self, sa):
        r = requests.get(f"{API}/products", params={"outlet_id": SUDIRMAN_ID})
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert TestGlobalProduct._global_pid in ids, "Global product NOT visible in outlet B list"


# --------------------------------------------------------------------------
# (F) Regression: sales + StockMovement, dashboard analytics, settlement/payouts
# --------------------------------------------------------------------------

class TestRegression:

    def test_dashboard_analytics(self, sa):
        r = sa.get(f"{API}/dashboard/analytics")
        assert r.status_code == 200, r.text
        j = r.json()
        assert "kpi" in j, f"Missing kpi field: {list(j.keys())}"

    def test_settlement_payouts_list(self, sa):
        r = sa.get(f"{API}/settlement/payouts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_sale_writes_stock_movement(self, sa, ensure_banda):
        # Login as seed kasir (bound to outlet-sudirman) — open shift + POST /sales
        s, r = _login(KASIR)
        assert r.status_code == 200, r.text
        me = r.json()
        outlet_id = me["outlet_id"]
        # Grab any product in the kasir's scope
        rprods = s.get(f"{API}/products")
        assert rprods.status_code == 200
        prods = [p for p in rprods.json() if (p.get("outlet_id") in (None, "", outlet_id))]
        if not prods:
            pytest.skip("No products in kasir scope")
        p0 = prods[0]
        pid = p0["id"]
        pname = p0.get("name", "TestProd")
        pprice = float(p0.get("price", 10000))
        # Ensure open shift
        s.post(f"{API}/shifts/close", json={"closing_cash": 0, "note": ""}, headers=CSRF)
        ropen = s.post(f"{API}/shifts/open", json={"opening_cash": 100000, "note": "reg-test"}, headers=CSRF)
        assert ropen.status_code == 200, ropen.text
        # Create sale
        rsale = s.post(f"{API}/sales", json={
            "table": "T1",
            "lines": [{"product_id": pid, "name": pname, "quantity": 1, "price": pprice}],
            "subtotal": pprice,
            "total": pprice,
            "payment_method": "Cash",
            "cash_received": max(100000, pprice),
        }, headers=CSRF)
        assert rsale.status_code == 200, rsale.text
        sale = rsale.json()
        assert sale["total"] > 0
        # Verify stock movement (Super Admin)
        rmov = sa.get(f"{API}/inventory/stock-movements", params={"product_id": pid, "limit": 10})
        if rmov.status_code == 200:
            movs = rmov.json()
            found = any(m.get("ref_id") == sale["id"] and m.get("kind") == "sale" for m in movs)
            assert found, f"StockMovement for sale {sale['id']} not found"
        # cleanup shift
        s.post(f"{API}/shifts/close", json={"closing_cash": 100000, "note": ""}, headers=CSRF)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
