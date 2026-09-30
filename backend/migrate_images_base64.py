#!/usr/bin/env python3
"""
Migrasi gambar Base64 → File URL (WebP).

Scan kolom yang MUNGKIN menyimpan data:image/*;base64,... dan konversi jadi
`/api/uploads/<hash>.webp` yang di-serve dari `backend/uploads/`.

Kolom yang di-scan (sesuai brief iter38):
  - mjd_products.image_url          → scope product (max 600px)
  - mjd_merchants.logo_url          → scope logo    (max 400px)
  - mjd_merchants.banner_url        → scope banner  (max 1200px)
  - mjd_settings.key='self_service:*' → value.banners[] (banner) + logo_url (logo)
                                       + header_image (banner)
  - mjd_settings.key='logo'         → value.logo_data (logo)
  - mjd_settings.key='printer_config' → value.logo_url (logo)
  - mjd_settings.key='qris-image:*' → value.image (banner size; QR is square)

Aturan aman:
  * SKIP entri yang sudah berupa URL (http://, https://, /api/uploads/...) atau kosong.
  * Idempotent: nama file = SHA256 payload → run ulang TIDAK bikin file duplikat.
  * Tulis file lebih dulu, VERIFY on-disk, baru UPDATE DB. Base64 lama tidak
    dihapus sebelum URL baru berhasil di-commit.
  * Setiap kolom di-commit terpisah supaya kegagalan satu baris tidak merusak
    baris lain.
  * --dry-run untuk lihat rencana perubahan tanpa modifikasi DB/file.

Usage:
    python migrate_images_base64.py --dry-run
    python migrate_images_base64.py           # eksekusi migrasi
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import logging
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional

# Ensure we can import backend/*
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from PIL import Image, ImageOps
from sqlalchemy import select, update
from sqlalchemy.orm.attributes import flag_modified

from database import AsyncSessionLocal  # type: ignore  # noqa: E402
import models as M  # type: ignore  # noqa: E402

UPLOAD_DIR = BACKEND_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_SIDE = {"product": 600, "logo": 400, "banner": 1200}
WEBP_QUALITY = 78

# data:image/png;base64,AAAA...
BASE64_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate-images")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_base64_image(value: object) -> bool:
    return isinstance(value, str) and BASE64_RE.match(value) is not None


def is_url(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    v = value.strip()
    return v.startswith(("http://", "https://", "/api/uploads/", "/uploads/"))


def convert_to_webp(b64: str, scope: str) -> tuple[str, bytes]:
    """Decode Base64 image → resize (scope max side) → WebP bytes.
    Returns (filename, webp_bytes). Filename derived from SHA256 for idempotency.
    """
    _, _, payload = b64.partition(",")
    raw = base64.b64decode(payload, validate=False)
    max_side = MAX_SIDE.get(scope, 600)
    img = Image.open(BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    w, h = img.size
    scale = max(w, h)
    if scale > max_side:
        ratio = max_side / scale
        img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    buf = BytesIO()
    img.save(buf, "WEBP", quality=WEBP_QUALITY, method=6)
    webp = buf.getvalue()
    digest = hashlib.sha256(webp).hexdigest()[:32]
    return f"{scope}-{digest}.webp", webp


def persist_webp(fname: str, data: bytes, dry_run: bool) -> str:
    """Write file idempotently. Returns public URL to store in DB."""
    out = UPLOAD_DIR / fname
    if out.exists() and out.stat().st_size == len(data):
        log.debug("reuse existing %s (%d bytes)", fname, out.stat().st_size)
    elif dry_run:
        log.info("[dry-run] would write %s (%d bytes)", fname, len(data))
    else:
        tmp = out.with_suffix(".webp.part")
        tmp.write_bytes(data)
        tmp.replace(out)  # atomic on same-fs POSIX
        # Verify on-disk before returning URL (safety check per brief)
        if not out.exists() or out.stat().st_size != len(data):
            raise RuntimeError(f"verify failed for {fname}")
    return f"/api/uploads/{fname}"


async def migrate_field(
    db,
    label: str,
    current: Optional[str],
    scope: str,
    dry_run: bool,
) -> tuple[bool, Optional[str], str]:
    """Migrate a single scalar image field. Returns (changed, new_url, note).
    changed=False for: empty, already-URL, non-base64.
    """
    if current is None or current == "":
        return False, None, "empty"
    if is_url(current):
        return False, None, "already-url"
    if not is_base64_image(current):
        return False, None, "unrecognized"
    try:
        fname, webp = convert_to_webp(current, scope)
    except Exception as e:  # noqa: BLE001
        log.warning("%s decode failed: %s", label, e)
        return False, None, f"decode-error:{e}"
    url = persist_webp(fname, webp, dry_run)
    return True, url, f"ok:{len(webp)}b"


# ---------------------------------------------------------------------------
# Migrators per table
# ---------------------------------------------------------------------------

async def migrate_products(db, dry_run: bool) -> dict:
    stats = {"scanned": 0, "migrated": 0, "already_url": 0, "empty": 0, "errors": 0, "bytes_before": 0, "bytes_after": 0}
    rows = (await db.execute(select(M.Product))).scalars().all()
    for p in rows:
        stats["scanned"] += 1
        before = len(p.image_url or "")
        changed, url, note = await migrate_field(db, f"product[{p.id}].image_url", p.image_url, "product", dry_run)
        if changed:
            stats["bytes_before"] += before
            new_len = len(url or "")
            stats["bytes_after"] += new_len
            log.info("product %s: %d → %d bytes (%s)", p.name[:40], before, new_len, url)
            if not dry_run:
                p.image_url = url
                await db.commit()
            stats["migrated"] += 1
        else:
            if note == "already-url":
                stats["already_url"] += 1
            elif note == "empty":
                stats["empty"] += 1
            elif note.startswith("decode-error"):
                stats["errors"] += 1
    return stats


async def migrate_merchants(db, dry_run: bool) -> dict:
    stats = {"scanned": 0, "logo_migrated": 0, "banner_migrated": 0, "errors": 0, "bytes_before": 0, "bytes_after": 0}
    rows = (await db.execute(select(M.Merchant))).scalars().all()
    for m in rows:
        stats["scanned"] += 1
        for field, scope in (("logo_url", "logo"), ("banner_url", "banner")):
            current = getattr(m, field, None)
            before = len(current or "")
            changed, url, note = await migrate_field(db, f"merchant[{m.id}].{field}", current, scope, dry_run)
            if changed:
                stats["bytes_before"] += before
                stats["bytes_after"] += len(url or "")
                log.info("merchant %s.%s: %d → %d bytes (%s)", m.name[:40], field, before, len(url or ""), url)
                if not dry_run:
                    setattr(m, field, url)
                    await db.commit()
                stats[f"{scope}_migrated"] += 1
            elif note.startswith("decode-error"):
                stats["errors"] += 1
    return stats


def _migrate_setting_dict(value: dict, plan: dict, dry_run: bool) -> tuple[bool, dict]:
    """Mutate `value` in-place for any base64 image fields we recognize.
    Returns (changed, per-field-notes). Only mutates when file write succeeds.
    """
    changed = False
    notes: dict[str, str] = {}
    if not isinstance(value, dict):
        return False, notes

    # Simple scalar keys → scope
    scalar_map = {
        "logo_url": "logo",
        "logo_data": "logo",
        "header_image": "banner",
        "image": "banner",  # qris-image.image
    }
    for k, scope in scalar_map.items():
        if k in value and is_base64_image(value[k]):
            try:
                fname, webp = convert_to_webp(value[k], scope)
                url = persist_webp(fname, webp, dry_run)
                if not dry_run:
                    value[k] = url  # only after file OK
                notes[k] = f"ok:{len(webp)}b"
                changed = True
            except Exception as e:  # noqa: BLE001
                notes[k] = f"error:{e}"

    # List: banners[]
    if isinstance(value.get("banners"), list):
        new_banners = []
        any_changed = False
        for i, b in enumerate(value["banners"]):
            if is_base64_image(b):
                try:
                    fname, webp = convert_to_webp(b, "banner")
                    url = persist_webp(fname, webp, dry_run)
                    new_banners.append(url)
                    any_changed = True
                    notes[f"banners[{i}]"] = f"ok:{len(webp)}b"
                except Exception as e:  # noqa: BLE001
                    new_banners.append(b)  # keep original, don't lose data
                    notes[f"banners[{i}]"] = f"error:{e}"
            else:
                new_banners.append(b)
        if any_changed:
            if not dry_run:
                value["banners"] = new_banners
            changed = True
    return changed, notes


async def migrate_settings(db, dry_run: bool) -> dict:
    stats = {"scanned": 0, "keys_touched": 0, "fields_migrated": 0, "errors": 0}
    rows = (await db.execute(select(M.Setting))).scalars().all()
    for s in rows:
        stats["scanned"] += 1
        # Only scan keys that plausibly hold images
        key = s.key or ""
        interesting = (
            key == "logo"
            or key == "printer_config"
            or key.startswith("self_service:")
            or key.startswith("qris-image:")
        )
        if not interesting:
            continue
        value = s.value if isinstance(s.value, dict) else {}
        # Make a shallow copy so we don't mutate original before file write ok
        pending = {**value}
        try:
            changed, notes = _migrate_setting_dict(pending, plan={}, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001
            log.warning("settings[%s] failed: %s", key, e)
            stats["errors"] += 1
            continue
        if changed:
            stats["keys_touched"] += 1
            stats["fields_migrated"] += sum(1 for v in notes.values() if v.startswith("ok"))
            log.info("settings[%s] → %s", key, notes)
            if not dry_run:
                s.value = pending
                flag_modified(s, "value")
                await db.commit()
    return stats


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main(dry_run: bool) -> None:
    log.info("=== migrate_images_base64 START (dry_run=%s) ===", dry_run)
    log.info("Upload dir: %s", UPLOAD_DIR)
    async with AsyncSessionLocal() as db:
        prod_stats = await migrate_products(db, dry_run)
        merch_stats = await migrate_merchants(db, dry_run)
        setting_stats = await migrate_settings(db, dry_run)
    log.info("--- products    : %s", prod_stats)
    log.info("--- merchants   : %s", merch_stats)
    log.info("--- settings    : %s", setting_stats)
    saved = prod_stats["bytes_before"] - prod_stats["bytes_after"] \
        + merch_stats["bytes_before"] - merch_stats["bytes_after"]
    log.info("Approx DB bytes freed (products+merchants scalars only): %s bytes", f"{saved:,}")
    log.info("Files on disk in %s: %d", UPLOAD_DIR, len(list(UPLOAD_DIR.glob('*.webp'))))
    log.info("=== migrate_images_base64 DONE ===")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Migrate Base64 image columns → file URLs (WebP).")
    ap.add_argument("--dry-run", action="store_true", help="Preview only, do not write files or DB")
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
