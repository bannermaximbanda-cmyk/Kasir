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
- [x] Model DB: users, outlets, merchants, products (+ image_url), stock_logs, expenses, sales, self_orders (+ payment_method + payment_proof), kitchen_orders, shifts, settings
- [x] Auth 4 role + JWT cookie + bearer
- [x] Merchant CRUD (RBAC-gated) + sinkron ke produk vendor
- [x] Product CRUD dengan upload gambar (base64 data URL)
- [x] Inventory: Barang Masuk / Keluar / Opname
- [x] Expenses CRUD dengan kategori & metode
- [x] POS multi-channel payment (Cash + kembalian, Transfer + ref, QRIS QR asli + upload bukti)
- [x] Kasir shift open/close + variance kalkulasi otomatis
- [x] Modal Rekap Shift lengkap format receipt style + tombol Print + Kirim WhatsApp
- [x] Monitoring Kasir (Admin): list shift real-time dengan total_cash, total_transfer, transaction_count
- [x] Data isolation kasir: GET /api/sales hanya returns shift aktif si kasir
- [x] Kitchen Display System live 3s polling + SLA color coding + chime WebAudio
- [x] Real QR Code (qrcode.react QRCodeSVG) untuk QR Meja pelanggan (URL /self-order?table=NN)
- [x] Customer public route /self-order (no auth) dengan checkout + QRIS asli + upload bukti
- [x] Menu Pesanan Online di POS: badge notifikasi + modal setujui + auto stock deduction + KDS tickets
- [x] Kitchen tickets split per merchant otomatis saat kasir approve/POS sale
- [x] Receipt modal dengan split kitchen ticket + WhatsApp share (wa.me) per merchant + tombol cetak
- [x] Self-service QR + auto flow ke antrean POS kasir
- [x] Printer settings (58/80mm, USB/BT/Network, auto-print, split kitchen)
- [x] Laporan P&L Statement + Export CSV
- [x] Seed otomatis: 4 merchants, 6 products, 4 demo users, 2 outlets, 2 expenses
- [x] Test coverage: 29/29 backend pytest (iterasi 6), 100% frontend flows

## Backlog (P1/P2)
- P1: Optimistic shift banner update (currently waits for 3s poll)
- P1: Refactor server.py (1049 lines) into router modules (auth/pos/kds/shifts/settings)
- P1: Refactor App.js (1171 lines) — extract komponen ke src/pages
- P1: Real QRIS payment gateway integration (Xendit / Midtrans dengan verifikasi otomatis)
- P1: Real thermal printer driver (Web Bluetooth / ESC-POS commands)
- P1: Shift report scope date range (currently includes semua expense/pending)
- P2: Alembic migrations replacing metadata.create_all
- P2: Supabase Realtime channels (ganti polling)
- P2: Loyalty / member program
- P2: E-invoice / faktur pajak
