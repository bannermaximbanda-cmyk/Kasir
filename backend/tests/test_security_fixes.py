"""Security audit follow-up verification for MJD Kupi (Jan 2026)."""
import os
import re
import subprocess
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://kupi-kasir-pro.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CREDS = {
    "superadmin": ("superadmin", ".Superadmin1_"),
    "admin": ("admin", "MjdKupi#2026"),
    "vendor": ("vendor", "MjdKupi#2026"),
    "kasir": ("kasir", "MjdKupi#2026"),
}


CSRF_HEADER = {"X-Requested-With": "mjd-kupi"}


def login(role_key):
    u, p = CREDS[role_key]
    s = requests.Session()
    s.headers.update(CSRF_HEADER)
    r = s.post(f"{API}/auth/login", json={"email": u, "password": p}, timeout=20)
    assert r.status_code == 200, f"login {role_key} failed: {r.status_code} {r.text}"
    return s, r


# -------------------- CSRF header middleware --------------------

def test_csrf_post_without_header_forbidden():
    s, _ = login("kasir")
    # Strip CSRF header for this call
    r = s.post(f"{API}/expenses",
               json={"category": "Operasional", "note": "CSRF_TEST", "amount": 1000,
                     "date": "2026-02-15", "method": "Cash"},
               headers={"X-Requested-With": ""}, timeout=20)
    # Requests will send empty header value; middleware should still reject.
    # If empty header still allowed, try deleting via a fresh session
    if r.status_code != 403:
        s2 = requests.Session()
        # copy auth cookie
        for c in s.cookies:
            s2.cookies.set(c.name, c.value)
        r = s2.post(f"{API}/expenses",
                    json={"category": "Operasional", "note": "CSRF_TEST", "amount": 1000,
                          "date": "2026-02-15", "method": "Cash"}, timeout=20)
    assert r.status_code == 403, f"expected 403 without CSRF header, got {r.status_code} {r.text}"
    assert "csrf" in r.text.lower(), f"expected CSRF error detail, got {r.text}"


def test_csrf_login_allowlisted_without_header():
    # Fresh session without CSRF header
    s = requests.Session()
    r = s.post(f"{API}/auth/login",
               json={"email": "admin", "password": "MjdKupi#2026"}, timeout=20)
    assert r.status_code == 200, f"login should be allowlisted without CSRF header, got {r.status_code} {r.text}"


def test_csrf_self_order_allowlisted_without_header():
    s = requests.Session()
    r = s.post(f"{API}/self-order",
               json={"table": "CSRF-SO", "total": 15000,
                     "lines": [{"product_id": "p-2", "name": "x", "quantity": 1, "price": 15000,
                                "merchant_id": "m-barista", "vendor": "Barista Kopi"}],
                     "notes": "csrf", "payment_method": "QRIS", "payment_proof": "img"},
               timeout=20)
    assert r.status_code == 200, f"self-order should be allowlisted, got {r.status_code} {r.text}"


# -------------------- SEC-001: SameSite=Lax --------------------

def test_sec001_login_cookie_samesite_lax():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "superadmin", "password": ".Superadmin1_"}, timeout=20)
    assert r.status_code == 200
    # Look at set-cookie header(s) — requests concatenates with comma but SameSite always present
    raw = r.headers.get("set-cookie") or ""
    # Also collect from raw
    joined = ", ".join(v for k, v in r.raw.headers.items() if k.lower() == "set-cookie") if hasattr(r, "raw") else raw
    combined = (raw + " " + joined).lower()
    assert "samesite=lax" in combined, f"Expected SameSite=Lax cookie, got: {combined}"
    assert "samesite=none" not in combined, f"Cookie still SameSite=None: {combined}"


# -------------------- SEC-002: plain_password gated + audit log --------------------

def test_sec002_plain_password_reveal_enabled_and_audit_log():
    s, _ = login("superadmin")
    r = s.get(f"{API}/admin/users", timeout=20)
    assert r.status_code == 200, r.text
    users = r.json()
    assert len(users) >= 4
    # reveal_enabled true because ENV ALLOW_PLAIN_PASSWORD_VIEW=true
    assert all(u.get("reveal_enabled") is True for u in users), "reveal_enabled not true for all users"
    # At least one has non-empty plain_password
    with_pw = [u for u in users if u.get("plain_password")]
    assert with_pw, "no user has plain_password exposed"

    # Audit log check
    try:
        out = subprocess.run(
            ["bash", "-lc", "grep '\\[audit\\] user_list_read' /var/log/supervisor/backend.err.log | tail -5"],
            capture_output=True, text=True, timeout=10,
        )
        combined = out.stdout + out.stderr
    except Exception as e:
        combined = ""
        print("audit log check failed:", e)
    print("AUDIT LOG TAIL:", combined)
    assert "user_list_read" in combined, "audit log line for user_list_read not found"


