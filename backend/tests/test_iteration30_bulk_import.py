"""
Iter30 — Bulk-import hardening tests.

Verifies:
  1. `varian` CSV column ("Panas:18000|Ice:20000") is parsed into Product.variants list
     with correct name+price per entry.
  2. `status_aktif` (1/0) column correctly maps to Product.is_active, taking precedence
     over the legacy `is_active` bool.
  3. New endpoints /api/products/csv-template and /api/products/export are reachable
     and return well-formed CSV with the expected header row.
  4. Cross-merchant SKU collision safety — the same SKU under 2 different merchants
     produces 2 separate products (not silent overwrite).
  5. In-file duplicate detection — 2 rows with identical (name, outlet, merchant)
     without id → first row inserted, subsequent rows flagged as error.
  6. outlet_id="" (blank) preserved as global (NULL) — not silently coerced to a
     default outlet.
"""

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL}/api"
HEADERS_CSRF = {"X-Requested-With": "mjd-kupi", "Content-Type": "application/json"}


def _login(email: str, password: str) -> str:
    last_err = None
    for attempt in range(4):
        try:
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, headers=HEADERS_CSRF, timeout=45)
            if r.status_code in (502, 503, 504):
                last_err = f"{r.status_code} edge error"
                time.sleep(3)
                continue
            assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
            return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            last_err = repr(e)
            if attempt == 3:
                raise
            time.sleep(3)
    raise RuntimeError(f"login retry exhausted: {last_err}")


@pytest.fixture(scope="module")
def sa_token() -> str:
    return _login("superadmin", ".Superadmin1_")


@pytest.fixture(scope="module")
def auth(sa_token):
    return {"Authorization": f"Bearer {sa_token}", **HEADERS_CSRF}


def _find_merchant(auth, name_prefix: str = "") -> str:
    r = requests.get(f"{API}/merchants", headers=auth, timeout=15)
    assert r.status_code == 200
    ms = r.json()
    if name_prefix:
        for m in ms:
            if (m.get("name") or "").lower().startswith(name_prefix.lower()):
                return m["id"]
    return ms[0]["id"]


