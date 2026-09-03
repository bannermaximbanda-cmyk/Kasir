import os
from pathlib import Path
import requests

BASE_URL = next(
    line.split("=", 1)[1].strip()
    for line in (Path(__file__).parents[2] / "frontend/.env").read_text().splitlines()
    if line.startswith("REACT_APP_BACKEND_URL=")
).rstrip("/")
PASSWORD = "MjdKupi#2026"


def login(email):
    session = requests.Session()
    response = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=20)
    return session, response


def test_all_demo_roles_and_me():
    expected = {
        "superadmin@mjd-kupi.local": "Super Admin",
        "manager@mjd-kupi.local": "Merchant Admin",
        "vendor@mjd-kupi.local": "Vendor",
        "kasir@mjd-kupi.local": "Kasir",
    }
    for email, role in expected.items():
        session, response = login(email)
        assert response.status_code == 200
        assert response.json()["role"] == role
        me = session.get(f"{BASE_URL}/api/auth/me", timeout=20)
        assert me.status_code == 200 and me.json()["role"] == role
        logout = session.post(f"{BASE_URL}/api/auth/logout", timeout=20)
        assert logout.status_code == 200
        assert session.get(f"{BASE_URL}/api/auth/me", timeout=20).status_code == 401


def test_unauthorized_and_role_permissions():
    assert requests.get(f"{BASE_URL}/api/auth/me", timeout=20).status_code == 401
    vendor, response = login("vendor@mjd-kupi.local")
    assert response.status_code == 200
    assert vendor.post(f"{BASE_URL}/api/outlets", json={"name": "TEST forbidden"}, timeout=20).status_code == 403
    assert vendor.get(f"{BASE_URL}/api/vendor/orders", timeout=20).status_code == 200


def test_self_order_vendor_queue_status_and_settlement():
    payload = {
        "table": "Meja TEST",
        "lines": [{"product_id": "1", "name": "TEST Kopi", "quantity": 1, "price": 1000, "vendor": "TEST Vendor"}],
        "total": 1000,
        "notes": "TEST regression",
    }
    created = requests.post(f"{BASE_URL}/api/self-order", json=payload, timeout=20)
    assert created.status_code == 200 and created.json()["table"] == "Meja TEST"
    vendor, login_response = login("vendor@mjd-kupi.local")
    assert login_response.status_code == 200
    orders = vendor.get(f"{BASE_URL}/api/vendor/orders", timeout=20)
    assert orders.status_code == 200
    order = next(item for item in orders.json() if item["table"] == "Meja TEST")
    updated = vendor.patch(f"{BASE_URL}/api/vendor/orders/{order['id']}?status=Diproses", timeout=20)
    assert updated.status_code == 200 and updated.json()["status"] == "Diproses"
    settlement = vendor.get(f"{BASE_URL}/api/vendor/settlement", timeout=20)
    assert settlement.status_code == 200 and settlement.json()["gross"] >= 1000


def test_outlets_and_qris_permissions():
    manager, response = login("manager@mjd-kupi.local")
    assert response.status_code == 200
    outlets = manager.get(f"{BASE_URL}/api/outlets", timeout=20)
    assert outlets.status_code == 200 and len(outlets.json()) >= 2
    qris = manager.post(f"{BASE_URL}/api/settings/qris", json={"outlet_id": outlets.json()[0]["id"], "qris_code": "TEST-QRIS"}, timeout=20)
    assert qris.status_code == 200 and qris.json()["ok"] is True