# -------------------- SEC-003: Vendor scoping --------------------

def test_sec003_vendor_me_has_merchant_id():
    s, _ = login("vendor")
    r = s.get(f"{API}/auth/me", timeout=20)
    assert r.status_code == 200
    me = r.json()
    # This is expected per problem statement but public_user() may not include merchant_id
    assert me.get("merchant_id") == "m-barista", f"/auth/me missing merchant_id='m-barista' — got {me}"


def test_sec003_vendor_kds_orders_scoped():
    # Seed cross-merchant KDS tickets via Kasir POS then check vendor sees only own merchant.
    ks, _ = login("kasir")
    # Ensure shift open
    r = ks.get(f"{API}/shifts/current", timeout=20)
    if not r.json():
        ks.post(f"{API}/shifts/open", json={"opening_cash": 100000, "note": "sec-test"}, timeout=20)
    # Create sale with mixed merchants: p-1 (barista) + p-3 (nasi-uduk)
    payload = {
        "table": "SEC-KDS",
        "lines": [
            {"product_id": "p-1", "name": "x", "quantity": 1, "price": 1, "merchant_id": "m-barista", "vendor": "Barista Kopi"},
            {"product_id": "p-3", "name": "y", "quantity": 1, "price": 1, "merchant_id": "m-nasi-uduk", "vendor": "Nasi Uduk Bang Agus"},
        ],
        "subtotal": 2, "tax": 0, "total": 2,
        "payment_method": "Cash", "cash_received": 100000,
    }
    r = ks.post(f"{API}/sales", json=payload, timeout=20)
    assert r.status_code == 200, r.text

    # Vendor view
    vs, _ = login("vendor")
    r = vs.get(f"{API}/kds/orders", timeout=20)
    assert r.status_code == 200
    tickets = r.json()
    # All returned tickets must be barista merchant only
    other = [t for t in tickets if t.get("merchant_id") != "m-barista"]
    assert not other, f"Vendor saw tickets from other merchants: {other[:2]}"


def test_sec003_vendor_kds_patch_forbidden_for_other_merchant():
    # Find a nasi-uduk ticket via admin
    ads, _ = login("admin")
    r = ads.get(f"{API}/kds/orders", timeout=20)
    assert r.status_code == 200
    others = [t for t in r.json() if t.get("merchant_id") == "m-nasi-uduk"]
    if not others:
        pytest.skip("no cross-merchant tickets to test patch forbidden")
    target_id = others[0]["id"]
    vs, _ = login("vendor")
    r = vs.patch(f"{API}/kds/orders/{target_id}", json={"status": "Selesai"}, timeout=20)
    assert r.status_code == 403, f"expected 403 for cross-merchant patch, got {r.status_code} {r.text}"


def test_sec003_vendor_orders_scoped():
    vs, _ = login("vendor")
    r = vs.get(f"{API}/vendor/orders", timeout=20)
    assert r.status_code == 200
    for order in r.json():
        lines = order.get("lines") or []
        assert any(ln.get("merchant_id") == "m-barista" for ln in lines), \
            f"vendor/orders returned order without barista line: {order.get('id')}"


# -------------------- SEC-004: Expenses & stock-log scoping --------------------

def test_sec004_expenses_scoping_kasir_only_own():
    ks, _ = login("kasir")
    # Ensure shift open
    r = ks.get(f"{API}/shifts/current", timeout=20)
    if not r.json():
        ks.post(f"{API}/shifts/open", json={"opening_cash": 50000, "note": "sec-exp"}, timeout=20)
    tag = f"TEST_SEC004_{uuid.uuid4().hex[:6]}"
    for i in range(2):
        r = ks.post(f"{API}/expenses", json={
            "category": "Operasional", "note": f"{tag}-{i}", "amount": 1000 + i,
            "date": "2026-02-15", "method": "Cash"
        }, timeout=20)
        assert r.status_code == 200, r.text
    r = ks.get(f"{API}/expenses", timeout=20)
    assert r.status_code == 200
    rows = r.json()
    assert all(row.get("user_id") for row in rows), "expenses missing user_id"
    # Every row belongs to this kasir
    me = ks.get(f"{API}/auth/me", timeout=20).json()
    other = [r for r in rows if r.get("user_id") != me["id"]]
    assert not other, f"Kasir sees others' expenses: {len(other)} rows"


