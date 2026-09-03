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
- [x] Model DB: users, outlets, merchants, products, stock_logs, expenses, sales, self_orders, kitchen_orders, shifts, settings
- [x] Auth 4 role + JWT cookie + bearer
- [x] Merchant CRUD (RBAC-gated) + sinkron ke produk vendor
- [x] Product CRUD (bind ke merchant_id + delete)
- [x] Inventory: Barang Masuk / Keluar / Opname (stock_logs terpisah)
- [x] Expenses CRUD dengan kategori & metode
- [x] POS multi-channel payment (Cash + kembalian, Transfer + ref, QRIS dinamis)
- [x] Kasir shift open/close + variance kalkulasi otomatis (opening + cash_sales vs closing)
- [x] Kitchen Display System (KDS) live, polling 3s, SLA hijau/kuning/merah, chime WebAudio, status Diproses → Siap → Selesai
- [x] Receipt modal dengan split kitchen ticket + WhatsApp share (wa.me) per merchant + tombol cetak
- [x] Self-service QR (tanpa auth) + auto kitchen ticket
- [x] Printer settings (58/80mm, USB/BT/Network, auto-print, split kitchen) tersimpan di Supabase
- [x] Laporan P&L Statement + Export CSV
- [x] Seed otomatis: 4 merchants, 6 products, 4 demo users, 2 outlets, 2 expenses
- [x] Test coverage: 18/18 backend pytest passed, 100% frontend flows validated

## Backlog (P1/P2)
- P1: Optimistic banner update on shift-open (currently waits for next 3s poll)
- P1: Refactor server.py (889 lines) into router modules
- P1: Real QRIS payment gateway integration (Xendit / Midtrans)
- P1: Real thermal printer driver (Web Bluetooth / ESC-POS)
- P2: Alembic migrations replacing metadata.create_all
- P2: Supabase Realtime channels (currently polling)
- P2: Loyalty / member program
- P2: E-invoice / faktur pajak
