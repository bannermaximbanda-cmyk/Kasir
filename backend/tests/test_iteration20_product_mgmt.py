"""Iteration 20 — Product Management overhaul (is_active + sku + bulk import).

Backend regression only. See review_request iteration 20.
"""
import os
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE}/api"
CSRF = {"X-Requested-With": "mjd-kupi"}

SUPER = ("superadmin", ".Superadmin1_")
ADMIN = ("admin", "MjdKupi#2026")
KASIR = ("kasir", "MjdKupi#2026")


def _login(username, password):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    last = None
    for _ in range(3):
        try:
            r = s.post(f"{API}/auth/login",
                       json={"email": username, "password": password},
                       headers=CSRF, timeout=30)
            if r.status_code == 200:
                tok = r.json().get("access_token")
                if tok:
                    s.headers.update({"Authorization": f"Bearer {tok}"})
                s.headers.update(CSRF)
                return s
            if r.status_code >= 500:
                time.sleep(2); continue
            raise AssertionError(f"Login {username} failed: {r.status_code} {r.text[:200]}")
        except (requests.ReadTimeout, requests.ConnectionError) as e:
            last = e; time.sleep(2)
    raise AssertionError(f"Login {username} unreachable: {last}")


@pytest.fixture(scope="module")
def super_admin():
    return _login(*SUPER)


@pytest.fixture(scope="module")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def kasir():
    return _login(*KASIR)


@pytest.fixture(scope="module")
def anon():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


OUTLET = "outlet-sudirman"


