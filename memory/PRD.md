# MJD Kupi — Product Requirements (Living Doc)

## Original problem
Aplikasi web POS & ERP Retail multi-tenant "MJD Kupi" dengan tema Clean White & Vibrant Orange. Modul: RBAC 4 role (Super Admin, Merchant Admin, Vendor, Kasir), Inventory/Stock, Expense, Costing/HPP, POS terminal, QR meja self-order, KDS, Shift kasir, Multi-channel payment, Printer configurator, WhatsApp notif per vendor, Laporan P&L konsolidasi.

## Architecture
- **Backend**: FastAPI + SQLAlchemy 2.0 async + asyncpg → **Supabase PostgreSQL (transaction pooler)**.
- **Frontend**: React 19 + Tailwind + Shadcn UI (Clean White / Vibrant Orange theme).
- **Auth**: JWT via HttpOnly cookies + Bearer token, bcrypt password hash, seeded 4 demo roles on startup.
- **Realtime**: Polling 3s (KDS) & 5s (Vendor Center) for MVP.
- **Storage**: 100% Supabase (localStorage removed as source of truth).

## User personas
1. **Super Admin (Holding Owner)** — Full access, konsolidasi laporan.
2. **Merchant Admin (Manager)** — CRUD produk/merchant, pengeluaran, laporan.
3. **Vendor / Tenant** — KDS + Pusat Vendor + Self-Service.
4. **Kasir (Operator)** — POS + KDS + Shift management.

## Core requirements (static)
- Multi-tenant produk terhubung ke `merchant_id`
- Kitchen tickets auto-split per merchant saat sale
- Shift kasir wajib dibuka sebelum transaksi
- Multi-channel payment (Cash/Transfer/QRIS)
- Live KDS dengan SLA color coding + chime
- WA click-to-chat per merchant untuk tiket dapur
- Printer thermal 58/80mm, split kitchen toggle

## Implemented (Feb 2026, this session)
- [x] Migrasi lengkap MongoDB → Supabase Postgres (SQLAlchemy async + asyncpg, statement_cache_size=0)
- [x] RBAC ketat 4 role: Super Admin (full + users + settings), Admin (management + monitoring, no system config), Kasir (POS + expense + KDS only), Vendor (KDS + vendor center + self-service)
- [x] Login by **username** ATAU email (Super Admin default: `superadmin` / `.Superadmin1_`)
- [x] User & Security Management (Super Admin only): list + create + reveal plain_password + reset + toggle active + delete
- [x] Multi-Outlet CRUD (Super Admin only) dengan phone/alamat untuk header struk
- [x] Logo upload otomatis muncul di sidebar/dashboard/struk thermal
- [x] Expense **auto-binding** ke user_id + user_name + shift_id dari session (anti-forge)
- [x] **Direct Thermal Print via Web Bluetooth ESC/POS** (58/80mm): buildSaleReceipt, buildShiftReport, buildKitchenTicket, tanpa dialog browser
- [x] Model DB: users (+ username/plain_password/active), outlets (+ phone), merchants, products (+ image_url), stock_logs, expenses (+ user_id/user_name/shift_id), sales, self_orders (+ payment_method/proof), kitchen_orders, shifts, settings
- [x] Merchant CRUD + sinkron ke produk vendor
- [x] Product CRUD dengan upload gambar (base64 data URL)
- [x] Inventory: Barang Masuk / Keluar / Opname
- [x] POS multi-channel (Cash + kembalian, Transfer + ref, QRIS QR asli + upload bukti)
- [x] Shift open/close + variance kalkulasi + Modal Rekap Shift format receipt + Print + Kirim WA
- [x] Monitoring Kasir real-time (Admin) dengan total_cash, total_transfer, transaction_count per shift
- [x] Data isolation kasir: sales list hanya shift aktif si kasir
- [x] KDS live 3s polling + SLA color coding + chime WebAudio
- [x] Real QR Code (qrcode.react QRCodeSVG) untuk QR Meja pelanggan
- [x] Customer public route `/self-order?table=NN` (no auth) checkout + QRIS + upload bukti
- [x] Menu Pesanan Online di POS: badge + modal + approve → stock deduction + KDS tickets
- [x] Laporan P&L Statement + Export CSV
- [x] Seed otomatis: 4 merchants, 6 products, 4 demo users, 2 outlets, 2 expenses
- [x] Test coverage: 22/22 iter7 backend passed, 100% frontend RBAC + User Mgmt + Settings verified

## Backlog (P1/P2)
- P1: Split server.py (1238 lines) → routers (auth/pos/kds/admin/settings), split App.js (1345 lines) → src/pages/
- P1: ENV flag `ALLOW_PLAIN_PASSWORD_VIEW` untuk gate plain_password endpoint di production
- P1: Guard: prevent last Super Admin toggle/delete + audit log entries
- P1: Real QRIS Xendit/Midtrans integration
- P1: Admin expense binding ke active shift kasir (currently hanya kasir auto-bind)
- P2: Alembic migrations replacing metadata.create_all + ALTER TABLE IF NOT EXISTS
- P2: Supabase Realtime channels replace polling
- P2: Fix legacy test_mjd_kupi_full.py test-order isolation issues (pytest_order or clean fixtures)
- P2: Loyalty / member program, E-invoice, Faktur pajak
