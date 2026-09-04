# MJD Kupi — Product Requirements (Living Doc)

## Original problem
Aplikasi web POS & ERP Retail multi-tenant "MJD Kupi" dengan tema Clean White & Vibrant Orange. Modul: RBAC 4 role (Super Admin, Merchant Admin, Vendor, Kasir), Inventory/Stock, Expense, Costing/HPP, POS terminal, QR meja self-order, KDS, Shift kasir, Multi-channel payment, Printer configurator, WhatsApp notif per vendor, Laporan P&L konsolidasi. **White-Label SaaS** untuk mitra toko dengan branding kustom, subscription control, dan feature toggles.

## Architecture
- **Backend**: FastAPI + SQLAlchemy 2.0 async + asyncpg → **Supabase PostgreSQL (transaction pooler)**.
- **Frontend**: React 19 + Tailwind + Shadcn UI (Clean White / Vibrant Orange theme).
- **Auth**: JWT via HttpOnly cookies + Bearer token, bcrypt password hash, seeded 4 demo roles on startup.
- **Realtime**: Polling 3s (KDS) & 5s (Vendor Center) for MVP.
- **Storage**: 100% Supabase (localStorage removed as source of truth).

## User personas
1. **Super Admin (Platform Owner)** — Full access, konsolidasi laporan, White-Label mitra, Feature Toggle Matrix.
2. **Merchant Admin (Manager)** — CRUD produk/merchant, pengeluaran, laporan.
3. **Vendor / Tenant** — KDS + Pusat Vendor + Self-Service (branding auto mengikuti merchant).
4. **Kasir (Operator)** — POS + KDS + Shift management (menu dinamis by Feature Toggle).

## Core requirements (static)
- Multi-tenant produk terhubung ke `merchant_id`
- Kitchen tickets auto-split per merchant saat sale
- Shift kasir wajib dibuka sebelum transaksi
- Multi-channel payment (Cash/Transfer/QRIS)
- Live KDS dengan SLA color coding + chime
- Product variants dengan harga & HPP berbeda per varian
- Feature toggle per role & per outlet
- White-Label per merchant (logo, warna, banner, struk header/footer, wifi, subscription)

## Implemented (Feb 2026 - all iterations)

### Iteration 1-9 (Original session)
- [x] Migrasi lengkap MongoDB → Supabase Postgres (SQLAlchemy async + asyncpg)
- [x] RBAC ketat 4 role dengan seed 4 demo users
- [x] Login by username ATAU email
- [x] Multi-Outlet CRUD (Super Admin only)
- [x] Expense auto-binding ke user_id + user_name + shift_id
- [x] Direct Thermal Print via Web Bluetooth ESC/POS (58/80mm)
- [x] Merchant/Product/Inventory CRUD
- [x] POS multi-channel (Cash + Transfer + QRIS asli via qrcode.react)
- [x] Shift open/close + variance calculation + Rekap Shift + Print + WA
- [x] Monitoring Kasir real-time (Admin)
- [x] KDS live 3s polling + SLA color coding + chime WebAudio
- [x] Customer Self-Order `/self-order?table=NN` (no auth)
- [x] Laporan P&L Statement + Export CSV
- [x] Security Audit: CSRF X-Requested-With header, SEC-002 plain_password gate, SEC-003 vendor scope, SEC-005 server-side pricing

### Iteration 10 (11 injected features validated)
- [x] Bank Accounts CRUD (Setting `bank-accounts`) with JSON MutableDict fix via flag_modified
- [x] QRIS image upload (Setting `qris-image:{outlet}`)
- [x] PIN Auth 15-min for Void: `/api/admin/pin/generate`, embedded verify in `/api/sales/{id}/void`
- [x] Kasir History: `/api/pos/history` (outlet-scoped)
- [x] Strict Outlet Isolation on products/sales/expenses
- [x] Shift Lock: POST /api/sales requires open shift for Kasir
- [x] Cash Opname variance auto-compute at shift close
- [x] Offline Resilience: IndexedDB queue + auto-sync on reconnect
- [x] Payment Settings (bank + QRIS image)

### Iteration 11 (Feb 2026 batch #2 - NEW)
- [x] **Product Variants (multi-price/HPP)**: `Product.variants` JSONB; POS variant selector modal + notes; authoritative variant pricing in `create_sale` / `accept_self_order`
- [x] **User-friendly Sidebar**: Toggle collapse (icon-only mode) with localStorage persistence; scrollable independent nav (`overflow-y-auto`)
- [x] **Professional POS Cart**: Line breakdown (product · variant · notes · price × qty · subtotal), grand total with tax
- [x] **Super Admin Feature Toggle Matrix**: `/api/feature-toggles` GET/POST — per Role and per Outlet; sidebar auto-filters
- [x] **White-Label Partner Management**:
  - Merchant fields: `slug`, `logo_url`, `theme_color`, `banner_url`, `receipt_header`, `receipt_footer`, `wifi_password`, `subscription_status`, `subscription_expires_at`, `features_enabled`
  - Modal editor (Identitas & Domain, Branding Visual, Struk & Wi-Fi, Subscription, Paket Fitur SaaS)
  - `/api/branding/current` + `/api/branding/by-slug/{slug}` for dynamic theming
  - Login enforcement: `subscription_status='suspended'` blocks login with exact Indonesian message

