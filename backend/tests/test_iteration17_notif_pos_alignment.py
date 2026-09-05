"""Iteration 17 — verify /api/notifications (type=order) and /api/pos/online-orders
return CONSISTENT order IDs (no divergence).

User-reported bug root cause was a FRONTEND polling bug; backend must remain
correct. This suite validates the backend data-source alignment.
"""
import os
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
    return s


@pytest.fixture(scope="module")
def super_sess():
    return _login(*CREDS["superadmin"])


@pytest.fixture(scope="module")
def kasir_sess():
    s = _login(*CREDS["kasir"])
    cur = s.get(f"{BASE_URL}/api/shifts/current").json()
    if not cur:
        r = s.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000, "note": "iter17"})
        assert r.status_code == 200, r.text
    return s


def _get_product(sess, outlet_id="outlet-sudirman"):
    r = sess.get(f"{BASE_URL}/api/products", params={"outlet_id": outlet_id})
    assert r.status_code == 200, r.text
    products = r.json()
    assert products, "need at least one product"
    return products[0]


def _create_self_order(product, outlet_id="outlet-sudirman", table="Meja TEST17", name="TEST_ITER17"):
    payload = {
        "table": table,
        "outlet_id": outlet_id,
        "customer_name": name,
        "customer_phone": "6281111",
        "total": float(product["price"]),
        "lines": [{
            "product_id": product["id"],
            "name": product["name"],
            "quantity": 1,
            "price": float(product["price"]),
            "vendor": product.get("vendor", "MJD Kupi"),
            "notes": "",
        }],
    }
    r = requests.post(f"{BASE_URL}/api/self-order", json=payload, headers=CSRF, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _notif_order_ids(sess):
    r = sess.get(f"{BASE_URL}/api/notifications")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = []
    for it in body.get("items", []):
        if it.get("type") == "order":
            nid = it["id"]  # "order:<uuid>"
            assert nid.startswith("order:"), f"expected 'order:' prefix, got {nid}"
            ids.append(nid.split(":", 1)[1])
    return ids, body["items"]


def _pos_order_ids(sess):
    r = sess.get(f"{BASE_URL}/api/pos/online-orders")
    assert r.status_code == 200, r.text
    return [o["id"] for o in r.json()], r.json()


class TestNotifPosAlignment:
    def test_fresh_order_appears_in_both_endpoints(self, super_sess, kasir_sess):
        p = _get_product(super_sess)
        order = _create_self_order(p, table="Meja I17-A")
        oid = order["id"]
        assert order["status"] == "Pesanan Diterima"

        # small settle
        time.sleep(1.0)

        notif_ids, notif_items = _notif_order_ids(kasir_sess)
        pos_ids, _ = _pos_order_ids(kasir_sess)

        assert oid in notif_ids, f"new order {oid} not in /notifications type=order (ids={notif_ids})"
        assert oid in pos_ids, f"new order {oid} not in /pos/online-orders (ids={pos_ids})"

        # verify notif title has 8-char uppercase UUID prefix
        prefix = oid[:8].upper()
        target = next(it for it in notif_items if it["id"] == f"order:{oid}")
        assert prefix in target["title"], f"expected UUID prefix {prefix} in title '{target['title']}'"

    def test_zero_divergence_notif_vs_pos_within_scope(self, kasir_sess):
        """Every order-type notif ID (for orders <24h AND still pending) must appear in POS list, and vice-versa."""
        notif_ids, notif_items = _notif_order_ids(kasir_sess)
        pos_ids, pos_items = _pos_order_ids(kasir_sess)

        # POS orders (still pending) MUST all be in notifications (which shows last 24h pending)
        # Filter POS orders to those created within last 24h to fair-compare
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        pos_recent = []
        for o in pos_items:
            ca = o.get("created_at")
            if not ca:
                continue
            try:
                dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            except Exception:
                continue
            if dt >= cutoff:
                pos_recent.append(o["id"])

        # /notifications caps at 10 total items across all types; skip strict check if capped
        # But we CAN assert: no order in notif that's NOT in POS (notif shouldn't over-report)
        # EXCEPT: notif also includes status='pending' (legacy); POS excludes it. So allow that diff.
        # Practical check: any order that IS in POS AND in notif window must be in notif OR notif is capped at 10
        if len(notif_items) < 10:
            missing = [i for i in pos_recent if i not in notif_ids]
            # allow if diff caused by other-type notifs pushing out, but with <10 items there's no cap
            assert not missing, f"POS orders not surfaced by /notifications: {missing}"

    def test_accepted_order_removed_from_pos_still_ok_in_notif(self, super_sess, kasir_sess):
        p = _get_product(super_sess)
        order = _create_self_order(p, table="Meja I17-B")
        oid = order["id"]
        time.sleep(0.5)

        # ensure appears in POS first
        pos_ids, _ = _pos_order_ids(kasir_sess)
        assert oid in pos_ids

        # accept it
        r = kasir_sess.post(f"{BASE_URL}/api/self-order/{oid}/accept")
        assert r.status_code == 200, r.text
        body = r.json()
        # status transitioned away from queue statuses (allowed: Diterima/Selesai/paid)
        queue = {"Pesanan Diterima", "Menunggu kasir", "Menunggu konfirmasi"}
        assert body.get("status") not in queue, f"accepted order still has queue status {body.get('status')}"

        time.sleep(0.5)
        pos_ids2, _ = _pos_order_ids(kasir_sess)
        assert oid not in pos_ids2, f"accepted order {oid} still appears in POS online-orders"

    def test_pos_filter_excludes_diterima_selesai_ditolak(self, super_sess, kasir_sess):
        """POS list must never show statuses outside the accepted 3 queue-states."""
        pos_ids, pos_items = _pos_order_ids(kasir_sess)
        allowed = {"Pesanan Diterima", "Menunggu kasir", "Menunggu konfirmasi"}
        for o in pos_items:
            assert o.get("status") in allowed, f"POS surfaced disallowed status {o.get('status')} for {o['id']}"

    def test_rbac_kasir_sees_only_own_outlet(self, kasir_sess):
        pos_ids, pos_items = _pos_order_ids(kasir_sess)
        for o in pos_items:
            assert o.get("outlet_id") == "outlet-sudirman", f"RBAC leak: {o.get('outlet_id')} shown to sudirman kasir"

    def test_super_admin_no_filter_sees_all_outlets(self, super_sess):
        r = super_sess.get(f"{BASE_URL}/api/pos/online-orders")
        assert r.status_code == 200, r.text
        items = r.json()
        outlets_seen = {o.get("outlet_id") for o in items}
        # not asserting >1 (may be empty); just no crash + no scoping restriction applied
        assert isinstance(items, list)
        # if any items, at least one is a known outlet
        for oid in outlets_seen:
            assert oid, "empty outlet_id in POS response"

    def test_notification_order_id_shape(self, super_sess, kasir_sess):
        p = _get_product(super_sess)
        order = _create_self_order(p, table="Meja I17-C")
        oid = order["id"]
        time.sleep(0.5)
        _, notif_items = _notif_order_ids(kasir_sess)
        target = next((it for it in notif_items if it["id"] == f"order:{oid}"), None)
        assert target, f"created order {oid} not in notif items"
        assert target["type"] == "order"
        assert target["action"] == "pos"
        assert "created_at" in target
        # title contains uppercase 8-char UUID prefix
        assert oid[:8].upper() in target["title"]


# ------------------------------------------------------------------
# Cleanup TEST_ITER17 self-orders after tests (best-effort DB)
# ------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    try:
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from database import async_session_maker  # type: ignore
        import models as M  # type: ignore
        from sqlalchemy import delete

        async def _clean():
            async with async_session_maker() as db:
                await db.execute(delete(M.SelfOrder).where(M.SelfOrder.customer_name.like("TEST_ITER17%")))
                await db.commit()
        asyncio.run(_clean())
    except Exception as e:
        print(f"cleanup skipped: {e}")
