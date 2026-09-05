"""MJD Kupi FastAPI backend backed by Supabase Postgres."""
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, List, Optional

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware

from database import AsyncSessionLocal, Base, engine, get_db
import models as M

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mjd-kupi")

app = FastAPI(title="MJD Kupi API", version="2.0.0")
api_router = APIRouter(prefix="/api")

# -----------------------------------------------------------------------------
# Schemas (request / response models)
# -----------------------------------------------------------------------------

class LoginInput(BaseModel):
    email: str
    password: str


class MerchantInput(BaseModel):
    id: Optional[str] = None
    name: str
    category: str = "F&B"
    commission_percent: float = 10.0
    commission_scheme: str = "percent"
    commission_fixed: float = 0.0
    phone: str = ""
    color: str = "#ffedd5"
    active: bool = True
    # White-Label branding
    slug: Optional[str] = None
    logo_url: str = ""
    theme_color: str = "#f97316"
    banner_url: str = ""
    receipt_header: str = ""
    receipt_footer: str = ""
    wifi_password: str = ""
    subscription_status: str = "active"
    subscription_expires_at: Optional[str] = None
    features_enabled: Optional[dict] = None


class ProductVariant(BaseModel):
    id: Optional[str] = None
    name: str
    price: float = 0
    cost: float = 0
    active: bool = True


class ProductInput(BaseModel):
    id: Optional[str] = None
    name: str
    category: str = "Lain-lain"
    vendor: str = "MJD Kupi"
    merchant_id: Optional[str] = None
    outlet_id: str = "outlet-sudirman"
    price: float = 0
    cost: float = 0
    stock: int = 0
    color: str = "#ffedd5"
    image_url: str = ""
    modifiers: List[Any] = []
    variants: List[ProductVariant] = []


class StockAdjustment(BaseModel):
    quantity: int
    reason: str = "Restock"
    kind: str = "in"  # in | out | opname
    note: str = ""


class ExpenseInput(BaseModel):
    id: Optional[str] = None
    category: str
    note: str = ""
    amount: float
    date: str
    method: str = "Cash"


class SaleLine(BaseModel):
    product_id: str
    name: str
    quantity: int
    price: float
    vendor: str = "MJD Kupi"
    merchant_id: Optional[str] = None
    variant_id: Optional[str] = None
    variant_name: str = ""
    notes: str = ""


class SaleInput(BaseModel):
    id: Optional[str] = None
    table: str = "Meja 01"
    lines: List[SaleLine]
    subtotal: float
    tax: float = 0
    total: float
    payment_method: str = "Cash"
    payment_reference: str = ""
    cash_received: float = 0
    change_amount: float = 0


class SelfOrderInput(BaseModel):
    table: str
    lines: List[SaleLine]
    total: float
    notes: str = ""
    payment_method: str = ""
    payment_proof: str = ""
    customer_name: str = ""
    customer_phone: str = ""
    outlet_id: str = "outlet-sudirman"


class VoidSaleInput(BaseModel):
    pin: str
    reason: str = ""


class BankAccountInput(BaseModel):
    bank_name: str
    account_number: str
    holder_name: str


class PinGenerateResponse(BaseModel):
    pin: str
    expires_at: str


class OutletInput(BaseModel):
    id: Optional[str] = None
    name: str
    address: str = ""
    phone: str = ""
    active: bool = True


class ShiftOpenInput(BaseModel):
    opening_cash: float
    note: str = ""


class ShiftCloseInput(BaseModel):
    closing_cash: float
    note: str = ""


class SettingInput(BaseModel):
    key: str
    value: Any


class KdsStatusInput(BaseModel):
    status: str  # Diproses | Siap diambil | Selesai


# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------

ROLES = ["Super Admin", "Admin", "Vendor", "Kasir"]
DEMO_USERS = [
    # (email, username, password, role, name)
    ("superadmin@mjd-kupi.local", "superadmin", ".Superadmin1_", "Super Admin", "Raka Owner"),
    ("manager@mjd-kupi.local", "admin", "MjdKupi#2026", "Admin", "Maya Ardianti"),
    ("vendor@mjd-kupi.local", "vendor", "MjdKupi#2026", "Vendor", "Agus Tenant"),
    ("kasir@mjd-kupi.local", "kasir", "MjdKupi#2026", "Kasir", "Dina Kasir"),
]


def public_user(user: M.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username or "",
        "role": user.role,
        "name": user.name,
        "outlet_id": user.outlet_id or "outlet-sudirman",
        "merchant_id": user.merchant_id or "",
    }


