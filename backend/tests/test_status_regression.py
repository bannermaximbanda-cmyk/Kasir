import requests
from pathlib import Path

BASE_URL = next(
    line.split("=", 1)[1].strip()
    for line in (Path(__file__).parents[2] / "frontend/.env").read_text().splitlines()
    if line.startswith("REACT_APP_BACKEND_URL=")
).rstrip("/")


def test_status_create_and_list():
    payload = {"client_name": "TEST_review_regression"}
    created = requests.post(f"{BASE_URL}/api/status", json=payload, timeout=15)
    assert created.status_code == 200
    body = created.json()
    assert body["client_name"] == payload["client_name"]
    assert isinstance(body["id"], str)

    listed = requests.get(f"{BASE_URL}/api/status", timeout=15)
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] and item["client_name"] == payload["client_name"] for item in listed.json())