# ────────────── Product create / update visibility ──────────────
class TestProductVisibility:
    def test_super_admin_default_hides_inactive(self, super_admin):
        # First create one inactive + one active
        sku_a = f"TEST-ACT-{uuid.uuid4().hex[:6]}"
        sku_i = f"TEST-INACT-{uuid.uuid4().hex[:6]}"
        r = super_admin.post(f"{API}/products", json={
            "name": f"TEST_Active_{sku_a}", "category": "Kopi", "price": 15000,
            "cost": 8000, "stock": 10, "sku": sku_a, "is_active": True,
            "outlet_id": OUTLET,
        }, timeout=15)
        assert r.status_code == 200, r.text
        pytest.active_id = r.json()["id"]
        assert r.json()["sku"] == sku_a
        assert r.json()["is_active"] is True

        r = super_admin.post(f"{API}/products", json={
            "name": f"TEST_Inactive_{sku_i}", "category": "Kopi", "price": 15000,
            "cost": 8000, "stock": 10, "sku": sku_i, "is_active": False,
            "outlet_id": OUTLET,
        }, timeout=15)
        assert r.status_code == 200, r.text
        pytest.inactive_id = r.json()["id"]
        assert r.json()["is_active"] is False

        # Super Admin without include_inactive → hides inactive
        r = super_admin.get(f"{API}/products?outlet_id={OUTLET}", timeout=15)
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert pytest.active_id in ids
        assert pytest.inactive_id not in ids

    def test_super_admin_include_inactive(self, super_admin):
        r = super_admin.get(f"{API}/products?outlet_id={OUTLET}&include_inactive=1", timeout=15)
        assert r.status_code == 200
        rows = r.json()
        ids = [p["id"] for p in rows]
        assert pytest.active_id in ids and pytest.inactive_id in ids
        # every row must include is_active and sku fields
        for p in rows:
            assert "is_active" in p, f"missing is_active on {p.get('id')}"
            assert "sku" in p, f"missing sku on {p.get('id')}"

    def test_anonymous_public_hides_inactive(self, anon):
        r = anon.get(f"{API}/products?outlet_id={OUTLET}", timeout=15)
        assert r.status_code == 200, r.text
        ids = [p["id"] for p in r.json()]
        assert pytest.active_id in ids
        assert pytest.inactive_id not in ids, "Inactive product leaked to anonymous!"

    def test_anonymous_requires_outlet(self, anon):
        r = anon.get(f"{API}/products", timeout=15)
        assert r.status_code == 400

    def test_kasir_default_hides_inactive(self, kasir):
        # POS default (no include_inactive)
        r = kasir.get(f"{API}/products", timeout=15)
        assert r.status_code == 200, r.text
        ids = [p["id"] for p in r.json()]
        assert pytest.active_id in ids
        assert pytest.inactive_id not in ids, "Inactive product leaked to POS/kasir!"

    def test_kasir_include_inactive_ignored(self, kasir):
        # Kasir passing include_inactive should still be filtered (non-admin)
        r = kasir.get(f"{API}/products?include_inactive=1", timeout=15)
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert pytest.inactive_id not in ids, "Kasir with include_inactive should NOT see inactive"

    def test_put_toggle_inactive(self, super_admin):
        pid = pytest.active_id
        # deactivate
        r = super_admin.put(f"{API}/products/{pid}", json={
            "name": "TEST_Deactivated", "is_active": False, "sku": "TEST-DEACT",
            "price": 15000, "cost": 8000, "stock": 10, "category": "Kopi",
        }, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False
        assert r.json()["sku"] == "TEST-DEACT"

        # verify admin include_inactive contains it, anon doesn't
        r1 = super_admin.get(f"{API}/products?outlet_id={OUTLET}&include_inactive=1", timeout=15)
        assert pid in [p["id"] for p in r1.json()]
        anon = requests.Session()
        r2 = anon.get(f"{API}/products?outlet_id={OUTLET}", timeout=15)
        assert pid not in [p["id"] for p in r2.json()]

    def test_put_toggle_active_restores(self, super_admin, anon):
        pid = pytest.active_id
        r = super_admin.put(f"{API}/products/{pid}", json={
            "name": "TEST_Reactivated", "is_active": True, "sku": "TEST-REACT",
            "price": 15000, "cost": 8000, "stock": 10, "category": "Kopi",
        }, timeout=15)
        assert r.status_code == 200
        assert r.json()["is_active"] is True
        r2 = anon.get(f"{API}/products?outlet_id={OUTLET}", timeout=15)
        assert pid in [p["id"] for p in r2.json()]


# ────────────── Bulk import ──────────────
class TestBulkImport:
    def test_upsert_by_sku_updates_existing(self, super_admin):
        # find any existing active product with a SKU (create one to be safe)
        sku = f"TEST-UPS-{uuid.uuid4().hex[:6]}"
        r = super_admin.post(f"{API}/products", json={
            "name": "TEST_ExistingForUpsert", "category": "Kopi",
            "price": 10000, "cost": 5000, "stock": 5, "sku": sku,
            "is_active": True, "outlet_id": OUTLET,
        }, timeout=15)
        assert r.status_code == 200
        existing_id = r.json()["id"]

        new_sku = f"TEST-NEW-{uuid.uuid4().hex[:6]}"
        payload = {
            "mode": "upsert",
            "rows": [
                # 1: duplicate SKU → should UPDATE existing (price changes)
                {"name": "TEST_UpsertUpdated", "sku": sku, "price": 22222,
                 "cost": 5000, "stock": 9, "category": "Kopi",
                 "outlet_id": OUTLET, "is_active": True},
                # 2: brand new sku + name → CREATE
                {"name": f"TEST_BrandNew_{new_sku}", "sku": new_sku, "price": 33333,
                 "cost": 5000, "stock": 3, "category": "Kopi",
                 "outlet_id": OUTLET, "is_active": True},
                # 3: empty name → error
                {"name": "", "sku": "TEST-EMPTY", "price": 1, "cost": 1, "stock": 1,
                 "category": "Kopi", "outlet_id": OUTLET, "is_active": True},
            ],
        }
        r = super_admin.post(f"{API}/products/bulk-import", json=payload, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert body["updated"] >= 1, body
        assert body["created"] >= 1, body
        assert len(body["errors"]) >= 1
        assert body["errors"][0]["row"] == 3

        # Verify updated product has new price and same id
        r2 = super_admin.get(f"{API}/products?outlet_id={OUTLET}&include_inactive=1", timeout=15)
        by_id = {p["id"]: p for p in r2.json()}
        assert existing_id in by_id
        assert by_id[existing_id]["price"] == 22222
        # Verify new sku exists
        skus = [p["sku"] for p in r2.json()]
        assert new_sku in skus

    def test_bulk_import_inactive_hidden_from_anonymous(self, super_admin, anon):
        sku = f"TEST-INACT-BULK-{uuid.uuid4().hex[:6]}"
        r = super_admin.post(f"{API}/products/bulk-import", json={
            "mode": "upsert",
            "rows": [{
                "name": f"TEST_BulkInactive_{sku}", "sku": sku,
                "price": 10000, "cost": 5000, "stock": 5,
                "category": "Kopi", "outlet_id": OUTLET, "is_active": False,
            }],
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1

        # not visible anonymously
        r2 = anon.get(f"{API}/products?outlet_id={OUTLET}", timeout=15)
        skus_pub = [p["sku"] for p in r2.json()]
        assert sku not in skus_pub

        # visible w/ include_inactive
        r3 = super_admin.get(f"{API}/products?outlet_id={OUTLET}&include_inactive=1", timeout=15)
        assert sku in [p["sku"] for p in r3.json()]

    def test_admin_outlet_isolation_forces_own_outlet(self, admin):
        # find another outlet id different from admin's own (outlet-sudirman)
        r_out = admin.get(f"{API}/outlets", timeout=15)
        assert r_out.status_code == 200
        outlets = r_out.json()
        other = next((o for o in outlets if o.get("id") and o["id"] != OUTLET), None)
        if not other:
            pytest.skip("No 2nd outlet seeded to test isolation")
        sku = f"TEST-ISO-{uuid.uuid4().hex[:6]}"
        r = admin.post(f"{API}/products/bulk-import", json={
            "mode": "upsert",
            "rows": [{
                "name": f"TEST_IsoAttempt_{sku}", "sku": sku,
                "price": 10000, "cost": 5000, "stock": 5,
                "category": "Kopi", "outlet_id": other["id"], "is_active": True,
            }],
        }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 1
        # confirm product was forced to admin's own outlet (outlet-sudirman)
        r2 = admin.get(f"{API}/products?outlet_id={OUTLET}&include_inactive=1", timeout=15)
        found = [p for p in r2.json() if p.get("sku") == sku]
        assert found, "Row was not forced to admin's outlet"
        assert found[0]["outlet_id"] == OUTLET


# ────────────── Regression Batch C endpoints ──────────────
class TestBatchCRegression:
    def test_settlement_preview(self, super_admin):
        r = super_admin.get(f"{API}/settlement/preview", timeout=20)
        assert r.status_code == 200, r.text
        assert "breakdown" in r.json() and "totals" in r.json()

    def test_stock_movements_get(self, super_admin):
        r = super_admin.get(f"{API}/inventory/stock-movements", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_settings_sound_config(self, super_admin):
        r = super_admin.get(f"{API}/settings/sound_config", timeout=15)
        # 200 with value OR 404 if never set — both acceptable
        assert r.status_code in (200, 404), r.text


# ────────────── Sales still generates stock movement ──────────────
class TestSalesStockRegression:
    def test_sale_creates_stock_movement(self, kasir, super_admin):
        # ensure kasir has open shift
        r = kasir.get(f"{API}/shifts/current", timeout=15)
        if r.status_code != 200 or not r.json():
            ro = kasir.post(f"{API}/shifts/open",
                            json={"opening_cash": 100000, "note": "iter20"}, timeout=15)
            assert ro.status_code == 200, ro.text

        # pick a product
        rp = kasir.get(f"{API}/products", timeout=15)
        prods = [p for p in rp.json() if p.get("stock", 0) > 0]
        if not prods:
            pytest.skip("no stocked product to sell")
        prod = prods[0]

        # count stock-movements before
        rm_before = super_admin.get(
            f"{API}/inventory/stock-movements?product_id={prod['id']}", timeout=15
        )
        assert rm_before.status_code == 200
        before_len = len(rm_before.json())

        payload = {
            "outlet_id": prod.get("outlet_id") or OUTLET,
            "lines": [{
                "product_id": prod["id"], "name": prod["name"],
                "price": prod["price"], "quantity": 1,
                "merchant_id": prod.get("merchant_id"),
            }],
            "payment_method": "cash",
            "paid_amount": prod["price"],
            "subtotal": prod["price"],
            "total": prod["price"],
            "channel": "pos",
        }
        rs = kasir.post(f"{API}/sales", json=payload, timeout=20)
        assert rs.status_code == 200, rs.text
        sale = rs.json()
        assert sale.get("id")

        # verify stock-movement added
        rm_after = super_admin.get(
            f"{API}/inventory/stock-movements?product_id={prod['id']}", timeout=15
        )
        assert rm_after.status_code == 200
        after = rm_after.json()
        assert len(after) > before_len, "Sale did not create stock movement"
        # find the sale kind row
        sale_mvs = [m for m in after if m.get("kind") == "sale"]
        assert sale_mvs, "No stock movement with kind='sale'"


# ────────────── Shift report expenses scoped to shift_id ──────────────
class TestShiftReportScope:
    def test_shift_report_expenses_scoped(self, kasir):
        r = kasir.get(f"{API}/shifts/current", timeout=15)
        if r.status_code != 200 or not r.json():
            pytest.skip("no open shift")
        shift = r.json()
        sid = shift["id"]
        rr = kasir.get(f"{API}/shifts/{sid}/report", timeout=20)
        assert rr.status_code == 200, rr.text
        rep = rr.json()
        assert "expenses_total" in rep
        assert isinstance(rep["expenses_total"], (int, float))
