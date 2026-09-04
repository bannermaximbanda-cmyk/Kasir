"""SQLAlchemy models for MJD Kupi (Supabase Postgres)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON, Index,
)
from database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "mjd_users"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(64), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    plain_password = Column(String(255), default="")  # Only shown to Super Admin (internal admin tooling)
    role = Column(String(32), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    outlet_id = Column(String(36), default="outlet-sudirman")
    merchant_id = Column(String(36), index=True, nullable=True)  # For Vendor role - tenant binding
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)


class Outlet(Base):
    __tablename__ = "mjd_outlets"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(120), nullable=False)
    address = Column(String(255), default="")
    phone = Column(String(32), default="")
    active = Column(Boolean, default=True)


class Merchant(Base):
    """Tenant / Vendor booth inside an outlet (e.g., Barista Kopi, Nasi Uduk).

    Extended (Feb 2026) with White-Label Partner branding & SaaS subscription fields.
    """
    __tablename__ = "mjd_merchants"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(120), nullable=False)
    category = Column(String(64), default="F&B")
    commission_percent = Column(Float, default=10.0)
    phone = Column(String(32), default="")
    color = Column(String(16), default="#ffedd5")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    # ── White-Label Partner Management ──────────────────────────────
    slug = Column(String(64), unique=True, index=True, nullable=True)
    logo_url = Column(Text, default="")
    theme_color = Column(String(16), default="#f97316")  # accent color
    banner_url = Column(Text, default="")
    receipt_header = Column(Text, default="")
    receipt_footer = Column(Text, default="")
    wifi_password = Column(String(64), default="")
    subscription_status = Column(String(16), default="active", index=True)  # active | trial | pending | suspended
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    features_enabled = Column(JSON, default=dict)  # {"pos":true, "self_order":true, "kds":true, "inventory":true, "reports":true, "multi_merchant":true}


class Product(Base):
    __tablename__ = "mjd_products"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    merchant_id = Column(String(36), ForeignKey("mjd_merchants.id", ondelete="SET NULL"), index=True, nullable=True)
    outlet_id = Column(String(36), index=True, default="outlet-sudirman")
    name = Column(String(180), nullable=False)
    category = Column(String(64), default="Lain-lain")
    vendor = Column(String(120), default="MJD Kupi")
    price = Column(Float, default=0.0)
    cost = Column(Float, default=0.0)
    stock = Column(Integer, default=0)
    color = Column(String(16), default="#ffedd5")
    image_url = Column(Text, default="")
    modifiers = Column(JSON, default=list)
    # Variants: [{id, name (Panas/Ice), price, cost, active}] — overrides price/cost when chosen
    variants = Column(JSON, default=list)


class StockLog(Base):
    __tablename__ = "mjd_stock_logs"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    product_id = Column(String(36), index=True, nullable=False)
    outlet_id = Column(String(36), index=True, default="outlet-sudirman")
    quantity = Column(Integer, nullable=False)
    reason = Column(String(120), default="Adjust")
    kind = Column(String(24), default="in")  # in | out | opname
    note = Column(Text, default="")
    user_id = Column(String(36), index=True, nullable=True)
    user_name = Column(String(120), default="")
    created_at = Column(DateTime(timezone=True), default=utc_now)


class Expense(Base):
    __tablename__ = "mjd_expenses"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    category = Column(String(64), nullable=False)
    note = Column(Text, default="")
    amount = Column(Float, default=0.0)
    date = Column(String(32), default="")
    method = Column(String(32), default="Cash")
    outlet_id = Column(String(36), default="outlet-sudirman")
    user_id = Column(String(36), index=True, nullable=True)
    user_name = Column(String(120), default="")
    shift_id = Column(String(36), index=True, nullable=True)


class Sale(Base):
    __tablename__ = "mjd_sales"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    table_no = Column(String(32), default="Meja 01")
    subtotal = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    payment_method = Column(String(32), default="Cash")
    payment_reference = Column(String(120), default="")
    cash_received = Column(Float, default=0.0)
    change_amount = Column(Float, default=0.0)
    outlet_id = Column(String(36), default="outlet-sudirman", index=True)
    cashier_id = Column(String(36), index=True, nullable=True)
    shift_id = Column(String(36), index=True, nullable=True)
    status = Column(String(16), default="paid", index=True)  # paid | voided
    void_reason = Column(Text, default="")
    voided_at = Column(DateTime(timezone=True), nullable=True)
    lines = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)


class SelfOrder(Base):
    __tablename__ = "mjd_self_orders"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    table_no = Column(String(32), default="Meja 01")
    outlet_id = Column(String(36), index=True, default="outlet-sudirman")
    customer_name = Column(String(120), default="")
    total = Column(Float, default=0.0)
    notes = Column(Text, default="")
    status = Column(String(32), default="Pesanan Diterima", index=True)
    lines = Column(JSON, default=list)
    payment_proof = Column(Text, default="")
    payment_method = Column(String(32), default="")
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)


class KitchenOrder(Base):
    """Per-merchant kitchen ticket derived from a sale / self order."""
    __tablename__ = "mjd_kitchen_orders"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    source_id = Column(String(36), index=True, nullable=False)
    source_type = Column(String(16), default="sale")  # sale | self
    table_no = Column(String(32), default="Meja 01")
    outlet_id = Column(String(36), index=True, default="outlet-sudirman")
    merchant_id = Column(String(36), index=True, nullable=True)
    merchant_name = Column(String(120), default="MJD Kupi")
    status = Column(String(32), default="Diproses", index=True)
    lines = Column(JSON, default=list)
    sla_start = Column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now)


class Shift(Base):
    __tablename__ = "mjd_shifts"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    cashier_id = Column(String(36), index=True, nullable=False)
    cashier_name = Column(String(120), default="")
    outlet_id = Column(String(36), default="outlet-sudirman")
    opening_cash = Column(Float, default=0.0)
    closing_cash = Column(Float, default=0.0)  # physical cash counted at end
    expected_cash = Column(Float, default=0.0)
    variance = Column(Float, default=0.0)
    note = Column(Text, default="")
    status = Column(String(16), default="open", index=True)  # open | closed
    opened_at = Column(DateTime(timezone=True), default=utc_now)
    closed_at = Column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    __tablename__ = "mjd_settings"
    key = Column(String(64), primary_key=True)
    value = Column(JSON, default=dict)
    updated_at = Column(DateTime(timezone=True), default=utc_now)


Index("ix_kitchen_status_start", KitchenOrder.status, KitchenOrder.sla_start)