### Iteration 12 (Feb 2026 Batch A — Enterprise Foundation)
- [x] **PPN / Tax Toggle Server-side (#7.3)**: `Setting.tax_config = {enabled, percent}`. `create_sale` recomputes tax authoritatively (client tax IGNORED). POS UI hides PPN line when disabled.
- [x] **Leading Zero Bug Fix (#8.1)**: Global `numOnFocus` helper applied via regex to all 15 `<input type="number">` — typing "2" in a "0" field yields "2" not "02".
- [x] **Multi-Outlet Consolidated (#1)**: outlet_scope() accepts "all" → returns None (no filter). Header outlet switcher offers "🏢 Semua Outlet (Konsolidasi)" for Super Admin/Admin, plus "+ Tambah Outlet Baru…" shortcut. Kasir/Vendor forced to own outlet_id (RBAC).
- [x] **Enterprise Dashboard (#2)**: Complete overhaul with Recharts:
  - 4 KPI cards (Penjualan, Transaksi/Basket, Laba Bersih/Margin, Pengeluaran) with growth badges & tabular numbers
  - Sales Trend (AreaChart) with **Jam / Harian** dual-mode toggle
  - Payment Method donut (PieChart, 30 days)
  - Low Stock red-bordered panel + Top 5 Products progress bars + Quick Actions
  - Outlet Comparison BarChart (shown when "Semua Outlet" active)
  - Backend: `/api/dashboard/analytics?mode=daily|hourly&outlet_id=` returns kpi/trend/payment_breakdown/top_products/low_stock/outlet_compare
- [x] **Global Ops Status Bar**: "POS: Online · Shift: Active (Budi)" indicator in top header with pulsing green dot

### Iteration 13-14 (Feb 2026 Batch B — Customer-Facing & Ops)
- [x] **Self-Order Mobile Overhaul (#4)**: GoFood-style redesign
  - Hero header dengan banner branding + logo bulat + "Buka - Menerima Pesanan" pulsing dot
  - Sticky search bar + horizontal category tabs
  - Product cards HD image + vendor badge + variant "Mulai Rp X" pricing hint
  - Floating bottom cart bar (fixed) dengan "[X] Item · Total · Lanjut ke Pembayaran →"
  - Variant selection drawer (bottom sheet) dengan pilihan + Catatan Khusus
  - Checkout drawer dengan Nama + WhatsApp (required) + itemized breakdown + payment method
  - Payment: QRIS Toko / Transfer Bank / Bayar di Kasir + upload bukti
  - Order tracking stepper (4-langkah) dengan icon + real-time status polling 4s
  - Digital receipt summary di halaman tracking
- [x] **QR Meja Custom Domain (#5)**: Config Base URL + Store ID/Slug + Outlet Target
  - Preview URL live dengan format `{baseURL}/self-order?store_id=X&outlet_id=Y&table=NN`
  - Auto re-render semua QR saat Base URL berubah, localStorage persistence
  - Print-ready cards dengan brand logo, MEJA XX, CTA scan, level="H" QR
  - Tombol "Cetak Semua QR (PDF)" mass print via CSS media print
- [x] **Notification Center (#3)**: Bell icon di header dengan badge counter
  - Backend `/api/notifications` aggregate: stock kritis + shift closing + pesanan baru (max 10 items after sort)
  - Slide-over drawer dari kanan dengan kategori icon + severity color (critical/warning/info)
  - Timeago labels ("baru saja", "5m lalu", "2j lalu")
  - Click item → jump ke halaman terkait (inventory/cashiers/pos)
  - Polling 15 detik + button "Tandai Semua Dibaca"
- [x] **Printer Settings Dedicated Menu (#7.2)**: Menu 🖨️ standalone
  - Status koneksi card (Terhubung/Terputus) dengan nama printer
  - Ukuran kertas 58mm/80mm selector
  - Alokasi role Kasir / Dapur / Barista dropdown
  - Web Bluetooth pair + Test Print + Panduan konfigurasi
  - Accessible untuk Kasir & Admin (bukan cuma Super Admin)
- [x] **Backend fixes iter13→14**: accept endpoint status allow-list expanded, `customer_phone` column + persistence, notifications truncated to 10

## Testing status
- **iter10**: 25/25 backend tests PASSED
- **iter11**: 15/15 backend tests PASSED
- **iter12**: 9/9 backend tests PASSED
- **iter13-14**: 8/8 backend tests PASSED + 3 critical bugs fixed
- **Regression**: **57/57 total** when run sequentially
- **Frontend**: verified via screenshot — Self-Order mobile (hero + cart), Notification Drawer (10 items), QR Config form + branded cards, Printer Settings menu

## Test credentials
See `/app/memory/test_credentials.md`.

## Backlog (P1/P2)
- **P1 REFACTORING**: Split `server.py` (~1813 lines) → routers/{auth, products, sales, merchants, settings, branding, kds, shifts}.py. Split `App.js` (~1900 lines) → components/pages folder structure.
- P1: Immediate subscription lockout — add `subscription_status` check inside `current_user()` dependency, not just at login (currently allows session until token expires).
- P1: Fix tax bypass loophole (allow client tax=0) — enforce server-computed tax always.
- P1: Wrap Setting.value & Product.variants with `MutableDict.as_mutable(JSON)` to prevent alias mutation bugs.
- P1: Alembic migrations replacing metadata.create_all + ALTER TABLE IF NOT EXISTS.
- P2: Supabase Realtime channels replace polling.
- P2: Guard prevent last Super Admin toggle/delete + audit log entries.
- P2: Real QRIS Xendit/Midtrans integration.
- P2: Multi-outlet per merchant slug routing (slug detection via subdomain/query param).
- P2: Loyalty / member program, E-invoice, Faktur pajak.
