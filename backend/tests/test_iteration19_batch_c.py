"""Batch C regression tests — Vendor Settlement, Advanced Inventory (StockMovements),
Bulk Product Import, Sound Settings, plus regression on Sales/Analytics/SelfOrder.

Iteration 19 — MJD Kupi POS
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


# ─────────────────── helpers / fixtures ───────────────────
def _login(username, password):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    last_exc = None
    for attempt in range(3):
        try:
            r = s.post(f"{API}/auth/login", json={"email": username, "password": password},
                       headers=CSRF, timeout=30)
            if r.status_code == 200:
                token = r.json().get("access_token")
                if token:
                    s.headers.update({"Authorization": f"Bearer {token}"})
                s.headers.update(CSRF)
                return s
            if r.status_code >= 500:
                time.sleep(2)
                continue
            assert False, f"Login {username} failed: {r.status_code} {r.text[:200]}"
        except (requests.ReadTimeout, requests.ConnectionError) as e:
            last_exc = e
            time.sleep(2)
    raise AssertionError(f"Login {username} unreachable: {last_exc}")


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
def merchants(super_admin):
    r = super_admin.get(f"{API}/merchants", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) > 0, "Need at least 1 merchant seeded"
    return data


@pytest.fixture(scope="module")
def outlets(super_admin):
    r = super_admin.get(f"{API}/outlets", timeout=15)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def kasir_open_shift(kasir):
    # ensure shift open
    r = kasir.get(f"{API}/shifts/current", timeout=15)
    if r.status_code == 200 and r.json():
        return r.json()
    r = kasir.post(f"{API}/shifts/open", json={"opening_cash": 100000, "note": "test"}, timeout=15)
    assert r.status_code == 200, f"Cannot open shift: {r.text}"
    return r.json()


# ─────────────────── Settlement Center ───────────────────
class TestSettlement:
    def test_preview_structure(self, super_admin):
        r = super_admin.get(f"{API}/settlement/preview", timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "breakdown" in data and "totals" in data
        assert isinstance(data["breakdown"], list)
        totals = data["totals"]
        for k in ("gross", "commission", "net", "item_count"):
            assert k in totals
        if data["breakdown"]:
            b = data["breakdown"][0]
            for k in ("merchant_id", "merchant_name", "commission_scheme",
                      "commission_percent", "commission_fixed", "gross",
                      "item_count", "commission", "net"):
                assert k in b, f"missing {k} in breakdown row"

    def test_payout_zero_omset_returns_400(self, super_admin, merchants):
        # Pick a merchant + far-future dates to guarantee zero sales
        mid = merchants[0]["id"]
        r = super_admin.post(f"{API}/settlement/payouts", json={
            "merchant_id": mid,
            "period_start": "2099-01-01",
            "period_end": "2099-01-05",
            "note": "test-zero",
        }, timeout=15)
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        assert "omset" in r.text.lower() or "belum" in r.text.lower()

    def test_payout_create_and_list(self, super_admin, merchants):
        # Find a merchant that has some gross via preview
        pv = super_admin.get(f"{API}/settlement/preview", timeout=20).json()
        breakdown = pv["breakdown"]
        target = next((b for b in breakdown if b["gross"] > 0), None)
        if not target:
            pytest.skip("No merchant has gross sales in preview — cannot test payout create")
        r = super_admin.post(f"{API}/settlement/payouts", json={
            "merchant_id": target["merchant_id"],
            "period_start": "2020-01-01",
            "period_end": "2099-12-31",
            "note": f"TEST_payout_{uuid.uuid4().hex[:6]}",
        }, timeout=20)
        assert r.status_code == 200, r.text
        payout = r.json()
        for k in ("id", "gross", "commission", "net", "item_count", "sale_ids", "status"):
            assert k in payout
        assert payout["status"] == "paid"
        assert isinstance(payout["sale_ids"], list)
        assert payout["gross"] == target["gross"]
        assert payout["commission"] == target["commission"]
        assert payout["net"] == target["net"]

        # list should include the freshly-created one first
        lr = super_admin.get(f"{API}/settlement/payouts", timeout=15)
        assert lr.status_code == 200
        lst = lr.json()
        assert isinstance(lst, list) and len(lst) > 0
        assert lst[0]["id"] == payout["id"]


# ─────────────────── Stock Movements ───────────────────
class TestStockMovements:
    def test_list_movements(self, super_admin):
        r = super_admin.get(f"{API}/inventory/stock-movements", params={"limit": 50}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def _first_product_for_outlet(self, session, outlet_id=None):
        params = {}
        if outlet_id:
            params["outlet_id"] = outlet_id
        r = session.get(f"{API}/products", params=params, timeout=15)
        assert r.status_code == 200
        prods = r.json()
        assert prods, "Need at least one product"
        return prods[0]

    def test_manual_in_creates_movement_and_updates_stock(self, super_admin):
        prod = self._first_product_for_outlet(super_admin)
        pid = prod["id"]
        before = int(prod.get("stock") or 0)
        r = super_admin.post(f"{API}/inventory/stock-movements", json={
            "product_id": pid, "kind": "in", "delta": 5, "reason": "TEST_in"
        }, timeout=15)
        assert r.status_code == 200, r.text
        mv = r.json()
        assert mv["delta"] == 5
        assert mv["stock_before"] == before
        assert mv["stock_after"] == before + 5
        # verify product stock updated
        pr = super_admin.get(f"{API}/products", timeout=15).json()
        cur = next(p for p in pr if p["id"] == pid)
        assert int(cur["stock"]) == before + 5
        # legacy StockLog also written
        logs = super_admin.get(f"{API}/stock-logs", timeout=15).json()
        assert any(l["product_id"] == pid and l["reason"] == "TEST_in" for l in logs), \
            "legacy StockLog mirror missing"

    def test_opname_requires_target_stock(self, super_admin):
        prod = self._first_product_for_outlet(super_admin)
        r = super_admin.post(f"{API}/inventory/stock-movements", json={
            "product_id": prod["id"], "kind": "opname", "reason": "TEST_opname_bad"
        }, timeout=15)
        assert r.status_code == 400, r.text

    def test_opname_sets_stock_exactly(self, super_admin):
        prod = self._first_product_for_outlet(super_admin)
        pid = prod["id"]
        target = 42
        r = super_admin.post(f"{API}/inventory/stock-movements", json={
            "product_id": pid, "kind": "opname", "target_stock": target,
            "reason": "TEST_opname"
        }, timeout=15)
        assert r.status_code == 200, r.text
        mv = r.json()
        assert mv["stock_after"] == target
        pr = super_admin.get(f"{API}/products", timeout=15).json()
        cur = next(p for p in pr if p["id"] == pid)
        assert int(cur["stock"]) == target

    def test_admin_cannot_touch_other_outlet(self, admin, super_admin):
        # find a product in an outlet different than admin's
        me = admin.get(f"{API}/auth/me", timeout=10).json()
        admin_outlet = me.get("outlet_id")
        all_prods = super_admin.get(f"{API}/products", timeout=15).json()
        foreign = next((p for p in all_prods
                        if p.get("outlet_id") and p["outlet_id"] != admin_outlet), None)
        if not foreign:
            pytest.skip("No product in a different outlet for isolation test")
        r = admin.post(f"{API}/inventory/stock-movements", json={
            "product_id": foreign["id"], "kind": "in", "delta": 1, "reason": "TEST_isolation"
        }, timeout=15)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


# ─────────────────── Bulk Import ───────────────────
class TestBulkImport:
    def test_upsert_new_and_existing(self, super_admin):
        # pick an existing product to update
        prods = super_admin.get(f"{API}/products", timeout=15).json()
        existing = prods[0]
        new_name = f"TEST_import_{uuid.uuid4().hex[:6]}"
        payload = {
            "mode": "upsert",
            "rows": [
                {"name": new_name, "category": "TestCat", "vendor": "MJD Kupi",
                 "outlet_id": existing.get("outlet_id"), "price": 12345, "cost": 5000, "stock": 7},
                {"name": existing["name"], "outlet_id": existing.get("outlet_id"),
                 "category": existing.get("category", "Lain-lain"),
                 "vendor": existing.get("vendor", "MJD Kupi"),
                 "price": float(existing.get("price") or 0) + 500,
                 "cost": float(existing.get("cost") or 0),
                 "stock": int(existing.get("stock") or 0) + 1,
                 "color": existing.get("color", "#ffedd5")},
            ],
        }
        r = super_admin.post(f"{API}/products/bulk-import", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["created"] == 1
        assert out["updated"] == 1
        assert out["total"] == 2
        assert out["errors"] == []

        # verify update reflected
        prods2 = super_admin.get(f"{API}/products", timeout=15).json()
        updated = next(p for p in prods2 if p["id"] == existing["id"])
        assert float(updated["price"]) == float(existing.get("price") or 0) + 500
        # verify new product exists
        assert any(p["name"] == new_name for p in prods2)

    def test_row_missing_name_returns_in_errors(self, super_admin):
        payload = {"mode": "upsert", "rows": [
            {"name": "", "outlet_id": "outlet-sudirman", "price": 1000, "cost": 500, "stock": 1}
        ]}
        r = super_admin.post(f"{API}/products/bulk-import", json=payload, timeout=15)
        # Pydantic may either reject "" as valid (since name: str) - or endpoint catches it.
        # Expected: endpoint's own guard catches empty string → 200 with errors[]
        # If Pydantic accepts, we still assert either 200 with errors or 422.
        if r.status_code == 200:
            body = r.json()
            assert body["created"] == 0 and body["updated"] == 0
            assert len(body["errors"]) == 1
        else:
            assert r.status_code == 422, r.text

    def test_admin_bulk_import_forced_to_own_outlet(self, admin, super_admin, outlets):
        me = admin.get(f"{API}/auth/me", timeout=10).json()
        admin_outlet = me.get("outlet_id") or "outlet-sudirman"
        # Pick a foreign outlet id
        foreign_outlet = next((o["id"] for o in outlets if o["id"] != admin_outlet), None)
        if not foreign_outlet:
            pytest.skip("Only one outlet available; cannot test isolation")
        new_name = f"TEST_admin_iso_{uuid.uuid4().hex[:6]}"
        r = admin.post(f"{API}/products/bulk-import", json={
            "mode": "upsert",
            "rows": [{"name": new_name, "outlet_id": foreign_outlet,
                      "price": 1000, "cost": 500, "stock": 3}],
        }, timeout=15)
        assert r.status_code == 200, r.text
        # find the created product; its outlet_id must be forced to admin's outlet
        prods = super_admin.get(f"{API}/products", timeout=15).json()
        created = next((p for p in prods if p["name"] == new_name), None)
        assert created is not None
        assert created["outlet_id"] == admin_outlet, \
            f"Expected outlet forced to {admin_outlet}, got {created['outlet_id']}"


# ─────────────────── Sound Settings ───────────────────
class TestSoundSettings:
    def test_sound_config_persist(self, super_admin):
        cfg = {"enabled": True, "volume": 0.7,
               "chime_new_order": "bell", "chime_kds_ready": "ding"}
        r = super_admin.post(f"{API}/settings", json={
            "key": "sound_config", "value": cfg
        }, timeout=15)
        assert r.status_code == 200, r.text
        r2 = super_admin.get(f"{API}/settings/sound_config", timeout=15)
        assert r2.status_code == 200
        assert r2.json() == cfg


# ─────────────────── Regression ───────────────────
class TestRegression:
    def test_sale_generates_stock_movement_and_deducts(self, kasir, kasir_open_shift, super_admin):
        # find a product in kasir's outlet (or default)
        prods = kasir.get(f"{API}/products", timeout=15).json()
        prod = next((p for p in prods if int(p.get("stock") or 0) > 2), None)
        if not prod:
            pytest.skip("no product with enough stock for sale test")
        before = int(prod["stock"])
        sale_body = {
            "table": "TEST_meja",
            "lines": [{
                "product_id": prod["id"], "name": prod["name"], "quantity": 1,
                "price": float(prod["price"]), "vendor": prod.get("vendor", "MJD Kupi"),
                "merchant_id": prod.get("merchant_id"),
                "variant_id": None, "variant_name": "", "notes": ""
            }],
            "subtotal": float(prod["price"]),
            "tax": 0, "total": float(prod["price"]),
            "payment_method": "Cash",
            "cash_received": float(prod["price"]),
        }
        r = kasir.post(f"{API}/sales", json=sale_body, timeout=20)
        assert r.status_code == 200, r.text
        sale = r.json()
        # verify stock deducted
        prods2 = kasir.get(f"{API}/products", timeout=15).json()
        cur = next(p for p in prods2 if p["id"] == prod["id"])
        assert int(cur["stock"]) == before - 1, f"stock not deducted: {before}→{cur['stock']}"
        # verify stock movement created with ref_id=sale.id
        movs = super_admin.get(f"{API}/inventory/stock-movements",
                               params={"product_id": prod["id"], "kind": "sale", "limit": 10},
                               timeout=15).json()
        matching = [m for m in movs if m.get("ref_id") == sale["id"]]
        assert matching, "No StockMovement(kind=sale) with ref_id=sale.id"
        m = matching[0]
        assert m["delta"] < 0
        assert m["stock_before"] > m["stock_after"]

    def test_dashboard_analytics_structure(self, super_admin):
        r = super_admin.get(f"{API}/dashboard/analytics", timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "kpi" in data
        assert "trend" in data

    def test_self_order_accept_double_click_409(self, kasir, kasir_open_shift, super_admin, outlets):
        # create a self-order
        prods = kasir.get(f"{API}/products", timeout=15).json()
        prod = next((p for p in prods if int(p.get("stock") or 0) > 2), None)
        if not prod:
            pytest.skip("no stock for self-order")
        outlet_id = prod.get("outlet_id") or "outlet-sudirman"
        body = {
            "table": "TEST_qr",
            "outlet_id": outlet_id,
            "customer_name": "TEST_customer",
            "customer_phone": "0812",
            "total": float(prod["price"]),
            "notes": "",
            "payment_method": "Cash",
            "payment_proof": "",
            "lines": [{
                "product_id": prod["id"], "name": prod["name"], "quantity": 1,
                "price": float(prod["price"]), "vendor": prod.get("vendor", "MJD Kupi"),
                "merchant_id": prod.get("merchant_id"),
                "variant_id": None, "variant_name": "", "notes": ""
            }]
        }
        # public endpoint but still needs CSRF header (state-changing)
        pub = requests.Session()
        pub.headers.update({"Content-Type": "application/json", **CSRF})
        r = pub.post(f"{API}/self-order", json=body, timeout=15)
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]
        # accept twice, first succeeds, second 409
        r1 = kasir.post(f"{API}/self-order/{order_id}/accept", timeout=20)
        r2 = kasir.post(f"{API}/self-order/{order_id}/accept", timeout=20)
        statuses = sorted([r1.status_code, r2.status_code])
        # One should be 200 (or 400 if shift race), the other 409
        assert 409 in statuses, f"Expected 409 on 2nd click, got {statuses}: {r1.text} / {r2.text}"