def test_varian_string_parsed_into_variants(auth):
    merchant_id = _find_merchant(auth)
    sku = f"VARIAN-TEST-{uuid.uuid4().hex[:8]}"
    payload = {
        "outlet_id_explicit": True,
        "mode": "upsert",
        "rows": [{
            "name": f"Kopi Varian {sku}",
            "sku": sku,
            "merchant_id": merchant_id,
            "outlet_id": "outlet-sudirman",
            "price": 20000,
            "cost": 6000,
            "stock": 5,
            "varian": "Panas:20000|Ice:22000|Extra Shot:5000",
            "status_aktif": 1,
        }],
    }
    r = requests.post(f"{API}/products/bulk-import", json=payload, headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1, body
    assert body["errors"] == [], body
    # Fetch product back and verify variants
    plist = requests.get(f"{API}/products?outlet_id=outlet-sudirman", headers=auth, timeout=15).json()
    p = next((x for x in plist if x.get("sku") == sku), None)
    assert p is not None, f"product {sku} not found after import"
    variants = p.get("variants") or []
    assert len(variants) == 3, f"expected 3 variants, got {variants}"
    by_name = {v["name"]: v for v in variants}
    assert by_name["Panas"]["price"] == 20000
    assert by_name["Ice"]["price"] == 22000
    assert by_name["Extra Shot"]["price"] == 5000
    for v in variants:
        assert v.get("active") is True
        assert v.get("id"), "variant must have generated id"


def test_status_aktif_maps_to_is_active(auth):
    merchant_id = _find_merchant(auth)
    sku_active = f"STATUS-1-{uuid.uuid4().hex[:8]}"
    sku_inactive = f"STATUS-0-{uuid.uuid4().hex[:8]}"
    payload = {
        "outlet_id_explicit": True,
        "mode": "upsert",
        "rows": [
            {"name": f"Active {sku_active}", "sku": sku_active, "merchant_id": merchant_id,
             "outlet_id": "outlet-sudirman", "price": 10000, "status_aktif": 1},
            {"name": f"Inactive {sku_inactive}", "sku": sku_inactive, "merchant_id": merchant_id,
             "outlet_id": "outlet-sudirman", "price": 10000, "status_aktif": 0},
        ],
    }
    r = requests.post(f"{API}/products/bulk-import", json=payload, headers=auth, timeout=15)
    assert r.status_code == 200
    plist = requests.get(f"{API}/products?outlet_id=outlet-sudirman&include_inactive=1", headers=auth, timeout=15).json()
    active_p = next(x for x in plist if x.get("sku") == sku_active)
    inactive_p = next(x for x in plist if x.get("sku") == sku_inactive)
    assert active_p["is_active"] is True
    assert inactive_p["is_active"] is False


def test_csv_template_endpoint(auth):
    r = requests.get(f"{API}/products/csv-template", headers=auth, timeout=15)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    body = r.text.lstrip("\ufeff")
    header_line = body.splitlines()[0]
    expected_cols = [
        "id", "nama_produk", "sku", "merchant_name", "kategori",
        "harga_jual", "hpp_modal", "stok_awal", "outlet_id",
        "image_url", "varian", "status_aktif",
    ]
    for col in expected_cols:
        assert col in header_line, f"missing column {col} in template header: {header_line}"
    # Must include the 3 example rows described in the spec
    assert body.count("\n") >= 4


def test_export_endpoint_returns_csv(auth):
    r = requests.get(f"{API}/products/export?outlet_id=outlet-sudirman", headers=auth, timeout=20)
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    body = r.text.lstrip("\ufeff")
    assert body.startswith("id,nama_produk,sku,merchant_name,kategori,harga_jual,hpp_modal,stok_awal,outlet_id,image_url,varian,status_aktif")
    disp = r.headers.get("content-disposition", "")
    assert "export_produk_" in disp


def test_cross_merchant_sku_collision_creates_two_products(auth):
    r = requests.get(f"{API}/merchants", headers=auth, timeout=15).json()
    if len(r) < 2:
        pytest.skip("need at least 2 merchants in preview")
    m1, m2 = r[0]["id"], r[1]["id"]
    tag = uuid.uuid4().hex[:8]
    sku = f"CROSS-M-{tag}"
    payload = {"outlet_id_explicit": True, "mode": "upsert", "rows": [
        {"name": f"Cross Test A {tag}", "sku": sku, "merchant_id": m1, "outlet_id": "outlet-sudirman", "price": 5000},
        {"name": f"Cross Test B {tag}", "sku": sku, "merchant_id": m2, "outlet_id": "outlet-sudirman", "price": 6000},
    ]}
    resp = requests.post(f"{API}/products/bulk-import", json=payload, headers=auth, timeout=15).json()
    assert resp["created"] == 2, resp
    plist = requests.get(f"{API}/products?outlet_id=outlet-sudirman", headers=auth, timeout=15).json()
    hits = [x for x in plist if x.get("sku") == sku]
    assert len(hits) == 2, f"expected 2 products with same SKU across merchants, got {len(hits)}"
    merchants_seen = {x["merchant_id"] for x in hits}
    assert merchants_seen == {m1, m2}


def test_in_file_duplicate_detection(auth):
    merchant_id = _find_merchant(auth)
    tag = uuid.uuid4().hex[:8]
    sku = f"IN-FILE-DUP-{tag}"
    name = f"Dup Alpha {tag}"
    payload = {"outlet_id_explicit": True, "mode": "upsert", "rows": [
        {"name": name, "sku": sku, "merchant_id": merchant_id, "outlet_id": "outlet-sudirman", "price": 5000},
        {"name": name, "sku": sku, "merchant_id": merchant_id, "outlet_id": "outlet-sudirman", "price": 5000},
    ]}
    r = requests.post(f"{API}/products/bulk-import", json=payload, headers=auth, timeout=15).json()
    assert r["created"] == 1, r
    assert len(r["errors"]) == 1, r
    err = r["errors"][0]
    assert err["row"] == 2
    assert "Duplikat" in err["error"]


def test_blank_outlet_id_preserved_as_global(auth):
    merchant_id = _find_merchant(auth)
    sku = f"GLOBAL-PRESERVED-{uuid.uuid4().hex[:8]}"
    payload = {"outlet_id_explicit": True, "mode": "upsert", "rows": [
        {"name": f"Global {sku}", "sku": sku, "merchant_id": merchant_id, "outlet_id": "", "price": 10000},
    ]}
    r = requests.post(f"{API}/products/bulk-import", json=payload, headers=auth, timeout=15).json()
    assert r["created"] == 1, r
    # Global products appear on every outlet — pull from any outlet and confirm outlet_id is NULL/blank.
    plist = requests.get(f"{API}/products?outlet_id=outlet-sudirman", headers=auth, timeout=15).json()
    p = next((x for x in plist if x.get("sku") == sku), None)
    assert p is not None, "global product should appear in outlet-sudirman view"
    assert p.get("outlet_id") in (None, ""), f"expected NULL outlet_id, got {p.get('outlet_id')!r}"