def test_sec004_expenses_vendor_forbidden():
    vs, _ = login("vendor")
    r = vs.get(f"{API}/expenses", timeout=20)
    assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"


def test_sec004_stock_logs_kasir_forbidden():
    ks, _ = login("kasir")
    r = ks.get(f"{API}/stock-logs", timeout=20)
    assert r.status_code == 403


def test_sec004_stock_logs_admin_allowed():
    ads, _ = login("admin")
    r = ads.get(f"{API}/stock-logs", timeout=20)
    assert r.status_code == 200


# -------------------- SEC-005: Server-side pricing recompute --------------------

def test_sec005_create_sale_recompute_from_authoritative_prices():
    ks, _ = login("kasir")
    r = ks.get(f"{API}/shifts/current", timeout=20)
    if not r.json():
        ks.post(f"{API}/shifts/open", json={"opening_cash": 100000, "note": "sec-005"}, timeout=20)
    # Tampered payload: price=1, subtotal=2, total=2
    tampered = {
        "table": "SEC-PRICE",
        "lines": [{"product_id": "p-1", "name": "x", "quantity": 2, "price": 1,
                    "merchant_id": "m-barista", "vendor": "Barista Kopi"}],
        "subtotal": 2, "tax": 0, "total": 2,
        "payment_method": "Cash", "cash_received": 100000,
    }
    r = ks.post(f"{API}/sales", json=tampered, timeout=20)
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["subtotal"] == 36000, f"subtotal should be 36000, got {sale['subtotal']}"
    # tax capped at 10%, but computed from subtotal (may be 0 if client sent 0 and 0<=0<=x); accept 0..3600
    assert 0 <= sale["tax"] <= 3600, f"tax not within cap: {sale['tax']}"
    assert sale["total"] == round(sale["subtotal"] + sale["tax"])
    line0 = sale["lines"][0]
    assert line0["price"] == 18000, f"line price not recomputed, got {line0['price']}"
    # change_amount from server total
    assert sale["change_amount"] == max(0, 100000 - sale["total"])


# -------------------- Security headers --------------------

def test_security_headers_on_api_root():
    r = requests.get(f"{API}/", timeout=20)
    assert r.status_code == 200
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert h.get("referrer-policy") == "no-referrer"
    assert "permissions-policy" in h


# -------------------- Regression: login for 4 roles + core lists --------------------

@pytest.mark.parametrize("role_key", list(CREDS.keys()))
def test_regression_login_all_roles(role_key):
    s, r = login(role_key)
    body = r.json()
    assert body.get("role")
    # /auth/me
    r2 = s.get(f"{API}/auth/me", timeout=20)
    assert r2.status_code == 200


def test_regression_core_lists_accessible():
    s, _ = login("admin")
    for path in ("/products", "/merchants", "/outlets"):
        r = s.get(f"{API}{path}", timeout=20)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        assert isinstance(r.json(), list)


def test_regression_shift_open_close_flow():
    # Use a fresh interaction: kasir opens (or already open) → runs report on active shift
    ks, _ = login("kasir")
    r = ks.get(f"{API}/shifts/current", timeout=20)
    if not r.json():
        r = ks.post(f"{API}/shifts/open", json={"opening_cash": 25000, "note": "regr"}, timeout=20)
        assert r.status_code == 200
    r = ks.get(f"{API}/shifts/current", timeout=20)
    assert r.status_code == 200 and r.json()
    shift_id = r.json()["id"]
    rep = ks.get(f"{API}/shifts/{shift_id}/report", timeout=20)
    assert rep.status_code == 200


def test_regression_accept_self_order_by_kasir():
    # Create self-order then accept
    r = requests.post(f"{API}/self-order", json={
        "table": "SEC-SO", "total": 999,
        "lines": [{"product_id": "p-2", "name": "x", "quantity": 1, "price": 1,
                   "merchant_id": "m-barista", "vendor": "Barista Kopi"}],
        "notes": "test", "payment_method": "QRIS", "payment_proof": "img"
    }, timeout=20)
    assert r.status_code == 200
    order_id = r.json()["id"]
    ks, _ = login("kasir")
    if not ks.get(f"{API}/shifts/current", timeout=20).json():
        ks.post(f"{API}/shifts/open", json={"opening_cash": 10000, "note": "self"}, timeout=20)
    r = ks.post(f"{API}/self-order/{order_id}/accept", timeout=20)
    assert r.status_code == 200, r.text
    sale = r.json()
    # Server should recompute total from product prices (p-2 = 15000)
    assert sale["total"] == 15000, f"self-order accept did not recompute: {sale}"