def token_for(user: M.User, token_type: str = "access") -> str:
    duration = timedelta(days=7) if token_type == "refresh" else timedelta(hours=8)
    return jwt.encode(
        {"sub": user.id, "type": token_type, "exp": datetime.now(timezone.utc) + duration},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> M.User:
    token = request.cookies.get("access_token")
    if not token and request.headers.get("Authorization", "").startswith("Bearer "):
        token = request.headers["Authorization"][7:]
    if not token:
        raise HTTPException(status_code=401, detail="Login diperlukan")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sesi kedaluwarsa") from exc
    result = await db.execute(select(M.User).where(M.User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Sesi tidak valid")
    return user


def require_roles(*roles: str):
    async def dependency(user: M.User = Depends(current_user)) -> M.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Role tidak memiliki akses")
        return user

    return dependency


# -----------------------------------------------------------------------------
# Serialization helpers
# -----------------------------------------------------------------------------

def to_dict(row, exclude=("password_hash",)) -> dict:
    data = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}
    for k, v in list(data.items()):
        if isinstance(v, datetime):
            data[k] = v.isoformat()
    return data


# -----------------------------------------------------------------------------
# Outlet isolation helper
# -----------------------------------------------------------------------------

def outlet_scope(user: M.User, requested_outlet: Optional[str] = None) -> Optional[str]:
    """Return the outlet_id a user is allowed to query.
    - Super Admin/Admin: may pass ?outlet_id=xxx to filter, or 'all'/None for all.
    - Kasir/Vendor: forced to their own outlet_id (ignore param).
    """
    if user.role in ("Super Admin", "Admin"):
        if not requested_outlet or requested_outlet == "all":
            return None
        return requested_outlet
    return user.outlet_id or "outlet-sudirman"


async def get_tax_config(db: AsyncSession) -> dict:
    """Reads tax_config setting. Returns {enabled: bool, percent: float}. Default OFF/0%."""
    result = await db.execute(select(M.Setting).where(M.Setting.key == "tax_config"))
    row = result.scalar_one_or_none()
    if not row or not row.value:
        return {"enabled": False, "percent": 0.0}
    v = row.value or {}
    return {"enabled": bool(v.get("enabled", False)), "percent": float(v.get("percent", 0) or 0)}


# -----------------------------------------------------------------------------
# Auth routes
# -----------------------------------------------------------------------------

@api_router.get("/")
async def root():
    return {"service": "mjd-kupi", "status": "ok", "db": "supabase"}


@api_router.post("/auth/login")
async def login(payload: LoginInput, response: Response, db: AsyncSession = Depends(get_db)):
    identifier = payload.email.lower().strip()
    # Accept either email or username as identifier
    q = select(M.User).where((M.User.email == identifier) | (M.User.username == identifier))
    result = await db.execute(q)
    user = result.scalar_one_or_none()
    if not user or not bcrypt.checkpw(payload.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Email/username atau password salah")
    if user.active is False:
        raise HTTPException(status_code=403, detail="Akun dinonaktifkan")
    # White-Label: enforce merchant subscription status
    if user.merchant_id and user.role != "Super Admin":
        mres = await db.execute(select(M.Merchant).where(M.Merchant.id == user.merchant_id))
        merchant = mres.scalar_one_or_none()
        if merchant and merchant.subscription_status == "suspended":
            raise HTTPException(status_code=403, detail="Masa Langganan/Kerjasama Toko Telah Berakhir. Silakan Hubungi Platform Owner.")
    access = token_for(user)
    refresh = token_for(user, "refresh")
    # Same-origin deployment (frontend + /api served via ingress) → SameSite=Lax mitigates CSRF.
    cookie_kwargs = dict(httponly=True, secure=True, samesite="lax")
    response.set_cookie("access_token", access, max_age=28800, **cookie_kwargs)
    response.set_cookie("refresh_token", refresh, max_age=604800, **cookie_kwargs)
    return {**public_user(user), "access_token": access}


@api_router.get("/auth/me")
async def me(user: M.User = Depends(current_user)):
    return public_user(user)


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


# -----------------------------------------------------------------------------
# Outlets
# -----------------------------------------------------------------------------

@api_router.get("/outlets")
async def list_outlets(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    result = await db.execute(select(M.Outlet).order_by(M.Outlet.name))
    return [to_dict(o) for o in result.scalars().all()]


@api_router.post("/outlets")
async def create_outlet(
    payload: OutletInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    outlet = M.Outlet(id=payload.id or str(uuid.uuid4()), name=payload.name, address=payload.address, active=payload.active)
    db.add(outlet)
    await db.commit()
    await db.refresh(outlet)
    return to_dict(outlet)


@api_router.put("/outlets/{outlet_id}")
async def update_outlet(
    outlet_id: str,
    payload: OutletInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    result = await db.execute(select(M.Outlet).where(M.Outlet.id == outlet_id))
    outlet = result.scalar_one_or_none()
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet tidak ditemukan")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"id"}).items():
        setattr(outlet, field, value)
    await db.commit()
    await db.refresh(outlet)
    return to_dict(outlet)


@api_router.delete("/outlets/{outlet_id}")
async def delete_outlet(
    outlet_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    result = await db.execute(select(M.Outlet).where(M.Outlet.id == outlet_id))
    outlet = result.scalar_one_or_none()
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet tidak ditemukan")
    await db.delete(outlet)
    await db.commit()
    return {"ok": True}


# ---- User & Security management (Super Admin only) ----

class UserInput(BaseModel):
    email: str
    username: str = ""
    password: str
    role: str
    name: str
    outlet_id: str = "outlet-sudirman"
    active: bool = True


class PasswordResetInput(BaseModel):
    new_password: str


@api_router.get("/admin/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    allow_reveal = os.environ.get("ALLOW_PLAIN_PASSWORD_VIEW", "false").lower() == "true"
    result = await db.execute(select(M.User).order_by(M.User.created_at.desc()))
    users = []
    for u in result.scalars().all():
        users.append({
            "id": u.id,
            "email": u.email,
            "username": u.username or "",
            "role": u.role,
            "name": u.name,
            "outlet_id": u.outlet_id or "",
            # plain_password only exposed when ALLOW_PLAIN_PASSWORD_VIEW=true (business ops flag)
            "plain_password": (u.plain_password or "") if allow_reveal else "",
            "reveal_enabled": allow_reveal,
            "active": u.active if u.active is not None else True,
            "created_at": u.created_at.isoformat() if u.created_at else "",
        })
    logger.info(f"[audit] user_list_read by={user.username or user.email} reveal={allow_reveal} count={len(users)}")
    return users


@api_router.post("/admin/users")
async def create_user(
    payload: UserInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Role harus salah satu dari {ROLES}")
    new_user = M.User(
        email=payload.email.lower().strip(),
        username=(payload.username or payload.email.split("@")[0]).lower().strip(),
        password_hash=bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode(),
        plain_password=payload.password,
        role=payload.role,
        name=payload.name,
        outlet_id=payload.outlet_id,
        active=payload.active,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return public_user(new_user)


@api_router.post("/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    payload: PasswordResetInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    result = await db.execute(select(M.User).where(M.User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    target.password_hash = bcrypt.hashpw(payload.new_password.encode(), bcrypt.gensalt()).decode()
    target.plain_password = payload.new_password
    await db.commit()
    return {"ok": True, "id": user_id}


@api_router.patch("/admin/users/{user_id}/toggle")
async def toggle_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    result = await db.execute(select(M.User).where(M.User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    target.active = not (target.active if target.active is not None else True)
    await db.commit()
    return {"ok": True, "active": target.active}


@api_router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Tidak bisa menghapus akun sendiri")
    result = await db.execute(select(M.User).where(M.User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    await db.delete(target)
    await db.commit()
    return {"ok": True}


# -----------------------------------------------------------------------------
# Merchants
# -----------------------------------------------------------------------------

@api_router.get("/merchants")
async def list_merchants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(M.Merchant).order_by(M.Merchant.name))
    return [to_dict(m) for m in result.scalars().all()]


@api_router.post("/merchants")
async def create_merchant(
    payload: MerchantInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    merchant = M.Merchant(
        id=payload.id or str(uuid.uuid4()),
        name=payload.name,
        category=payload.category,
        commission_percent=payload.commission_percent,
        phone=payload.phone,
        color=payload.color,
        active=payload.active,
        slug=payload.slug,
        logo_url=payload.logo_url,
        theme_color=payload.theme_color,
        banner_url=payload.banner_url,
        receipt_header=payload.receipt_header,
        receipt_footer=payload.receipt_footer,
        wifi_password=payload.wifi_password,
        subscription_status=payload.subscription_status,
        features_enabled=payload.features_enabled or {},
    )
    db.add(merchant)
    await db.commit()
    await db.refresh(merchant)
    return to_dict(merchant)


@api_router.put("/merchants/{merchant_id}")
async def update_merchant(
    merchant_id: str,
    payload: MerchantInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    result = await db.execute(select(M.Merchant).where(M.Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant tidak ditemukan")
    data = payload.model_dump(exclude_unset=True, exclude={"id"})
    # Convert subscription_expires_at ISO string → datetime
    if "subscription_expires_at" in data and data["subscription_expires_at"]:
        try:
            data["subscription_expires_at"] = datetime.fromisoformat(data["subscription_expires_at"].replace("Z", "+00:00"))
        except Exception:
            data["subscription_expires_at"] = None
    if data.get("features_enabled") is None and "features_enabled" in data:
        data["features_enabled"] = {}
    for field, value in data.items():
        setattr(merchant, field, value)
    await db.commit()
    await db.refresh(merchant)
    # Sync product.vendor column when merchant name changes
    await db.execute(
        M.Product.__table__.update()
        .where(M.Product.merchant_id == merchant_id)
        .values(vendor=merchant.name)
    )
    await db.commit()
    return to_dict(merchant)


@api_router.delete("/merchants/{merchant_id}")
async def delete_merchant(
    merchant_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    result = await db.execute(select(M.Merchant).where(M.Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant tidak ditemukan")
    await db.delete(merchant)
    await db.commit()
    return {"ok": True}


# -----------------------------------------------------------------------------
# Products
# -----------------------------------------------------------------------------

@api_router.get("/products")
async def list_products(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    # Public (customer self-order): must specify outlet_id
    # Authed: apply role-based outlet scope
    user = None
    try:
        user = await current_user(request, db) if request else None
    except HTTPException:
        user = None
    stmt = select(M.Product).order_by(M.Product.name)
    if user:
        scope = outlet_scope(user, outlet_id)
        if scope:
            stmt = stmt.where(M.Product.outlet_id == scope)
    else:
        # Anonymous: must specify outlet to prevent full catalog leak
        if not outlet_id:
            raise HTTPException(status_code=400, detail="outlet_id wajib untuk akses publik")
        stmt = stmt.where(M.Product.outlet_id == outlet_id)
    result = await db.execute(stmt)
    return [to_dict(p) for p in result.scalars().all()]


@api_router.post("/products")
async def create_product(
    payload: ProductInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    # Admin can only create products for their own outlet; Super Admin unrestricted
    outlet_id = payload.outlet_id or user.outlet_id or "outlet-sudirman"
    if user.role == "Admin" and outlet_id != (user.outlet_id or "outlet-sudirman"):
        raise HTTPException(status_code=403, detail="Admin hanya boleh produk outletnya sendiri")
    product = M.Product(
        id=payload.id or str(uuid.uuid4()),
        name=payload.name,
        category=payload.category,
        vendor=payload.vendor,
        merchant_id=payload.merchant_id,
        outlet_id=outlet_id,
        price=payload.price,
        cost=payload.cost,
        stock=payload.stock,
        color=payload.color,
        image_url=payload.image_url,
        modifiers=payload.modifiers,
        variants=[{**v.model_dump(), "id": v.id or str(uuid.uuid4())} for v in (payload.variants or [])],
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return to_dict(product)


@api_router.put("/products/{product_id}")
async def update_product(
    product_id: str,
    payload: ProductInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    result = await db.execute(select(M.Product).where(M.Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    data = payload.model_dump(exclude_unset=True, exclude={"id"})
    # Normalize variants ids
    if "variants" in data and data["variants"] is not None:
        data["variants"] = [{**v, "id": v.get("id") or str(uuid.uuid4())} for v in data["variants"]]
    for field, value in data.items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return to_dict(product)


@api_router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    result = await db.execute(select(M.Product).where(M.Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    await db.delete(product)
    await db.commit()
    return {"ok": True}


@api_router.patch("/products/{product_id}/stock")
async def adjust_stock(
    product_id: str,
    payload: StockAdjustment,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    result = await db.execute(select(M.Product).where(M.Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    # Outlet isolation: non-super admin can only adjust products of their outlet
    if user.role != "Super Admin" and product.outlet_id and product.outlet_id != user.outlet_id:
        raise HTTPException(status_code=403, detail="Produk bukan milik outlet Anda")
    stock_before = int(product.stock or 0)
    if payload.kind == "opname":
        product.stock = max(0, payload.quantity)
        delta = product.stock - stock_before
    else:
        product.stock = max(0, stock_before + payload.quantity)
        delta = product.stock - stock_before
    stock_after = int(product.stock or 0)
    outlet_id_final = product.outlet_id or user.outlet_id or "outlet-sudirman"
    log = M.StockLog(
        product_id=product_id,
        outlet_id=outlet_id_final,
        quantity=payload.quantity,
        reason=payload.reason,
        kind=payload.kind,
        note=payload.note,
        user_id=user.id,
        user_name=user.name,
    )
    db.add(log)
    # Batch C: Advanced Inventory audit trail
    db.add(M.StockMovement(
        product_id=product_id,
        outlet_id=outlet_id_final,
        kind=payload.kind,  # in | out | opname
        delta=delta,
        stock_before=stock_before,
        stock_after=stock_after,
        reason=payload.reason or ("Opname" if payload.kind == "opname" else "Adjust"),
        operator_id=user.id,
        operator_name=user.name,
        ref_id="",
    ))
    await db.commit()
    await db.refresh(product)
    return to_dict(product)


@api_router.get("/stock-logs")
async def stock_logs(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Admin", "Super Admin")),
):
    scope = outlet_scope(user, outlet_id)
    stmt = select(M.StockLog).order_by(M.StockLog.created_at.desc()).limit(500)
    if scope:
        stmt = stmt.where(M.StockLog.outlet_id == scope)
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


# -----------------------------------------------------------------------------
# Expenses
# -----------------------------------------------------------------------------

@api_router.get("/expenses")
async def list_expenses(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    stmt = select(M.Expense).order_by(M.Expense.date.desc())
    if user.role == "Kasir":
        stmt = stmt.where(M.Expense.user_id == user.id)
    elif user.role == "Vendor":
        raise HTTPException(status_code=403, detail="Vendor tidak berhak melihat pengeluaran")
    else:
        scope = outlet_scope(user, outlet_id)
        if scope:
            stmt = stmt.where(M.Expense.outlet_id == scope)
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


@api_router.post("/expenses")
async def create_expense(
    payload: ExpenseInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    # Auto-bind kasir/admin session to prevent forgery
    shift_id = None
    if user.role == "Kasir":
        r = await db.execute(select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open"))
        s = r.scalar_one_or_none()
        if s:
            shift_id = s.id
    expense = M.Expense(
        id=payload.id or str(uuid.uuid4()),
        category=payload.category,
        note=payload.note,
        amount=payload.amount,
        date=payload.date,
        method=payload.method,
        outlet_id=user.outlet_id or "outlet-sudirman",
        user_id=user.id,
        user_name=user.name,
        shift_id=shift_id,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return to_dict(expense)


# -----------------------------------------------------------------------------
# Kitchen (KDS) helpers
# -----------------------------------------------------------------------------

async def create_kitchen_tickets(
    db: AsyncSession, source_id: str, source_type: str, table_no: str, lines: List[dict], outlet_id: str = "outlet-sudirman",
):
    """Split order lines by merchant / vendor and create kitchen tickets."""
    buckets: dict[str, dict] = {}
    for ln in lines:
        key = ln.get("merchant_id") or ln.get("vendor") or "mjd"
        bucket = buckets.setdefault(
            key,
            {"merchant_id": ln.get("merchant_id"), "merchant_name": ln.get("vendor", "MJD Kupi"), "lines": []},
        )
        bucket["lines"].append(ln)
    for bucket in buckets.values():
        ticket = M.KitchenOrder(
            source_id=source_id,
            source_type=source_type,
            table_no=table_no,
            outlet_id=outlet_id,
            merchant_id=bucket["merchant_id"],
            merchant_name=bucket["merchant_name"],
            lines=bucket["lines"],
        )
        db.add(ticket)
    await db.commit()


# -----------------------------------------------------------------------------
# Sales (POS)
# -----------------------------------------------------------------------------

@api_router.post("/sales")
async def create_sale(
    payload: SaleInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    # Enforce open shift for kasir
    shift_id = None
    if user.role == "Kasir":
        result = await db.execute(
            select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
        )
        shift = result.scalar_one_or_none()
        if not shift:
            raise HTTPException(status_code=400, detail="Buka shift terlebih dahulu sebelum bertransaksi")
        shift_id = shift.id

    # SEC-005: recompute totals & tax server-side from authoritative product prices & tax_config.
    tax_config = await get_tax_config(db)
    verified_lines: list[dict] = []
    subtotal = 0.0
    for line in payload.lines:
        pr = await db.execute(select(M.Product).where(M.Product.id == line.product_id))
        product = pr.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=400, detail=f"Produk {line.product_id} tidak ditemukan")
        qty = max(1, int(line.quantity or 0))
        # If variant selected, use variant price; else use product price
        variant_name = ""
        variant_id = line.variant_id or None
        price = float(product.price)
        if variant_id and product.variants:
            variant = next((v for v in product.variants if v.get("id") == variant_id and v.get("active", True)), None)
            if not variant:
                raise HTTPException(status_code=400, detail=f"Varian tidak valid untuk {product.name}")
            price = float(variant.get("price", product.price))
            variant_name = variant.get("name", "")
        subtotal += price * qty
        verified_lines.append({
            "product_id": product.id,
            "name": product.name,
            "quantity": qty,
            "price": price,
            "vendor": product.vendor,
            "merchant_id": product.merchant_id,
            "variant_id": variant_id,
            "variant_name": variant_name,
            "notes": (line.notes or "")[:200],
        })
    # Server-authoritative tax based on tax_config setting (Feature #7.3)
    if tax_config["enabled"] and tax_config["percent"] > 0:
        tax = round(subtotal * (tax_config["percent"] / 100.0))
    else:
        tax = 0
    total = round(subtotal + tax)

    sale = M.Sale(
        id=payload.id or str(uuid.uuid4()),
        table_no=payload.table,
        subtotal=subtotal,
        tax=tax,
        total=total,
        payment_method=payload.payment_method,
        payment_reference=payload.payment_reference,
        cash_received=payload.cash_received,
        change_amount=max(0, float(payload.cash_received or 0) - total),
        outlet_id=user.outlet_id or "outlet-sudirman",
        cashier_id=user.id,
        shift_id=shift_id,
        lines=verified_lines,
    )
    db.add(sale)
    # Deduct stock + write StockMovement (Batch C audit trail)
    for line in verified_lines:
        r = await db.execute(select(M.Product).where(M.Product.id == line["product_id"]))
        product = r.scalar_one_or_none()
        if product:
            stock_before = int(product.stock or 0)
            product.stock = max(0, stock_before - int(line["quantity"]))
            stock_after = int(product.stock or 0)
            db.add(M.StockMovement(
                product_id=product.id,
                outlet_id=product.outlet_id or sale.outlet_id,
                kind="sale",
                delta=stock_after - stock_before,
                stock_before=stock_before,
                stock_after=stock_after,
                reason=f"Penjualan {sale.table_no}",
                operator_id=user.id,
                operator_name=user.name,
                ref_id=sale.id,
            ))
    await db.commit()
    await db.refresh(sale)
    # Kitchen tickets split per merchant
    await create_kitchen_tickets(db, sale.id, "sale", sale.table_no, verified_lines, outlet_id=sale.outlet_id)
    return to_dict(sale)


@api_router.get("/sales")
async def list_sales(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    stmt = select(M.Sale).order_by(M.Sale.created_at.desc()).limit(500)
    # Isolation: Kasir hanya melihat transaksi shift aktifnya sendiri
    if user.role == "Kasir":
        active = await db.execute(
            select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
        )
        shift = active.scalar_one_or_none()
        if shift:
            stmt = select(M.Sale).where(M.Sale.shift_id == shift.id).order_by(M.Sale.created_at.desc())
        else:
            return []
    else:
        scope = outlet_scope(user, outlet_id)
        if scope:
            stmt = stmt.where(M.Sale.outlet_id == scope)
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

@api_router.get("/dashboard")
async def dashboard_summary(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    scope = outlet_scope(user, outlet_id)
    sales_stmt = select(func.coalesce(func.sum(M.Sale.total), 0)).where(M.Sale.status != "voided")
    trx_stmt = select(func.count(M.Sale.id)).where(M.Sale.status != "voided")
    exp_stmt = select(func.coalesce(func.sum(M.Expense.amount), 0))
    if scope:
        sales_stmt = sales_stmt.where(M.Sale.outlet_id == scope)
        trx_stmt = trx_stmt.where(M.Sale.outlet_id == scope)
        exp_stmt = exp_stmt.where(M.Expense.outlet_id == scope)
    sales_total = (await db.execute(sales_stmt)).scalar_one()
    trx_count = (await db.execute(trx_stmt)).scalar_one()
    expenses_total = (await db.execute(exp_stmt)).scalar_one()
    return {
        "sales_total": float(sales_total or 0),
        "expense_total": float(expenses_total or 0),
        "transaction_count": int(trx_count or 0),
        "net_profit": float(sales_total or 0) - float(expenses_total or 0),
        "outlet_scope": scope or "all",
    }


@api_router.get("/notifications")
async def get_notifications(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    """Aggregate real-time alerts: low stock, recent shift events, pending self-orders."""
    scope = outlet_scope(user, outlet_id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    items = []
    # Low stock
    ls_stmt = select(M.Product).where(M.Product.stock <= 5)
    if scope: ls_stmt = ls_stmt.where(M.Product.outlet_id == scope)
    ls = (await db.execute(ls_stmt.order_by(M.Product.stock).limit(10))).scalars().all()
    for p in ls:
        items.append({
            "id": f"stock:{p.id}",
            "type": "stock",
            "severity": "critical" if p.stock == 0 else "warning",
            "title": f"Stok {p.name} tersisa {int(p.stock or 0)}",
            "detail": f"Outlet {p.outlet_id.replace('outlet-', '').title()} · minimum 5 porsi",
            "created_at": now.isoformat(),
            "action": "inventory",
        })
    # Recent shift events (closed shifts last 24h)
    sh_stmt = select(M.Shift).where(M.Shift.closed_at.isnot(None), M.Shift.closed_at >= since)
    if scope: sh_stmt = sh_stmt.where(M.Shift.outlet_id == scope)
    shifts = (await db.execute(sh_stmt.order_by(M.Shift.closed_at.desc()).limit(5))).scalars().all()
    for s in shifts:
        variance = (s.closing_cash or 0) - ((s.opening_cash or 0) + (s.expected_cash or 0))
        items.append({
            "id": f"shift:{s.id}",
            "type": "shift",
            "severity": "info" if abs(variance) < 10000 else "warning",
            "title": f"Kasir {s.cashier_name or 'Kasir'} melakukan Closing",
            "detail": f"Selisih: {'Rp ' + f'{variance:,.0f}'.replace(',', '.') if variance else 'Rp 0'} · {s.outlet_id.replace('outlet-', '').title()}",
            "created_at": s.closed_at.isoformat() if s.closed_at else now.isoformat(),
            "action": "cashiers",
        })
    # Pending self-orders (last 24h, not yet accepted)
    so_stmt = select(M.SelfOrder).where(M.SelfOrder.status.in_(PENDING_SELF_ORDER_STATUSES), M.SelfOrder.created_at >= since)
    if scope: so_stmt = so_stmt.where(M.SelfOrder.outlet_id == scope)
    orders = (await db.execute(so_stmt.order_by(M.SelfOrder.created_at.desc()).limit(10))).scalars().all()
    for o in orders:
        items.append({
            "id": f"order:{o.id}",
            "type": "order",
            "severity": "info",
            "title": f"Pesanan Baru #{str(o.id)[:8].upper()} dari QR {o.table_no}",
            "detail": f"{o.customer_name or 'Pelanggan'} · Rp {(o.total or 0):,.0f}".replace(",", "."),
            "created_at": o.created_at.isoformat() if o.created_at else now.isoformat(),
            "action": "pos",
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    items = items[:10]
    return {"items": items, "unread_count": len(items)}


# Shared constant: all statuses that represent an ACTIVE pending self-order queue.
# Used by both /notifications (type=order) and /pos/online-orders to guarantee zero divergence.
PENDING_SELF_ORDER_STATUSES = ["Pesanan Diterima", "Menunggu kasir", "Menunggu konfirmasi", "pending", "pending_cashier_approval"]


@api_router.get("/dashboard/analytics")
async def dashboard_analytics(
    outlet_id: Optional[str] = None,
    mode: str = "daily",  # daily | hourly
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    """Comprehensive analytics: KPI comparisons, sales trend, payment breakdown, top products, low stock, outlet compare.

    Optimized: fetches sales in a single query then aggregates in Python (was 20+ round-trips).
    """
    scope = outlet_scope(user, outlet_id)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yday = today - timedelta(days=1)
    last_week_start = today - timedelta(days=7)
    thirty = today - timedelta(days=30)

    # Single query: fetch last 30 days of paid sales (limit for safety)
    sales_stmt = select(M.Sale).where(M.Sale.status != "voided", M.Sale.created_at >= thirty)
    if scope:
        sales_stmt = sales_stmt.where(M.Sale.outlet_id == scope)
    sales_rows = (await db.execute(sales_stmt.order_by(M.Sale.created_at.desc()).limit(5000))).scalars().all()

    def in_range(dt, since, until=None):
        if dt is None: return False
        if dt < since: return False
        if until is not None and dt >= until: return False
        return True

    # KPI totals
    today_sales = sum(float(s.total or 0) for s in sales_rows if in_range(s.created_at, today))
    yday_sales = sum(float(s.total or 0) for s in sales_rows if in_range(s.created_at, yday, today))
    today_trx = sum(1 for s in sales_rows if in_range(s.created_at, today))

    # Bounded expenses (this week)
    exp_stmt = select(func.coalesce(func.sum(M.Expense.amount), 0)).where(M.Expense.date >= last_week_start.strftime("%Y-%m-%d"))
    if scope: exp_stmt = exp_stmt.where(M.Expense.outlet_id == scope)
    week_expense = (await db.execute(exp_stmt)).scalar_one() or 0

    # Trend
    trend = []
    if mode == "hourly":
        buckets = {h: {"gross": 0.0, "count": 0} for h in range(24)}
        for s in sales_rows:
            if not in_range(s.created_at, today): continue
            h = s.created_at.hour
            buckets[h]["gross"] += float(s.total or 0)
            buckets[h]["count"] += 1
        for h in range(24):
            trend.append({"label": f"{h:02d}:00", "gross": buckets[h]["gross"], "count": buckets[h]["count"]})
    else:
        seven_start = today - timedelta(days=6)
        buckets = {i: {"gross": 0.0, "count": 0} for i in range(7)}
        for s in sales_rows:
            if not in_range(s.created_at, seven_start, today + timedelta(days=1)): continue
            day_i = (s.created_at.date() - seven_start.date()).days
            if 0 <= day_i < 7:
                buckets[day_i]["gross"] += float(s.total or 0)
                buckets[day_i]["count"] += 1
        for i in range(7):
            d = seven_start + timedelta(days=i)
            trend.append({"label": d.strftime("%a %d"), "gross": buckets[i]["gross"], "count": buckets[i]["count"]})

    # Payment breakdown
    pm_agg: dict = {}
    for s in sales_rows:
        m = s.payment_method or "Lainnya"
        if m not in pm_agg: pm_agg[m] = {"method": m, "total": 0.0, "count": 0}
        pm_agg[m]["total"] += float(s.total or 0)
        pm_agg[m]["count"] += 1
    payment_breakdown = list(pm_agg.values())

    # Top products
    prod_counter: dict = {}
    for s in sales_rows:
        for ln in (s.lines or []):
            pid = ln.get("product_id"); name = ln.get("name")
            if not pid: continue
            if pid not in prod_counter:
                prod_counter[pid] = {"product_id": pid, "name": name, "quantity": 0, "revenue": 0.0}
            prod_counter[pid]["quantity"] += int(ln.get("quantity") or 0)
            prod_counter[pid]["revenue"] += float(ln.get("price") or 0) * int(ln.get("quantity") or 0)
    top_products = sorted(prod_counter.values(), key=lambda x: x["quantity"], reverse=True)[:5]

    # Outlet compare (only for consolidated)
    outlet_compare = []
    if not scope:
        outlet_agg: dict = {}
        for s in sales_rows:
            oid = s.outlet_id or "-"
            if oid not in outlet_agg: outlet_agg[oid] = {"outlet_id": oid, "gross": 0.0, "count": 0}
            outlet_agg[oid]["gross"] += float(s.total or 0)
            outlet_agg[oid]["count"] += 1
        # attach names
        outlets_res = (await db.execute(select(M.Outlet))).scalars().all()
        name_map = {o.id: o.name for o in outlets_res}
        for oid, agg in outlet_agg.items():
            outlet_compare.append({"outlet_id": oid, "name": name_map.get(oid, oid), "gross": agg["gross"], "count": agg["count"]})

    # Low stock
    ls_stmt = select(M.Product).where(M.Product.stock <= 5)
    if scope: ls_stmt = ls_stmt.where(M.Product.outlet_id == scope)
    ls_rows = (await db.execute(ls_stmt.order_by(M.Product.stock).limit(10))).scalars().all()
    low_stock = [{"id": p.id, "name": p.name, "stock": int(p.stock or 0), "vendor": p.vendor, "outlet_id": p.outlet_id, "min": 5} for p in ls_rows]

    avg_basket = (float(today_sales) / today_trx) if today_trx else 0
    growth = ((float(today_sales) - float(yday_sales)) / float(yday_sales) * 100) if yday_sales else (100.0 if today_sales else 0.0)
    return {
        "kpi": {
            "sales_today": float(today_sales),
            "sales_yesterday": float(yday_sales),
            "sales_growth_percent": round(growth, 1),
            "transactions_today": int(today_trx),
            "avg_basket": round(avg_basket),
            "expenses_total": float(week_expense),
            "net_profit": float(today_sales) - float(week_expense),
        },
        "trend": trend,
        "mode": mode,
        "payment_breakdown": payment_breakdown,
        "top_products": top_products,
        "low_stock": low_stock,
        "outlet_compare": outlet_compare,
        "outlet_scope": scope or "all",
    }


# -----------------------------------------------------------------------------
# Self-order & Vendor / KDS
# -----------------------------------------------------------------------------

@api_router.post("/self-order")
async def create_self_order(payload: SelfOrderInput, db: AsyncSession = Depends(get_db)):
    if not payload.customer_name:
        raise HTTPException(status_code=400, detail="Nama pelanggan wajib diisi")
    # Check if any cashier has an open shift at this outlet
    active_shift = await db.execute(
        select(M.Shift).where(M.Shift.status == "open", M.Shift.outlet_id == payload.outlet_id)
    )
    if not active_shift.scalar_one_or_none():
        raise HTTPException(status_code=423, detail="Toko sedang tutup - belum ada kasir buka shift")
    order = M.SelfOrder(
        id=str(uuid.uuid4()),
        table_no=payload.table,
        outlet_id=payload.outlet_id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        total=payload.total,
        notes=payload.notes,
        lines=[ln.model_dump() for ln in payload.lines],
        payment_method=payload.payment_method,
        payment_proof=payload.payment_proof,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return to_dict(order)


@api_router.get("/self-order/{order_id}/status")
async def self_order_status(order_id: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint for customer to poll their order status."""
    result = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    return {
        "id": order.id,
        "status": order.status,
        "table_no": order.table_no,
        "customer_name": order.customer_name,
        "total": order.total,
        "created_at": order.created_at.isoformat() if order.created_at else "",
    }


@api_router.get("/outlets/{outlet_id}/shift-status")
async def outlet_shift_status(outlet_id: str, db: AsyncSession = Depends(get_db)):
    """Public: is the store open (any kasir shift active) at this outlet?"""
    r = await db.execute(
        select(M.Shift).where(M.Shift.status == "open", M.Shift.outlet_id == outlet_id)
    )
    shift = r.scalar_one_or_none()
    return {"outlet_id": outlet_id, "open": bool(shift), "cashier_name": shift.cashier_name if shift else ""}


# -----------------------------------------------------------------------------
# Self-Service Management (per outlet): banners, marquee, store status override
# -----------------------------------------------------------------------------

class SelfServiceSettingsInput(BaseModel):
    banners: List[str] = []  # data URLs / http URLs
    marquee_text: str = ""
    logo_url: str = ""
    header_image: str = ""
    force_closed: bool = False  # admin override: force close regardless of shift
    closed_message: str = ""


@api_router.get("/outlets/{outlet_id}/self-service")
async def get_self_service_settings(outlet_id: str, db: AsyncSession = Depends(get_db)):
    """Public: settings displayed on the customer /self-order page for this outlet."""
    key = f"self_service:{outlet_id}"
    result = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = result.scalar_one_or_none()
    v = (row.value or {}) if row else {}
    return {
        "outlet_id": outlet_id,
        "banners": v.get("banners", []),
        "marquee_text": v.get("marquee_text", ""),
        "logo_url": v.get("logo_url", ""),
        "header_image": v.get("header_image", ""),
        "force_closed": bool(v.get("force_closed", False)),
        "closed_message": v.get("closed_message", ""),
    }


@api_router.post("/outlets/{outlet_id}/self-service")
async def save_self_service_settings(
    outlet_id: str,
    payload: SelfServiceSettingsInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    key = f"self_service:{outlet_id}"
    result = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = result.scalar_one_or_none()
    value = payload.model_dump()
    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(M.Setting(key=key, value=value))
    await db.commit()
    return {"ok": True, "outlet_id": outlet_id, **value}


# Public outlets listing (for customer self-order to switch)
@api_router.get("/public/outlets")
async def public_outlets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(M.Outlet).where(M.Outlet.active == True).order_by(M.Outlet.name))
    return [{"id": o.id, "name": o.name, "address": o.address} for o in result.scalars().all()]


class RejectReasonInput(BaseModel):
    reason: str = ""


@api_router.post("/self-order/{order_id}/reject")
async def reject_self_order(
    order_id: str,
    payload: RejectReasonInput = RejectReasonInput(),
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Admin", "Super Admin")),
):
    """Kasir menolak pesanan online — atomic transition ke 'Ditolak' (dupe-safe)."""
    reason = (payload.reason or "").strip() if payload else ""
    reject_note = f" [Ditolak: {reason or 'tanpa alasan'}]"
    # Atomic — only orders NOT yet finalized can be rejected
    upd = await db.execute(
        M.SelfOrder.__table__.update()
        .where(M.SelfOrder.id == order_id)
        .where(M.SelfOrder.status.notin_(["Ditolak", "Selesai", "Diterima", "Diproses", "processing"]))
        .values(status="Ditolak", notes=(M.SelfOrder.notes.op("||")(reject_note)))
    )
    await db.commit()
    if upd.rowcount == 0:
        r = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
        existing = r.scalar_one_or_none()
        if not existing:
            raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
        raise HTTPException(status_code=409, detail=f"Pesanan sudah {existing.status} (double-click terblokir)")
    return {"ok": True, "id": order_id, "status": "Ditolak"}


@api_router.post("/self-order/{order_id}/accept")
async def accept_self_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Admin", "Super Admin")),
):
    """Kasir menyetujui pesanan online: buat sale, kurangi stok, buat KDS tickets.

    ATOMIC GUARD (Feb 2026): pakai UPDATE ... WHERE status IN pending-set → transitional 'processing'.
    Jika 0 rows affected, request kedua/dupe langsung 409 Conflict tanpa duplikasi Sale.
    """
    # Atomic status transition: pending → processing (only 1 request wins)
    upd = await db.execute(
        M.SelfOrder.__table__.update()
        .where(M.SelfOrder.id == order_id)
        .where(M.SelfOrder.status.in_(["Menunggu kasir", "Menunggu konfirmasi", "Pesanan Diterima"]))
        .values(status="processing")
    )
    await db.commit()
    if upd.rowcount == 0:
        # Either not found OR already processed by concurrent request
        r = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
        existing = r.scalar_one_or_none()
        if not existing:
            raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
        raise HTTPException(status_code=409, detail=f"Pesanan sudah {existing.status} (double-click terblokir)")
    # Now we own the lock — reload the order
    result = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")

    shift_id = None
    if user.role == "Kasir":
        active = await db.execute(
            select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
        )
        shift = active.scalar_one_or_none()
        if not shift:
            # Rollback the lock so kasir can retry after opening shift
            order.status = "Pesanan Diterima"
            await db.commit()
            raise HTTPException(status_code=400, detail="Buka shift terlebih dahulu")
        shift_id = shift.id

    subtotal = 0.0
    verified_lines: list[dict] = []
    for line in (order.lines or []):
        pr = await db.execute(select(M.Product).where(M.Product.id == line.get("product_id")))
        product = pr.scalar_one_or_none()
        if not product:
            continue
        qty = max(1, int(line.get("quantity") or 0))
        variant_id = line.get("variant_id")
        variant_name = ""
        price = float(product.price)
        if variant_id and product.variants:
            variant = next((v for v in product.variants if v.get("id") == variant_id and v.get("active", True)), None)
            if variant:
                price = float(variant.get("price", product.price))
                variant_name = variant.get("name", "")
        subtotal += price * qty
        verified_lines.append({
            "product_id": product.id,
            "name": product.name,
            "quantity": qty,
            "price": price,
            "vendor": product.vendor,
            "merchant_id": product.merchant_id,
            "variant_id": variant_id,
            "variant_name": variant_name,
            "notes": (line.get("notes") or "")[:200],
        })
    sale = M.Sale(
        id=str(uuid.uuid4()),
        table_no=order.table_no,
        subtotal=subtotal,
        tax=0,
        total=subtotal,
        payment_method=order.payment_method or "QRIS",
        payment_reference=(order.payment_proof or "")[:120],
        outlet_id=user.outlet_id or "outlet-sudirman",
        cashier_id=user.id,
        shift_id=shift_id,
        lines=verified_lines,
    )
    db.add(sale)
    for line in verified_lines:
        r = await db.execute(select(M.Product).where(M.Product.id == line["product_id"]))
        product = r.scalar_one_or_none()
        if product:
            product.stock = max(0, int(product.stock or 0) - int(line["quantity"]))
    order.status = "Diproses"
    await db.commit()
    await db.refresh(sale)
    await create_kitchen_tickets(db, sale.id, "sale", sale.table_no, verified_lines, outlet_id=sale.outlet_id)
    return to_dict(sale)


@api_router.get("/vendor/orders")
async def vendor_orders(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Admin", "Super Admin")),
):
    stmt = select(M.SelfOrder).order_by(M.SelfOrder.created_at.desc()).limit(200)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if user.role == "Vendor" and user.merchant_id:
        # Only expose orders that contain at least one line for this vendor's merchant
        rows = [r for r in rows if any(
            (ln.get("merchant_id") or "") == user.merchant_id for ln in (r.lines or [])
        )]
    return [to_dict(row) for row in rows]


@api_router.patch("/vendor/orders/{order_id}")
async def update_vendor_order(
    order_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Admin", "Super Admin")),
):
    result = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    # SEC-003: vendor can only touch orders that involve their merchant
    if user.role == "Vendor" and user.merchant_id:
        owns = any((ln.get("merchant_id") or "") == user.merchant_id for ln in (order.lines or []))
        if not owns:
            raise HTTPException(status_code=403, detail="Bukan order merchant Anda")
    order.status = status
    await db.commit()
    return {"id": order_id, "status": status}


@api_router.get("/vendor/settlement")
async def vendor_settlement(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Admin", "Super Admin")),
):
    total = (await db.execute(select(func.coalesce(func.sum(M.SelfOrder.total), 0)))).scalar_one()
    sales_total = (await db.execute(select(func.coalesce(func.sum(M.Sale.total), 0)))).scalar_one()
    gross = float((total or 0) + (sales_total or 0))
    commission = round(gross * 0.1)
    return {
        "gross": gross,
        "commission": commission,
        "net": gross - commission,
        "payout_status": "Siap dicairkan" if gross > 0 else "Belum ada omset",
    }


# -----------------------------------------------------------------------------
# Batch C — Advanced Inventory (Stock Movements) & Vendor Settlement Ledger
# -----------------------------------------------------------------------------

class ManualStockMovementInput(BaseModel):
    product_id: str
    kind: str = "adjust"  # in | out | opname | adjust
    delta: int = 0        # positive or negative for in/out/adjust; ignored for opname
    target_stock: Optional[int] = None  # required when kind=opname
    reason: str = "Adjust"
    ref_id: str = ""


@api_router.get("/inventory/stock-movements")
async def list_stock_movements(
    outlet_id: Optional[str] = None,
    product_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Admin", "Super Admin")),
):
    scope = outlet_scope(user, outlet_id)
    stmt = select(M.StockMovement).order_by(M.StockMovement.created_at.desc()).limit(min(limit, 500))
    if scope:
        stmt = stmt.where(M.StockMovement.outlet_id == scope)
    if product_id:
        stmt = stmt.where(M.StockMovement.product_id == product_id)
    if kind:
        stmt = stmt.where(M.StockMovement.kind == kind)
    rows = (await db.execute(stmt)).scalars().all()
    return [to_dict(r) for r in rows]


@api_router.post("/inventory/stock-movements")
async def create_stock_movement(
    payload: ManualStockMovementInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Admin", "Super Admin")),
):
    r = await db.execute(select(M.Product).where(M.Product.id == payload.product_id))
    product = r.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    if user.role == "Admin" and product.outlet_id and product.outlet_id != user.outlet_id:
        raise HTTPException(status_code=403, detail="Produk bukan milik outlet Anda")
    stock_before = int(product.stock or 0)
    if payload.kind == "opname":
        if payload.target_stock is None:
            raise HTTPException(status_code=400, detail="target_stock wajib untuk opname")
        stock_after = max(0, int(payload.target_stock))
    else:
        stock_after = max(0, stock_before + int(payload.delta))
    product.stock = stock_after
    delta = stock_after - stock_before
    outlet_id_final = product.outlet_id or user.outlet_id or "outlet-sudirman"
    mv = M.StockMovement(
        product_id=payload.product_id,
        outlet_id=outlet_id_final,
        kind=payload.kind,
        delta=delta,
        stock_before=stock_before,
        stock_after=stock_after,
        reason=payload.reason,
        operator_id=user.id,
        operator_name=user.name,
        ref_id=payload.ref_id,
    )
    db.add(mv)
    # Also mirror to legacy StockLog to keep dashboards intact
    db.add(M.StockLog(
        product_id=payload.product_id,
        outlet_id=outlet_id_final,
        quantity=delta,
        reason=payload.reason,
        kind=payload.kind if payload.kind != "adjust" else ("in" if delta >= 0 else "out"),
        note="",
        user_id=user.id,
        user_name=user.name,
    ))
    await db.commit()
    await db.refresh(mv)
    return to_dict(mv)


# ── Products Bulk Import (Excel/CSV parsed on the client, sent as JSON) ──────
class BulkProductRow(BaseModel):
    id: Optional[str] = None
    name: str
    category: str = "Lain-lain"
    vendor: str = "MJD Kupi"
    merchant_id: Optional[str] = None
    outlet_id: Optional[str] = None
    price: float = 0
    cost: float = 0
    stock: int = 0
    color: str = "#ffedd5"


class BulkProductInput(BaseModel):
    rows: List[BulkProductRow]
    mode: str = "upsert"  # upsert | insert


@api_router.post("/products/bulk-import")
async def bulk_import_products(
    payload: BulkProductInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    created, updated, errors = 0, 0, []
    for i, row in enumerate(payload.rows):
        if not row.name:
            errors.append({"row": i + 1, "error": "Nama produk kosong"})
            continue
        target_outlet = row.outlet_id or user.outlet_id or "outlet-sudirman"
        if user.role == "Admin" and target_outlet != (user.outlet_id or "outlet-sudirman"):
            target_outlet = user.outlet_id or "outlet-sudirman"
        # Match by id or name+outlet
        existing = None
        if row.id:
            existing = (await db.execute(select(M.Product).where(M.Product.id == row.id))).scalar_one_or_none()
        if not existing and payload.mode == "upsert":
            existing = (await db.execute(
                select(M.Product).where(M.Product.name == row.name, M.Product.outlet_id == target_outlet)
            )).scalar_one_or_none()
        if existing:
            existing.category = row.category or existing.category
            existing.vendor = row.vendor or existing.vendor
            existing.price = float(row.price)
            existing.cost = float(row.cost)
            existing.stock = int(row.stock)
            if row.merchant_id:
                existing.merchant_id = row.merchant_id
            if row.color:
                existing.color = row.color
            updated += 1
        else:
            db.add(M.Product(
                id=row.id or str(uuid.uuid4()),
                name=row.name,
                category=row.category,
                vendor=row.vendor,
                merchant_id=row.merchant_id,
                outlet_id=target_outlet,
                price=float(row.price),
                cost=float(row.cost),
                stock=int(row.stock),
                color=row.color or "#ffedd5",
                modifiers=[],
                variants=[],
            ))
            created += 1
    await db.commit()
    return {"created": created, "updated": updated, "errors": errors, "total": len(payload.rows)}


# ── Settlement / Payout Center (per-merchant breakdown + ledger) ─────────────

class PayoutInput(BaseModel):
    merchant_id: str
    period_start: str  # YYYY-MM-DD
    period_end: str
    note: str = ""


async def _compute_settlement_breakdown(
    db: AsyncSession, outlet_id: Optional[str], date_from: Optional[str], date_to: Optional[str]
) -> list[dict]:
    """Aggregate sales.lines per merchant with commission from merchant scheme."""
    merchants = (await db.execute(select(M.Merchant))).scalars().all()
    merchant_map = {m.id: m for m in merchants}

    stmt = select(M.Sale).where(M.Sale.status == "paid")
    if outlet_id:
        stmt = stmt.where(M.Sale.outlet_id == outlet_id)
    if date_from:
        stmt = stmt.where(M.Sale.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        # inclusive end-of-day
        stmt = stmt.where(M.Sale.created_at <= datetime.fromisoformat(date_to) + timedelta(days=1))
    sales = (await db.execute(stmt)).scalars().all()

    buckets: dict[str, dict] = {}
    for sale in sales:
        for line in (sale.lines or []):
            mid = line.get("merchant_id") or "unassigned"
            m = merchant_map.get(mid)
            bucket = buckets.setdefault(mid, {
                "merchant_id": mid,
                "merchant_name": m.name if m else "Tanpa Merchant",
                "commission_scheme": (m.commission_scheme if m else "percent"),
                "commission_percent": (m.commission_percent if m else 0.0),
                "commission_fixed": (m.commission_fixed if m else 0.0),
                "gross": 0.0,
                "item_count": 0,
                "sale_ids": [],
                "commission": 0.0,
                "net": 0.0,
            })
            qty = int(line.get("quantity") or 0)
            price = float(line.get("price") or 0)
            gross_line = qty * price
            bucket["gross"] += gross_line
            bucket["item_count"] += qty
            if sale.id not in bucket["sale_ids"]:
                bucket["sale_ids"].append(sale.id)
            # commission per line
            if bucket["commission_scheme"] == "fixed":
                bucket["commission"] += bucket["commission_fixed"] * qty
            else:
                bucket["commission"] += gross_line * (bucket["commission_percent"] / 100.0)
    for b in buckets.values():
        b["gross"] = round(b["gross"])
        b["commission"] = round(b["commission"])
        b["net"] = b["gross"] - b["commission"]
    # sort by gross desc
    return sorted(buckets.values(), key=lambda x: x["gross"], reverse=True)


@api_router.get("/settlement/preview")
async def settlement_preview(
    outlet_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Admin", "Super Admin")),
):
    scope = outlet_scope(user, outlet_id)
    breakdown = await _compute_settlement_breakdown(db, scope, date_from, date_to)
    totals = {
        "gross": sum(b["gross"] for b in breakdown),
        "commission": sum(b["commission"] for b in breakdown),
        "net": sum(b["net"] for b in breakdown),
        "item_count": sum(b["item_count"] for b in breakdown),
    }
    return {"breakdown": breakdown, "totals": totals, "date_from": date_from, "date_to": date_to}


@api_router.get("/settlement/payouts")
async def list_payouts(
    merchant_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Admin", "Super Admin")),
):
    stmt = select(M.Payout).order_by(M.Payout.created_at.desc()).limit(200)
    if merchant_id:
        stmt = stmt.where(M.Payout.merchant_id == merchant_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [to_dict(r) for r in rows]


@api_router.post("/settlement/payouts")
async def create_payout(
    payload: PayoutInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Admin", "Super Admin")),
):
    merchant = (await db.execute(select(M.Merchant).where(M.Merchant.id == payload.merchant_id))).scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant tidak ditemukan")
    breakdown = await _compute_settlement_breakdown(db, None, payload.period_start, payload.period_end)
    entry = next((b for b in breakdown if b["merchant_id"] == payload.merchant_id), None)
    if not entry or entry["gross"] <= 0:
        raise HTTPException(status_code=400, detail="Belum ada omset untuk merchant pada periode ini")
    payout = M.Payout(
        merchant_id=payload.merchant_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        gross=entry["gross"],
        commission=entry["commission"],
        net=entry["net"],
        item_count=entry["item_count"],
        sale_ids=entry["sale_ids"],
        status="paid",
        note=payload.note,
        operator_id=user.id,
        operator_name=user.name,
    )
    db.add(payout)
    await db.commit()
    await db.refresh(payout)
    return to_dict(payout)


# -----------------------------------------------------------------------------
# Kitchen Display (KDS)
# -----------------------------------------------------------------------------

@api_router.get("/kds/orders")
async def kds_orders(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Admin", "Super Admin", "Kasir")),
):
    stmt = (
        select(M.KitchenOrder)
        .where(M.KitchenOrder.status != "Selesai")
        .order_by(M.KitchenOrder.sla_start.asc())
        .limit(200)
    )
    # Vendor bound to merchant
    if user.role == "Vendor" and user.merchant_id:
        stmt = stmt.where(M.KitchenOrder.merchant_id == user.merchant_id)
    # Outlet isolation
    scope = outlet_scope(user, outlet_id)
    if scope:
        stmt = stmt.where(M.KitchenOrder.outlet_id == scope)
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


@api_router.patch("/kds/orders/{ticket_id}")
async def update_kds_status(
    ticket_id: str,
    payload: KdsStatusInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Admin", "Super Admin", "Kasir")),
):
    result = await db.execute(select(M.KitchenOrder).where(M.KitchenOrder.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket dapur tidak ditemukan")
    if user.role == "Vendor" and user.merchant_id and ticket.merchant_id != user.merchant_id:
        raise HTTPException(status_code=403, detail="Bukan tiket merchant Anda")
    ticket.status = payload.status
    ticket.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": ticket_id, "status": payload.status}


# -----------------------------------------------------------------------------
# Shift management (kasir cash drawer)
# -----------------------------------------------------------------------------

@api_router.get("/shifts/current")
async def current_shift(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    result = await db.execute(
        select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
    )
    shift = result.scalar_one_or_none()
    return to_dict(shift) if shift else None


@api_router.post("/shifts/open")
async def open_shift(
    payload: ShiftOpenInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    result = await db.execute(
        select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Shift aktif masih terbuka")
    shift = M.Shift(
        cashier_id=user.id,
        cashier_name=user.name,
        outlet_id=user.outlet_id or "outlet-sudirman",
        opening_cash=payload.opening_cash,
        note=payload.note,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return to_dict(shift)


@api_router.post("/shifts/close")
async def close_shift(
    payload: ShiftCloseInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    result = await db.execute(
        select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="Tidak ada shift aktif")
    # Cash sales during this shift
    cash_r = await db.execute(
        select(func.coalesce(func.sum(M.Sale.total), 0)).where(
            M.Sale.shift_id == shift.id, M.Sale.payment_method == "Cash", M.Sale.status != "voided"
        )
    )
    cash_sales = float(cash_r.scalar_one() or 0)
    # Cash expenses recorded during this shift (kas keluar)
    exp_r = await db.execute(
        select(func.coalesce(func.sum(M.Expense.amount), 0)).where(
            M.Expense.shift_id == shift.id, M.Expense.method == "Cash"
        )
    )
    cash_expenses = float(exp_r.scalar_one() or 0)
    # Kas Seharusnya = Modal Awal + Omset Tunai - Pengeluaran Tunai
    shift.expected_cash = float(shift.opening_cash) + cash_sales - cash_expenses
    shift.closing_cash = payload.closing_cash
    shift.variance = payload.closing_cash - shift.expected_cash
    shift.note = payload.note or shift.note
    shift.status = "closed"
    shift.closed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shift)
    return {
        **to_dict(shift),
        "cash_sales": cash_sales,
        "cash_expenses": cash_expenses,
    }


@api_router.get("/shifts")
async def list_shifts(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    result = await db.execute(select(M.Shift).order_by(M.Shift.opened_at.desc()).limit(50))
    shifts = [to_dict(row) for row in result.scalars().all()]
    # Enrich with realtime cash & transfer totals
    for s in shifts:
        cash_r = await db.execute(
            select(func.coalesce(func.sum(M.Sale.total), 0)).where(
                M.Sale.shift_id == s["id"], M.Sale.payment_method == "Cash"
            )
        )
        trf_r = await db.execute(
            select(func.coalesce(func.sum(M.Sale.total), 0)).where(
                M.Sale.shift_id == s["id"], M.Sale.payment_method != "Cash"
            )
        )
        count_r = await db.execute(
            select(func.count(M.Sale.id)).where(M.Sale.shift_id == s["id"])
        )
        s["total_cash"] = float(cash_r.scalar_one() or 0)
        s["total_transfer"] = float(trf_r.scalar_one() or 0)
        s["transaction_count"] = int(count_r.scalar_one() or 0)
    return shifts


@api_router.get("/shifts/{shift_id}/report")
async def shift_report(
    shift_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(current_user),
):
    """Detailed shift report for close/print/WA share."""
    result = await db.execute(select(M.Shift).where(M.Shift.id == shift_id))
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift tidak ditemukan")
    if user.role == "Kasir" and shift.cashier_id != user.id:
        raise HTTPException(status_code=403, detail="Bukan shift Anda")

    sales_r = await db.execute(select(M.Sale).where(M.Sale.shift_id == shift_id))
    sales = sales_r.scalars().all()
    cash = sum(s.total for s in sales if s.payment_method == "Cash")
    transfer = sum(s.total for s in sales if s.payment_method != "Cash")
    tables_paid = len({s.table_no for s in sales})

    # Pending self-orders on this shift's day (Menunggu kasir)
    pending_r = await db.execute(
        select(M.SelfOrder).where(M.SelfOrder.status == "Menunggu kasir")
    )
    pendings = pending_r.scalars().all()
    tables_pending = len({o.table_no for o in pendings})
    unpaid_total = sum(o.total for o in pendings)

    # Expenses today
    exp_r = await db.execute(select(func.coalesce(func.sum(M.Expense.amount), 0)))
    expenses_total = float(exp_r.scalar_one() or 0)

    # Per merchant breakdown
    per_merchant: dict[str, float] = {}
    for s in sales:
        for ln in (s.lines or []):
            key = ln.get("vendor") or "MJD Kupi"
            per_merchant[key] = per_merchant.get(key, 0) + (ln.get("price", 0) * ln.get("quantity", 0))

    return {
        "shift": to_dict(shift),
        "cashier_name": shift.cashier_name,
        "total_cash": float(cash),
        "total_transfer": float(transfer),
        "total_omset": float(cash + transfer),
        "tables_paid": tables_paid,
        "tables_pending": tables_pending,
        "unpaid_total": float(unpaid_total),
        "expenses_total": expenses_total,
        "transaction_count": len(sales),
        "per_merchant": per_merchant,
    }


@api_router.get("/pos/online-orders")
async def pos_online_orders(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Admin", "Super Admin")),
):
    """Antrean pesanan dari QR meja self-order yang belum di-approve kasir."""
    stmt = (
        select(M.SelfOrder)
        .where(M.SelfOrder.status.in_(PENDING_SELF_ORDER_STATUSES))
        .order_by(M.SelfOrder.created_at.desc())
        .limit(100)
    )
    scope = outlet_scope(user, outlet_id)
    if scope:
        stmt = stmt.where(M.SelfOrder.outlet_id == scope)
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


# -----------------------------------------------------------------------------
# PIN authorization (dynamic 6-char code, valid 15 min) — TOTP-like
# -----------------------------------------------------------------------------

import secrets as _secrets

@api_router.post("/admin/pin/generate", response_model=PinGenerateResponse)
async def generate_pin(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    pin = "".join(_secrets.choice(alphabet) for _ in range(6))
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    key = f"pin:{user.outlet_id or 'outlet-sudirman'}"
    payload = {"pin": pin, "expires_at": expires.isoformat(), "generated_by": user.username or user.email}
    r = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = r.scalar_one_or_none()
    if row:
        row.value = payload; row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(M.Setting(key=key, value=payload))
    await db.commit()
    logger.info(f"[audit] pin_generated by={user.username or user.email} outlet={user.outlet_id}")
    return {"pin": pin, "expires_at": expires.isoformat()}


async def _verify_pin(db: AsyncSession, outlet_id: str, pin: str) -> bool:
    r = await db.execute(select(M.Setting).where(M.Setting.key == f"pin:{outlet_id}"))
    row = r.scalar_one_or_none()
    if not row or not row.value:
        return False
    data = row.value
    if str(data.get("pin", "")).upper() != pin.upper():
        return False
    try:
        exp = datetime.fromisoformat(data["expires_at"])
        return datetime.now(timezone.utc) < exp
    except Exception:
        return False


@api_router.post("/sales/{sale_id}/void")
async def void_sale(
    sale_id: str,
    payload: VoidSaleInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Admin", "Super Admin")),
):
    result = await db.execute(select(M.Sale).where(M.Sale.id == sale_id))
    sale = result.scalar_one_or_none()
    if not sale:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    if sale.status == "voided":
        raise HTTPException(status_code=400, detail="Transaksi sudah dibatalkan")
    if user.role == "Kasir" and sale.cashier_id != user.id:
        raise HTTPException(status_code=403, detail="Bukan transaksi Anda")
    if not await _verify_pin(db, sale.outlet_id or user.outlet_id, payload.pin):
        raise HTTPException(status_code=403, detail="Kode otorisasi salah atau kadaluarsa")
    # Restore stock
    for line in (sale.lines or []):
        pr = await db.execute(select(M.Product).where(M.Product.id == line.get("product_id")))
        p = pr.scalar_one_or_none()
        if p:
            p.stock = int(p.stock or 0) + int(line.get("quantity", 0))
    sale.status = "voided"
    sale.void_reason = payload.reason
    sale.voided_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info(f"[audit] sale_voided id={sale.id} by={user.username or user.email} reason={payload.reason}")
    return to_dict(sale)


@api_router.get("/pos/history")
async def kasir_history(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Admin", "Super Admin")),
):
    """History transaksi kasir untuk shift aktif."""
    if user.role != "Kasir":
        r = await db.execute(select(M.Sale).order_by(M.Sale.created_at.desc()).limit(100))
        return [to_dict(s) for s in r.scalars().all()]
    a = await db.execute(select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open"))
    shift = a.scalar_one_or_none()
    if not shift:
        return []
    r = await db.execute(select(M.Sale).where(M.Sale.shift_id == shift.id).order_by(M.Sale.created_at.desc()))
    return [to_dict(s) for s in r.scalars().all()]


# -----------------------------------------------------------------------------
# Bank accounts (per outlet)
# -----------------------------------------------------------------------------

@api_router.get("/settings/bank-accounts")
async def get_bank_accounts(
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    outlet = outlet_id or "outlet-sudirman"
    r = await db.execute(select(M.Setting).where(M.Setting.key == f"bank-accounts:{outlet}"))
    row = r.scalar_one_or_none()
    return row.value if row else {"accounts": []}


from sqlalchemy.orm.attributes import flag_modified

@api_router.post("/settings/bank-accounts")
async def add_bank_account(
    payload: BankAccountInput,
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    outlet = outlet_id or user.outlet_id or "outlet-sudirman"
    key = f"bank-accounts:{outlet}"
    r = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = r.scalar_one_or_none()
    accounts = list(row.value.get("accounts", [])) if row and row.value else []
    accounts.append({"id": str(uuid.uuid4()), **payload.model_dump()})
    if row:
        row.value = {"accounts": accounts}
        row.updated_at = datetime.now(timezone.utc)
        flag_modified(row, "value")
    else:
        db.add(M.Setting(key=key, value={"accounts": accounts}))
    await db.commit()
    return {"accounts": accounts}


@api_router.delete("/settings/bank-accounts/{account_id}")
async def delete_bank_account(
    account_id: str,
    outlet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    outlet = outlet_id or user.outlet_id or "outlet-sudirman"
    key = f"bank-accounts:{outlet}"
    r = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Belum ada rekening")
    accounts = [a for a in (row.value.get("accounts", []) or []) if a.get("id") != account_id]
    row.value = {"accounts": accounts}
    row.updated_at = datetime.now(timezone.utc)
    flag_modified(row, "value")
    await db.commit()
    return {"accounts": accounts}


# -----------------------------------------------------------------------------
# Settings (printer, QRIS, branding, etc.)
# -----------------------------------------------------------------------------

@api_router.get("/settings/{key}")
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else {}


@api_router.post("/settings")
async def upsert_setting(
    payload: SettingInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    result = await db.execute(select(M.Setting).where(M.Setting.key == payload.key))
    row = result.scalar_one_or_none()
    if row:
        row.value = payload.value
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(M.Setting(key=payload.key, value=payload.value))
    await db.commit()
    return {"ok": True, "key": payload.key}


# Convenience endpoint for legacy QRIS write path
class QrisInput(BaseModel):
    outlet_id: str
    qris_code: str


@api_router.post("/settings/qris")
async def save_qris(
    payload: QrisInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Admin")),
):
    key = f"qris:{payload.outlet_id}"
    result = await db.execute(select(M.Setting).where(M.Setting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = {"qris_code": payload.qris_code}
    else:
        db.add(M.Setting(key=key, value={"qris_code": payload.qris_code}))
    await db.commit()
    return {"ok": True, "outlet_id": payload.outlet_id}


# -----------------------------------------------------------------------------
# Feature Toggles (per role / per outlet) — Super Admin only
# -----------------------------------------------------------------------------

FEATURE_KEYS_DEFAULT = {
    "pos": True, "self_order": True, "kds": True, "inventory": True,
    "expenses": True, "reports": True, "vendor_center": True, "settings": True,
    "users": True, "merchants": True, "products": True, "outlets": True,
    "tables": True, "cashiers": True, "overview": True, "white_label": True,
}


class FeatureToggleInput(BaseModel):
    # matrix: {"role:Kasir": {"pos": true, "kds": false}, "outlet:outlet-kemang": {"self_order": false}}
    matrix: dict = {}


@api_router.get("/feature-toggles")
async def get_feature_toggles(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    result = await db.execute(select(M.Setting).where(M.Setting.key == "feature_toggles"))
    row = result.scalar_one_or_none()
    matrix = (row.value or {}).get("matrix", {}) if row else {}
    return {"defaults": FEATURE_KEYS_DEFAULT, "matrix": matrix}


@api_router.post("/feature-toggles")
async def save_feature_toggles(
    payload: FeatureToggleInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin")),
):
    result = await db.execute(select(M.Setting).where(M.Setting.key == "feature_toggles"))
    row = result.scalar_one_or_none()
    value = {"matrix": payload.matrix or {}}
    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(M.Setting(key="feature_toggles", value=value))
    await db.commit()
    return {"ok": True, "matrix": payload.matrix}


# -----------------------------------------------------------------------------
# White-Label Branding lookup (public: reads merchant by slug for self-order)
# -----------------------------------------------------------------------------

@api_router.get("/branding/by-slug/{slug}")
async def branding_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(M.Merchant).where(M.Merchant.slug == slug))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Mitra tidak ditemukan")
    if merchant.subscription_status == "suspended":
        raise HTTPException(status_code=403, detail="Masa Langganan/Kerjasama Toko Telah Berakhir. Silakan Hubungi Platform Owner.")
    return {
        "id": merchant.id,
        "name": merchant.name,
        "slug": merchant.slug,
        "logo_url": merchant.logo_url,
        "theme_color": merchant.theme_color,
        "banner_url": merchant.banner_url,
        "receipt_header": merchant.receipt_header,
        "receipt_footer": merchant.receipt_footer,
        "subscription_status": merchant.subscription_status,
        "features_enabled": merchant.features_enabled or {},
    }


@api_router.get("/branding/current")
async def branding_current(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    """Returns the branding for the logged-in user's tenant merchant."""
    if not user.merchant_id:
        # Super Admin / Admin without merchant: return platform default
        return {"id": "", "name": "MJD Kupi", "theme_color": "#f97316", "logo_url": "", "banner_url": "", "subscription_status": "active", "features_enabled": {}}
    result = await db.execute(select(M.Merchant).where(M.Merchant.id == user.merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        return {"id": "", "name": "MJD Kupi", "theme_color": "#f97316", "logo_url": "", "banner_url": "", "subscription_status": "active", "features_enabled": {}}
    return {
        "id": merchant.id, "name": merchant.name, "slug": merchant.slug,
        "logo_url": merchant.logo_url, "theme_color": merchant.theme_color,
        "banner_url": merchant.banner_url, "receipt_header": merchant.receipt_header,
        "receipt_footer": merchant.receipt_footer, "subscription_status": merchant.subscription_status,
        "features_enabled": merchant.features_enabled or {},
    }


# -----------------------------------------------------------------------------
# Startup: create tables + seed demo data
# -----------------------------------------------------------------------------

DEMO_MERCHANTS = [
    ("m-barista", "Barista Kopi", "Kopi", 10.0, "62811100001", "#fff0e6"),
    ("m-nasi-uduk", "Nasi Uduk Bang Agus", "Makanan", 15.0, "62811100002", "#fff8dc"),
    ("m-sate", "Sate Madura Pak Kumis", "Makanan", 15.0, "62811100003", "#fee2e2"),
    ("m-bakery", "MJD Bakery", "Snack", 12.0, "62811100004", "#fff2c6"),
]

DEMO_PRODUCTS = [
    ("p-1", "Kopi Susu Gula Aren", "Kopi", "m-barista", 18000, 6500, 42, "#fff0e6"),
    ("p-2", "Americano Ice", "Kopi", "m-barista", 15000, 4500, 28, "#f6eadf"),
    ("p-3", "Nasi Uduk Ayam", "Makanan", "m-nasi-uduk", 24000, 11500, 18, "#fff8dc"),
    ("p-4", "Sate Madura 10 Tusuk", "Makanan", "m-sate", 30000, 15000, 12, "#fee2e2"),
    ("p-5", "Croffle Butter", "Snack", "m-bakery", 16000, 6000, 24, "#fff2c6"),
    ("p-6", "Matcha Latte", "Non-Kopi", "m-barista", 22000, 8000, 9, "#e6f4e7"),
]


@app.on_event("startup")
async def bootstrap():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent ALTER for new columns on existing tables (Feb 2026)
        from sqlalchemy import text
        for stmt in (
            "ALTER TABLE mjd_products ADD COLUMN IF NOT EXISTS image_url TEXT DEFAULT ''",
            "ALTER TABLE mjd_self_orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32) DEFAULT ''",
            "ALTER TABLE mjd_self_orders ADD COLUMN IF NOT EXISTS payment_proof TEXT DEFAULT ''",
            "ALTER TABLE mjd_users ADD COLUMN IF NOT EXISTS username VARCHAR(64) UNIQUE",
            "ALTER TABLE mjd_users ADD COLUMN IF NOT EXISTS plain_password VARCHAR(255) DEFAULT ''",
            "ALTER TABLE mjd_users ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE mjd_expenses ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
            "ALTER TABLE mjd_expenses ADD COLUMN IF NOT EXISTS user_name VARCHAR(120) DEFAULT ''",
            "ALTER TABLE mjd_expenses ADD COLUMN IF NOT EXISTS shift_id VARCHAR(36)",
            "ALTER TABLE mjd_outlets ADD COLUMN IF NOT EXISTS phone VARCHAR(32) DEFAULT ''",
            "ALTER TABLE mjd_users ADD COLUMN IF NOT EXISTS merchant_id VARCHAR(36)",
            "ALTER TABLE mjd_products ADD COLUMN IF NOT EXISTS outlet_id VARCHAR(36) DEFAULT 'outlet-sudirman'",
            "ALTER TABLE mjd_stock_logs ADD COLUMN IF NOT EXISTS outlet_id VARCHAR(36) DEFAULT 'outlet-sudirman'",
            "ALTER TABLE mjd_stock_logs ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
            "ALTER TABLE mjd_stock_logs ADD COLUMN IF NOT EXISTS user_name VARCHAR(120) DEFAULT ''",
            "ALTER TABLE mjd_kitchen_orders ADD COLUMN IF NOT EXISTS outlet_id VARCHAR(36) DEFAULT 'outlet-sudirman'",
            "ALTER TABLE mjd_self_orders ADD COLUMN IF NOT EXISTS outlet_id VARCHAR(36) DEFAULT 'outlet-sudirman'",
            "ALTER TABLE mjd_self_orders ADD COLUMN IF NOT EXISTS customer_name VARCHAR(120) DEFAULT ''",
            "ALTER TABLE mjd_sales ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'paid'",
            "ALTER TABLE mjd_sales ADD COLUMN IF NOT EXISTS void_reason TEXT DEFAULT ''",
            "ALTER TABLE mjd_sales ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ",
            "ALTER TABLE mjd_products ADD COLUMN IF NOT EXISTS variants JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS slug VARCHAR(64)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_merchant_slug ON mjd_merchants(slug)",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT ''",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS theme_color VARCHAR(16) DEFAULT '#f97316'",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS banner_url TEXT DEFAULT ''",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS receipt_header TEXT DEFAULT ''",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS receipt_footer TEXT DEFAULT ''",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS wifi_password VARCHAR(64) DEFAULT ''",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(16) DEFAULT 'active'",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMPTZ",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS features_enabled JSONB DEFAULT '{}'::jsonb",
            "CREATE INDEX IF NOT EXISTS ix_sales_outlet ON mjd_sales(outlet_id)",
            "ALTER TABLE mjd_self_orders ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(32) DEFAULT ''",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS commission_scheme VARCHAR(16) DEFAULT 'percent'",
            "ALTER TABLE mjd_merchants ADD COLUMN IF NOT EXISTS commission_fixed FLOAT DEFAULT 0",
            "UPDATE mjd_self_orders SET status='Pesanan Diterima' WHERE status='Menunggu kasir'",
            "UPDATE mjd_users SET role='Admin' WHERE role='Merchant Admin'",
            "UPDATE mjd_users SET merchant_id='m-barista' WHERE role='Vendor' AND (merchant_id IS NULL OR merchant_id='')",
        ):
            await conn.execute(text(stmt))

    async with AsyncSessionLocal() as db:
        # Seed outlets
        count = (await db.execute(select(func.count(M.Outlet.id)))).scalar_one()
        if count == 0:
            db.add_all([
                M.Outlet(id="outlet-sudirman", name="Outlet Sudirman", address="Jl. Sudirman No. 10", active=True),
                M.Outlet(id="outlet-kemang", name="Outlet Kemang", address="Jl. Kemang Raya No. 3", active=True),
            ])
            await db.commit()

        # Seed users (with username & plain_password)
        for email, username, password, role, name in DEMO_USERS:
            result = await db.execute(select(M.User).where(M.User.email == email))
            existing = result.scalar_one_or_none()
            if not existing:
                db.add(M.User(
                    email=email,
                    username=username,
                    password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                    plain_password=password,
                    role=role,
                    name=name,
                    active=True,
                ))
            else:
                # Backfill username/plain_password for existing users
                changed = False
                if not existing.username:
                    existing.username = username; changed = True
                if not existing.plain_password:
                    existing.plain_password = password; changed = True
                # Also rotate super admin password to new spec
                if username == "superadmin" and not bcrypt.checkpw(password.encode(), existing.password_hash.encode()):
                    existing.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                    existing.plain_password = password
                    changed = True
                if changed:
                    pass
        await db.commit()

        # Seed merchants
        count = (await db.execute(select(func.count(M.Merchant.id)))).scalar_one()
        if count == 0:
            for mid, name, cat, comm, phone, color in DEMO_MERCHANTS:
                db.add(M.Merchant(
                    id=mid, name=name, category=cat, commission_percent=comm, phone=phone, color=color,
                ))
            await db.commit()

        # Seed products
        count = (await db.execute(select(func.count(M.Product.id)))).scalar_one()
        if count == 0:
            for pid, name, cat, mid, price, cost, stock, color in DEMO_PRODUCTS:
                # Lookup vendor name from seeded merchants
                vendor_name = next((n for _mid, n, *_ in DEMO_MERCHANTS if _mid == mid), "MJD Kupi")
                db.add(M.Product(
                    id=pid, name=name, category=cat, merchant_id=mid, vendor=vendor_name,
                    price=price, cost=cost, stock=stock, color=color, modifiers=[],
                ))
            await db.commit()

        # Seed default expenses if empty
        count = (await db.execute(select(func.count(M.Expense.id)))).scalar_one()
        if count == 0:
            db.add_all([
                M.Expense(category="Pembelian Bahan Baku", note="Restock susu & biji kopi", amount=1250000, date="2026-02-12", method="Transfer"),
                M.Expense(category="Listrik & Air", note="Tagihan bulan berjalan", amount=850000, date="2026-02-10", method="Transfer"),
            ])
            await db.commit()


@app.on_event("shutdown")
async def shutdown_engine():
    await engine.dispose()


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    # SEC-001 defense-in-depth: require custom header on state-changing API routes.
    # Browsers cannot send custom headers on cross-site simple requests → effective anti-CSRF
    # even if the ingress rewrites cookie SameSite. Same-origin fetch()/axios sends it fine.
    method = request.method.upper()
    path = request.url.path or ""
    is_state = method in ("POST", "PUT", "PATCH", "DELETE")
    # Allow list: login (bootstraps session) and public customer self-order create
    allow = path.startswith("/api/auth/login") or path == "/api/self-order"
    if is_state and path.startswith("/api/") and not allow:
        if request.headers.get("x-requested-with", "").lower() != "mjd-kupi":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "CSRF header missing"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response
