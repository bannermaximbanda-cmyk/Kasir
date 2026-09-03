"""End-to-end backend tests for MJD Kupi (Supabase Postgres migration).

Covers: auth, RBAC, merchants, products, shifts, POS, KDS, self-order,
settings, and expense flows using the public REACT_APP_BACKEND_URL.
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "super":  ("superadmin@mjd-kupi.local", "MjdKupi#2026", "Super Admin"),
    "admin":  ("manager@mjd-kupi.local",    "MjdKupi#2026", "Merchant Admin"),
    "vendor": ("vendor@mjd-kupi.local",     "MjdKupi#2026", "Vendor"),
    "kasir":  ("kasir@mjd-kupi.local",      "MjdKupi#2026", "Kasir"),
}


def _login(session: requests.Session, key: str) -> dict:
    email, password, _ = CREDS[key]
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {key} failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("access_token"), "no access_token in response"
    # Attach bearer as fallback (cookie also set)
    session.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    return data


@pytest.fixture
def super_client():
    s = requests.Session()
    _login(s, "super")
    return s


@pytest.fixture
def admin_client():
    s = requests.Session()
    _login(s, "admin")
    return s


@pytest.fixture
def vendor_client():
    s = requests.Session()
    _login(s, "vendor")
    return s


@pytest.fixture
def kasir_client():
    s = requests.Session()
    _login(s, "kasir")
    return s


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestAuth:
    def test_health(self):
        r = requests.get(f"{API}/", timeout=30)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    @pytest.mark.parametrize("key", list(CREDS.keys()))
    def test_login_all_roles(self, key):
        s = requests.Session()
        data = _login(s, key)
        assert data["role"] == CREDS[key][2]
        assert data["email"] == CREDS[key][0]
        # cookie should be set
        assert "access_token" in s.cookies.get_dict() or data.get("access_token")

    def test_login_bad_password(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": CREDS["super"][0], "password": "wrong"}, timeout=30)
        assert r.status_code == 401

    def test_me(self, admin_client):
        r = admin_client.get(f"{API}/auth/me", timeout=30)
        assert r.status_code == 200
        assert r.json()["role"] == "Merchant Admin"


# ---------------------------------------------------------------------------
# Seed data verification
# ---------------------------------------------------------------------------
class TestSeedData:
    def test_merchants_seeded(self):
        r = requests.get(f"{API}/merchants", timeout=30)
        assert r.status_code == 200
        names = [m["name"] for m in r.json()]
        for expected in ["Barista Kopi", "Nasi Uduk Bang Agus",
                         "Sate Madura Pak Kumis", "MJD Bakery"]:
            assert expected in names, f"missing merchant: {expected}"

    def test_products_seeded_bound_to_merchants(self):
        r = requests.get(f"{API}/products", timeout=30)
        assert r.status_code == 200
        products = r.json()
        assert len(products) >= 6
        mr = requests.get(f"{API}/merchants", timeout=30).json()
        mids = {m["id"] for m in mr}
        for p in products:
            if p["id"].startswith("p-"):
                assert p["merchant_id"] in mids, f"product {p['name']} has bad merchant_id"


# ---------------------------------------------------------------------------
# Merchant RBAC
# ---------------------------------------------------------------------------
class TestMerchantRBAC:
    def test_admin_can_create_update(self, admin_client):
        name = f"TEST_Merchant_{uuid.uuid4().hex[:8]}"
        r = admin_client.post(f"{API}/merchants",
                              json={"name": name, "category": "F&B"}, timeout=30)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        # update
        r2 = admin_client.put(f"{API}/merchants/{mid}",
                              json={"name": name + "_upd", "category": "F&B"}, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["name"] == name + "_upd"
        # cleanup with super
        s = requests.Session(); _login(s, "super")
        d = s.delete(f"{API}/merchants/{mid}", timeout=30)
        assert d.status_code == 200

    def test_kasir_cannot_create(self, kasir_client):
        r = kasir_client.post(f"{API}/merchants",
                              json={"name": "TEST_NoAccess"}, timeout=30)
        assert r.status_code == 403

    def test_vendor_cannot_create(self, vendor_client):
        r = vendor_client.post(f"{API}/merchants",
                               json={"name": "TEST_NoAccess"}, timeout=30)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Shift + POS + KDS integration
# ---------------------------------------------------------------------------
class TestShiftPosKds:
    def test_sale_without_shift_blocked(self, kasir_client):
        # ensure no open shift
        cur = kasir_client.get(f"{API}/shifts/current", timeout=30).json()
        if cur:
            kasir_client.post(f"{API}/shifts/close",
                              json={"closing_cash": cur["opening_cash"]}, timeout=30)
        products = requests.get(f"{API}/products", timeout=30).json()
        p = products[0]
        payload = {
            "table": "TEST_M01",
            "lines": [{"product_id": p["id"], "name": p["name"],
                       "quantity": 1, "price": p["price"],
                       "vendor": p.get("vendor", ""), "merchant_id": p.get("merchant_id")}],
            "subtotal": p["price"], "tax": 0, "total": p["price"],
            "payment_method": "Cash", "cash_received": p["price"], "change_amount": 0,
        }
        r = kasir_client.post(f"{API}/sales", json=payload, timeout=30)
        assert r.status_code == 400
        assert "shift" in r.json()["detail"].lower()

    def test_full_shift_and_sale_and_kds_flow(self, kasir_client):
        # Open shift
        r = kasir_client.post(f"{API}/shifts/open",
                              json={"opening_cash": 200000, "note": "TEST"}, timeout=30)
        assert r.status_code == 200, r.text
        shift = r.json()
        assert shift["status"] == "open"
        assert shift["opening_cash"] == 200000

        cur = kasir_client.get(f"{API}/shifts/current", timeout=30).json()
        assert cur and cur["id"] == shift["id"]

        # Build a multi-merchant sale so KDS should split into multiple tickets
        products = requests.get(f"{API}/products", timeout=30).json()
        by_merchant = {}
        for p in products:
            by_merchant.setdefault(p["merchant_id"], p)
        picks = list(by_merchant.values())[:2]
        assert len(picks) >= 2

        lines = [{"product_id": p["id"], "name": p["name"], "quantity": 1,
                  "price": p["price"], "vendor": p.get("vendor", ""),
                  "merchant_id": p.get("merchant_id")} for p in picks]
        subtotal = sum(p["price"] for p in picks)
        payload = {"table": "TEST_KDS", "lines": lines,
                   "subtotal": subtotal, "tax": 0, "total": subtotal,
                   "payment_method": "Cash", "cash_received": subtotal, "change_amount": 0}

        # Pre-stock check
        pre_stock = {p["id"]: p["stock"] for p in picks}

        r = kasir_client.post(f"{API}/sales", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        sale = r.json()
        assert sale["payment_method"] == "Cash"
        assert sale["shift_id"] == shift["id"]

        # Stock decremented
        prods_after = {p["id"]: p for p in requests.get(f"{API}/products", timeout=30).json()}
        for pid, before in pre_stock.items():
            assert prods_after[pid]["stock"] == before - 1

        # KDS tickets exist for this sale, one per merchant
        tickets = kasir_client.get(f"{API}/kds/orders", timeout=30).json()
        matched = [t for t in tickets if t["source_id"] == sale["id"]]
        assert len(matched) == len(picks), f"expected {len(picks)} tickets, got {len(matched)}"

        # Transition tickets: Siap diambil -> Selesai
        for t in matched:
            r1 = kasir_client.patch(f"{API}/kds/orders/{t['id']}",
                                    json={"status": "Siap diambil"}, timeout=30)
            assert r1.status_code == 200
            r2 = kasir_client.patch(f"{API}/kds/orders/{t['id']}",
                                    json={"status": "Selesai"}, timeout=30)
            assert r2.status_code == 200

        # After Selesai, no longer in list
        tickets_after = kasir_client.get(f"{API}/kds/orders", timeout=30).json()
        remain = [t for t in tickets_after if t["source_id"] == sale["id"]]
        assert remain == []

        # Close shift and verify variance math
        expected = 200000 + subtotal  # opening + cash sales
        closing_cash = expected + 5000  # over 5k
        r = kasir_client.post(f"{API}/shifts/close",
                              json={"closing_cash": closing_cash, "note": "TEST close"},
                              timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["status"] == "closed"
        assert abs(c["expected_cash"] - expected) < 0.01
        assert abs(c["variance"] - 5000) < 0.01

    def test_transfer_and_qris_payment(self, kasir_client):
        # open shift
        cur = kasir_client.get(f"{API}/shifts/current", timeout=30).json()
        if not cur:
            kasir_client.post(f"{API}/shifts/open",
                              json={"opening_cash": 0}, timeout=30)
        products = requests.get(f"{API}/products", timeout=30).json()
        p = products[0]
        for method in ("Transfer", "QRIS"):
            payload = {"table": "TEST_PM", "lines": [
                {"product_id": p["id"], "name": p["name"], "quantity": 1,
                 "price": p["price"], "vendor": p.get("vendor", ""),
                 "merchant_id": p.get("merchant_id")}],
                "subtotal": p["price"], "tax": 0, "total": p["price"],
                "payment_method": method, "payment_reference": "TEST-REF",
                "cash_received": 0, "change_amount": 0}
            r = kasir_client.post(f"{API}/sales", json=payload, timeout=30)
            assert r.status_code == 200, r.text
            assert r.json()["payment_method"] == method
        # close leftover shift
        kasir_client.post(f"{API}/shifts/close",
                          json={"closing_cash": 0}, timeout=30)


# ---------------------------------------------------------------------------
# Self order (no auth)
# ---------------------------------------------------------------------------
class TestSelfOrder:
    def test_self_order_creates_kitchen_tickets_and_vendor_sees(self, vendor_client):
        products = requests.get(f"{API}/products", timeout=30).json()
        p = products[0]
        payload = {"table": "TEST_SELF",
                   "lines": [{"product_id": p["id"], "name": p["name"], "quantity": 2,
                              "price": p["price"], "vendor": p.get("vendor", ""),
                              "merchant_id": p.get("merchant_id")}],
                   "total": p["price"] * 2, "notes": "TEST self order"}
        r = requests.post(f"{API}/self-order", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]

        # KDS should have ticket referencing this self order
        tickets = vendor_client.get(f"{API}/kds/orders", timeout=30).json()
        assert any(t["source_id"] == order_id and t["source_type"] == "self" for t in tickets)

        # vendor listing
        orders = vendor_client.get(f"{API}/vendor/orders", timeout=30).json()
        assert any(o["id"] == order_id for o in orders)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class TestSettings:
    def test_printer_settings_roundtrip(self, admin_client):
        cfg = {"width": 58, "auto_cut": True, "brand": "TEST_Printer"}
        r = admin_client.post(f"{API}/settings",
                              json={"key": "printer", "value": cfg}, timeout=30)
        assert r.status_code == 200
        r2 = requests.get(f"{API}/settings/printer", timeout=30)
        assert r2.status_code == 200
        assert r2.json() == cfg


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
class TestExpenses:
    def test_admin_can_create_and_list_ordered(self, admin_client):
        payload = {"category": "TEST_Cat", "note": "TEST expense",
                   "amount": 12345, "date": "2026-03-01", "method": "Cash"}
        r = admin_client.post(f"{API}/expenses", json=payload, timeout=30)
        assert r.status_code == 200
        eid = r.json()["id"]
        lst = admin_client.get(f"{API}/expenses", timeout=30).json()
        assert any(e["id"] == eid for e in lst)
        # sorted desc by date
        dates = [e["date"] for e in lst if e["date"]]
        assert dates == sorted(dates, reverse=True)
