"""Iteration 12 — Feb 2026: Tax config server enforcement + Dashboard analytics + Multi-outlet."""
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
def kasir_sess():
    s = _login(*CREDS["kasir"])
    # Ensure open shift
    cur = s.get(f"{BASE_URL}/api/shifts/current").json()
    if not cur:
        r = s.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000, "note": "iter12"})
        assert r.status_code == 200, r.text
    return s


def _set_tax(super_sess, enabled: bool, percent: float):
    r = super_sess.post(f"{BASE_URL}/api/settings", json={
        "key": "tax_config",
        "value": {"enabled": enabled, "percent": percent},
    })
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module", autouse=True)
def _reset_tax_config(super_sess):
    """Reset tax_config OFF at test suite end regardless of failures."""
    yield
    _set_tax(super_sess, False, 10)


# ================== Tax config ==================

class TestTaxConfig:
    def test_tax_off_default(self, super_sess, kasir_sess):
        _set_tax(super_sess, False, 10)
        # verify read-back
        r = super_sess.get(f"{BASE_URL}/api/settings/tax_config")
        assert r.status_code == 200
        body = r.json()
        assert body.get("enabled") is False
        assert float(body.get("percent") or 0) == 10.0

        payload = {
            "table": "Meja TAX_OFF",
            "lines": [{"product_id": "p-1", "name": "Kopi", "quantity": 2, "price": 1}],
            "subtotal": 1, "tax": 999, "total": 1000,  # client lies, server must ignore tax
            "payment_method": "Cash", "cash_received": 100000,
        }
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        assert sale["tax"] == 0, sale
        assert sale["total"] == sale["subtotal"], sale

    def test_tax_on_11_percent(self, super_sess, kasir_sess):
        _set_tax(super_sess, True, 11)
        r = super_sess.get(f"{BASE_URL}/api/settings/tax_config")
        assert r.status_code == 200
        body = r.json()
        assert body.get("enabled") is True
        assert float(body["percent"]) == 11.0

        payload = {
            "table": "Meja TAX_ON",
            "lines": [{"product_id": "p-1", "name": "Kopi", "quantity": 2, "price": 1}],
            "subtotal": 1, "tax": 0, "total": 1,  # client sends tax=0, server must OVERRIDE
            "payment_method": "Cash", "cash_received": 100000,
        }
        r = kasir_sess.post(f"{BASE_URL}/api/sales", json=payload)
        assert r.status_code == 200, r.text
        sale = r.json()
        subtotal = float(sale["subtotal"])
        expected_tax = round(subtotal * 0.11)
        assert sale["tax"] == expected_tax, (sale, expected_tax)
        assert sale["total"] == round(subtotal + expected_tax), sale

    def test_tax_config_reset_off(self, super_sess):
        _set_tax(super_sess, False, 10)
        r = super_sess.get(f"{BASE_URL}/api/settings/tax_config")
        body = r.json()
        assert body["enabled"] is False
        assert float(body["percent"]) == 10.0


# ================== Dashboard analytics ==================

class TestDashboardAnalytics:
    def test_analytics_daily(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/dashboard/analytics?mode=daily")
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("kpi", "trend", "mode", "payment_breakdown", "top_products", "low_stock", "outlet_compare", "outlet_scope"):
            assert k in body, f"missing key {k}"
        assert body["mode"] == "daily"
        assert isinstance(body["trend"], list) and len(body["trend"]) == 7
        for it in body["trend"]:
            assert "label" in it and "gross" in it and "count" in it

    def test_analytics_hourly(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/dashboard/analytics?mode=hourly")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "hourly"
        assert len(body["trend"]) == 24
        labels = [it["label"] for it in body["trend"]]
        assert labels[0] == "00:00" and labels[-1] == "23:00"

    def test_analytics_outlet_all(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/dashboard/analytics?outlet_id=all&mode=daily")
        assert r.status_code == 200
        body = r.json()
        assert body["outlet_scope"] == "all"
        assert isinstance(body["outlet_compare"], list)
        assert len(body["outlet_compare"]) >= 1, "outlet_compare should be non-empty when scope=all"

    def test_analytics_single_outlet(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/dashboard/analytics?outlet_id=outlet-kemang&mode=daily")
        assert r.status_code == 200
        body = r.json()
        assert body["outlet_scope"] == "outlet-kemang"
        assert body["outlet_compare"] == []

    def test_analytics_kasir_ignores_outlet_param(self, kasir_sess):
        # Kasir passes outlet_id=all but should always be scoped to their own outlet
        r = kasir_sess.get(f"{BASE_URL}/api/dashboard/analytics?outlet_id=all&mode=daily")
        assert r.status_code == 200
        body = r.json()
        # Kasir's outlet, not 'all'
        assert body["outlet_scope"] != "all"
        assert body["outlet_scope"], "outlet_scope must be set to kasir's outlet"


# ================== Dashboard basic ==================

class TestDashboardBasic:
    def test_dashboard_all_scope(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/dashboard?outlet_id=all")
        assert r.status_code == 200
        body = r.json()
        for k in ("sales_total", "expense_total", "transaction_count", "net_profit", "outlet_scope"):
            assert k in body, f"missing key {k}"
        assert body["outlet_scope"] == "all"
