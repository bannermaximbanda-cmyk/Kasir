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
    phone: str = ""
    color: str = "#ffedd5"
    active: bool = True


class ProductInput(BaseModel):
    id: Optional[str] = None
    name: str
    category: str = "Lain-lain"
    vendor: str = "MJD Kupi"
    merchant_id: Optional[str] = None
    price: float = 0
    cost: float = 0
    stock: int = 0
    color: str = "#ffedd5"
    image_url: str = ""
    modifiers: List[Any] = []


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


class OutletInput(BaseModel):
    id: Optional[str] = None
    name: str
    address: str = ""
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

ROLES = ["Super Admin", "Merchant Admin", "Vendor", "Kasir"]
DEMO_USERS = [
    ("superadmin@mjd-kupi.local", "MjdKupi#2026", "Super Admin", "Raka Owner"),
    ("manager@mjd-kupi.local", "MjdKupi#2026", "Merchant Admin", "Maya Ardianti"),
    ("vendor@mjd-kupi.local", "MjdKupi#2026", "Vendor", "Agus Tenant"),
    ("kasir@mjd-kupi.local", "MjdKupi#2026", "Kasir", "Dina Kasir"),
]


def public_user(user: M.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "name": user.name,
        "outlet_id": user.outlet_id or "outlet-sudirman",
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
# Auth routes
# -----------------------------------------------------------------------------

@api_router.get("/")
async def root():
    return {"service": "mjd-kupi", "status": "ok", "db": "supabase"}


@api_router.post("/auth/login")
async def login(payload: LoginInput, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(M.User).where(M.User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not bcrypt.checkpw(payload.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Email atau password salah")
    access = token_for(user)
    refresh = token_for(user, "refresh")
    cookie_kwargs = dict(httponly=True, secure=True, samesite="none")
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
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
):
    merchant = M.Merchant(
        id=payload.id or str(uuid.uuid4()),
        name=payload.name,
        category=payload.category,
        commission_percent=payload.commission_percent,
        phone=payload.phone,
        color=payload.color,
        active=payload.active,
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
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
):
    result = await db.execute(select(M.Merchant).where(M.Merchant.id == merchant_id))
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant tidak ditemukan")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"id"}).items():
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
async def list_products(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(M.Product).order_by(M.Product.name))
    return [to_dict(p) for p in result.scalars().all()]


@api_router.post("/products")
async def create_product(
    payload: ProductInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
):
    product = M.Product(
        id=payload.id or str(uuid.uuid4()),
        name=payload.name,
        category=payload.category,
        vendor=payload.vendor,
        merchant_id=payload.merchant_id,
        price=payload.price,
        cost=payload.cost,
        stock=payload.stock,
        color=payload.color,
        image_url=payload.image_url,
        modifiers=payload.modifiers,
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
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
):
    result = await db.execute(select(M.Product).where(M.Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    for field, value in payload.model_dump(exclude_unset=True, exclude={"id"}).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return to_dict(product)


@api_router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
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
    if payload.kind == "opname":
        product.stock = max(0, payload.quantity)
    else:
        product.stock = max(0, int(product.stock or 0) + payload.quantity)
    log = M.StockLog(
        product_id=product_id,
        quantity=payload.quantity,
        reason=payload.reason,
        kind=payload.kind,
        note=payload.note,
    )
    db.add(log)
    await db.commit()
    await db.refresh(product)
    return to_dict(product)


@api_router.get("/stock-logs")
async def stock_logs(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    result = await db.execute(select(M.StockLog).order_by(M.StockLog.created_at.desc()).limit(500))
    return [to_dict(row) for row in result.scalars().all()]


# -----------------------------------------------------------------------------
# Expenses
# -----------------------------------------------------------------------------

@api_router.get("/expenses")
async def list_expenses(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    result = await db.execute(select(M.Expense).order_by(M.Expense.date.desc()))
    return [to_dict(row) for row in result.scalars().all()]


@api_router.post("/expenses")
async def create_expense(
    payload: ExpenseInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
):
    expense = M.Expense(
        id=payload.id or str(uuid.uuid4()),
        category=payload.category,
        note=payload.note,
        amount=payload.amount,
        date=payload.date,
        method=payload.method,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return to_dict(expense)


# -----------------------------------------------------------------------------
# Kitchen (KDS) helpers
# -----------------------------------------------------------------------------

async def create_kitchen_tickets(
    db: AsyncSession, source_id: str, source_type: str, table_no: str, lines: List[dict]
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

    sale = M.Sale(
        id=payload.id or str(uuid.uuid4()),
        table_no=payload.table,
        subtotal=payload.subtotal,
        tax=payload.tax,
        total=payload.total,
        payment_method=payload.payment_method,
        payment_reference=payload.payment_reference,
        cash_received=payload.cash_received,
        change_amount=payload.change_amount,
        outlet_id=user.outlet_id or "outlet-sudirman",
        cashier_id=user.id,
        shift_id=shift_id,
        lines=[ln.model_dump() for ln in payload.lines],
    )
    db.add(sale)
    # Deduct stock
    for line in payload.lines:
        result = await db.execute(select(M.Product).where(M.Product.id == line.product_id))
        product = result.scalar_one_or_none()
        if product:
            product.stock = max(0, int(product.stock or 0) - int(line.quantity))
    await db.commit()
    await db.refresh(sale)
    # Kitchen tickets split per merchant
    await create_kitchen_tickets(
        db, sale.id, "sale", sale.table_no, [ln.model_dump() for ln in payload.lines]
    )
    return to_dict(sale)


@api_router.get("/sales")
async def list_sales(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
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
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

@api_router.get("/dashboard")
async def dashboard_summary(db: AsyncSession = Depends(get_db), user: M.User = Depends(current_user)):
    sales_total = (await db.execute(select(func.coalesce(func.sum(M.Sale.total), 0)))).scalar_one()
    expenses_total = (await db.execute(select(func.coalesce(func.sum(M.Expense.amount), 0)))).scalar_one()
    trx_count = (await db.execute(select(func.count(M.Sale.id)))).scalar_one()
    return {
        "sales_total": float(sales_total or 0),
        "expense_total": float(expenses_total or 0),
        "transaction_count": int(trx_count or 0),
    }


# -----------------------------------------------------------------------------
# Self-order & Vendor / KDS
# -----------------------------------------------------------------------------

@api_router.post("/self-order")
async def create_self_order(payload: SelfOrderInput, db: AsyncSession = Depends(get_db)):
    order = M.SelfOrder(
        id=str(uuid.uuid4()),
        table_no=payload.table,
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


@api_router.post("/self-order/{order_id}/accept")
async def accept_self_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Merchant Admin", "Super Admin")),
):
    """Kasir menyetujui pesanan online: buat sale, kurangi stok, buat KDS tickets."""
    result = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    if order.status not in ("Menunggu kasir", "Menunggu konfirmasi"):
        raise HTTPException(status_code=400, detail=f"Pesanan sudah {order.status}")

    shift_id = None
    if user.role == "Kasir":
        active = await db.execute(
            select(M.Shift).where(M.Shift.cashier_id == user.id, M.Shift.status == "open")
        )
        shift = active.scalar_one_or_none()
        if not shift:
            raise HTTPException(status_code=400, detail="Buka shift terlebih dahulu")
        shift_id = shift.id

    subtotal = float(order.total)
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
        lines=order.lines or [],
    )
    db.add(sale)
    for line in (order.lines or []):
        r = await db.execute(select(M.Product).where(M.Product.id == line.get("product_id")))
        product = r.scalar_one_or_none()
        if product:
            product.stock = max(0, int(product.stock or 0) - int(line.get("quantity", 0)))
    order.status = "Diproses"
    await db.commit()
    await db.refresh(sale)
    await create_kitchen_tickets(db, sale.id, "sale", sale.table_no, order.lines or [])
    return to_dict(sale)


@api_router.get("/vendor/orders")
async def vendor_orders(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Merchant Admin", "Super Admin")),
):
    result = await db.execute(select(M.SelfOrder).order_by(M.SelfOrder.created_at.desc()).limit(200))
    return [to_dict(row) for row in result.scalars().all()]


@api_router.patch("/vendor/orders/{order_id}")
async def update_vendor_order(
    order_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Merchant Admin", "Super Admin")),
):
    result = await db.execute(select(M.SelfOrder).where(M.SelfOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    order.status = status
    await db.commit()
    return {"id": order_id, "status": status}


@api_router.get("/vendor/settlement")
async def vendor_settlement(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Merchant Admin", "Super Admin")),
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
# Kitchen Display (KDS)
# -----------------------------------------------------------------------------

@api_router.get("/kds/orders")
async def kds_orders(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Merchant Admin", "Super Admin", "Kasir")),
):
    stmt = (
        select(M.KitchenOrder)
        .where(M.KitchenOrder.status != "Selesai")
        .order_by(M.KitchenOrder.sla_start.asc())
        .limit(200)
    )
    result = await db.execute(stmt)
    return [to_dict(row) for row in result.scalars().all()]


@api_router.patch("/kds/orders/{ticket_id}")
async def update_kds_status(
    ticket_id: str,
    payload: KdsStatusInput,
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Vendor", "Merchant Admin", "Super Admin", "Kasir")),
):
    result = await db.execute(select(M.KitchenOrder).where(M.KitchenOrder.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket dapur tidak ditemukan")
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
    # Sum cash sales during the shift
    cash_result = await db.execute(
        select(func.coalesce(func.sum(M.Sale.total), 0)).where(
            M.Sale.shift_id == shift.id, M.Sale.payment_method == "Cash"
        )
    )
    cash_sales = float(cash_result.scalar_one() or 0)
    shift.expected_cash = shift.opening_cash + cash_sales
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
    }


@api_router.get("/shifts")
async def list_shifts(
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
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
    db: AsyncSession = Depends(get_db),
    user: M.User = Depends(require_roles("Kasir", "Merchant Admin", "Super Admin")),
):
    """Antrean pesanan dari QR meja self-order yang belum di-approve kasir."""
    result = await db.execute(
        select(M.SelfOrder)
        .where(M.SelfOrder.status.in_(["Menunggu kasir", "Menunggu konfirmasi"]))
        .order_by(M.SelfOrder.created_at.desc())
        .limit(100)
    )
    return [to_dict(row) for row in result.scalars().all()]


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
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
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
    user: M.User = Depends(require_roles("Super Admin", "Merchant Admin")),
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

        # Seed users
        for email, password, role, name in DEMO_USERS:
            result = await db.execute(select(M.User).where(M.User.email == email))
            if not result.scalar_one_or_none():
                db.add(M.User(
                    email=email,
                    password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                    role=role,
                    name=name,
                ))
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
