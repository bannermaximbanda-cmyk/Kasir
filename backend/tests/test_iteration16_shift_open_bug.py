"""Iteration 16 - Shift open bug fix + auth-driven fields."""
import os
import requests
import pytest
from pathlib import Path

def _load_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        env = Path("/app/frontend/.env")
        for line in env.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip()
                break
    return url.rstrip("/")

BASE_URL = _load_url()
HEADERS = {"Content-Type": "application/json", "X-Requested-With": "mjd-kupi"}


@pytest.fixture(scope="module")
def kasir_client():
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "kasir", "password": "MjdKupi#2026"})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def kasir_info(kasir_client):
    r = kasir_client.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()


def _close_if_open(client):
    r = client.get(f"{BASE_URL}/api/shifts/current")
    assert r.status_code == 200
    cur = r.json()
    if cur:
        opening = cur.get("opening_cash", 0)
        rc = client.post(f"{BASE_URL}/api/shifts/close", json={"closing_cash": opening, "note": ""})
        assert rc.status_code in (200, 204), f"Close pre-cleanup failed: {rc.status_code} {rc.text}"


class TestShiftOpenBug:
    def test_00_cleanup_any_open_shift(self, kasir_client):
        _close_if_open(kasir_client)
        r = kasir_client.get(f"{BASE_URL}/api/shifts/current")
        assert r.status_code == 200
        assert r.json() in (None, {}, [])

    def test_01_open_shift_clean_payload_success(self, kasir_client, kasir_info):
        payload = {"opening_cash": 500000, "note": "test"}
        r = kasir_client.post(f"{BASE_URL}/api/shifts/open", json=payload)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        shift = r.json()
        assert "id" in shift
        assert shift.get("opening_cash") == 500000
        assert shift.get("cashier_id") == kasir_info.get("id")
        assert shift.get("outlet_id") == (kasir_info.get("outlet_id") or "outlet-sudirman")
        assert shift.get("status") == "open"

    def test_02_current_returns_open_shift(self, kasir_client, kasir_info):
        r = kasir_client.get(f"{BASE_URL}/api/shifts/current")
        assert r.status_code == 200
        cur = r.json()
        assert cur is not None
        assert cur.get("status") == "open"
        assert cur.get("cashier_id") == kasir_info.get("id")

    def test_03_open_when_already_open_returns_400_aktif(self, kasir_client):
        r = kasir_client.post(f"{BASE_URL}/api/shifts/open", json={"opening_cash": 100000, "note": "dup"})
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "aktif" in detail, f"Expected 'aktif' in detail, got: {detail}"

    def test_04_cannot_spoof_cashier_or_outlet(self, kasir_client, kasir_info):
        # Close existing first
        _close_if_open(kasir_client)
        spoof = {
            "opening_cash": 250000,
            "note": "spoof",
            "cashier_id": "hacker-id",
            "outlet_id": "hacker-outlet",
        }
        r = kasir_client.post(f"{BASE_URL}/api/shifts/open", json=spoof)
        assert r.status_code == 200, r.text
        shift = r.json()
        assert shift.get("cashier_id") == kasir_info.get("id")
        assert shift.get("cashier_id") != "hacker-id"
        assert shift.get("outlet_id") != "hacker-outlet"

    def test_05_close_then_reopen(self, kasir_client):
        # There should be an open shift from previous test
        r = kasir_client.get(f"{BASE_URL}/api/shifts/current")
        cur = r.json()
        assert cur is not None, "Expected an open shift to close"
        rc = kasir_client.post(
            f"{BASE_URL}/api/shifts/close",
            json={"closing_cash": cur.get("opening_cash", 0), "note": ""},
        )
        assert rc.status_code in (200, 204), f"Close failed: {rc.status_code} {rc.text}"

        # Now reopen should succeed
        ro = kasir_client.post(
            f"{BASE_URL}/api/shifts/open", json={"opening_cash": 300000, "note": "reopen"}
        )
        assert ro.status_code == 200, f"Reopen failed: {ro.status_code} {ro.text}"
        assert ro.json().get("status") == "open"

    def test_99_cleanup(self, kasir_client):
        _close_if_open(kasir_client)
