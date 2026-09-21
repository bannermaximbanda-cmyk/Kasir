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

### Iteration 15 (Feb 2026 — CRITICAL BUG FIX + Self-Service Management + Outlet Picker)
- [x] **BUG FIX (URGENT)**: QR self-orders NOW appear in POS "Pesanan Online" modal (backend already correct; RCA in iter15 report confirmed 12/12 test pass + kasir at outlet-sudirman sees exact order #34956F85)
- [x] **Notification click → auto-open OnlineOrdersModal**: Klik notif type='order' langsung setPage('pos') + setShowOnlineOrders(true) untuk terima/tolak
- [x] **Reject Pesanan endpoint**: `POST /api/self-order/{id}/reject` dengan JSON body `{reason}`, status jadi "Ditolak", tidak muncul lagi di queue
- [x] **Self-Service Management per outlet (`/api/outlets/{outlet_id}/self-service`)**:
  - Banner Promo carousel (multi-upload dataURL, auto-rotate 4.5s)
  - Marquee text berjalan (running text di atas hero)
  - Logo & Header image upload
  - Force closed toggle + custom closed_message override shift
  - Halaman "Pengaturan Self-Service & QR Meja" dengan outlet selector dropdown, Preview Order link
- [x] **Public outlets endpoint `/api/public/outlets`**: List outlet aktif tanpa auth
- [x] **Customer Self-Order Outlet Picker**: Header dropdown yang bisa switch outlet on-the-fly, fetch menu+banner+status outlet baru dinamis
- [x] **UI POS Online Orders enhanced**: Menampilkan customer_name + phone badge, variant chip, notes, tombol "Tolak Pesanan" + "Terima & Kirim ke Dapur" (bukan lagi 1 tombol)

### Iteration 16 (Feb 2026 — Buka Shift Bug Fix + Modal UI/UX)
- [x] **BUG FIX Buka Shift 400 error (root cause)**: Frontend mengirim IDR-formatted string ("Rp 500.000") → Pydantic int validation gagal
- [x] **Frontend sanitize**: `parseIDR()` helper strip semua non-digit sebelum kirim `Number`
- [x] **Try/catch + Toast friendly**: Tidak lagi runtime error overlay; menampilkan pesan Indonesia
- [x] **Idempotency**: Kalau shift sudah aktif, otomatis fetch `/shifts/current` dan reuse (bukan blokir user)
- [x] **Auto-format IDR mask**: Typing "500000" jadi "Rp 500.000" real-time
- [x] **Quick Nominal buttons**: [Rp 100rb] [Rp 200rb] [Rp 500rb] [Rp 1.000.000] dengan state active
- [x] **Shift Context Card**: Kasir Aktif (Dina Kasir), Outlet (Outlet Sudirman), Waktu Mulai (Sabtu, 5 Sept 2026 · 04.34 WIB) — gradien orange
- [x] **Loading state**: Tombol submit disabled + spinner "Membuka shift…" saat request

### Iteration 17 (Feb 2026 — Notification/POS Query Alignment)
- [x] **BUG FIX (frontend root cause)**: `useEffect` di App.js line 128-175 punya premature `return` yang menghentikan setup polling `reloadOnlineOrders` — akibatnya modal Pesanan Online SELAMANYA menampilkan array kosong meski data ada di backend.
- [x] **Fix**: Konsolidasi return cleanup — semua timer (notif + online orders) dibersihkan di satu return handler
- [x] **Notification click → auto-scroll ke order** dengan flash highlight animation
- [x] **Preventive**: Extracted `PENDING_SELF_ORDER_STATUSES` shared constant untuk mencegah divergensi status filter di masa depan
- [x] **Dual action buttons**: [Tolak Pesanan] + [Terima & Kirim ke Dapur] di modal Pesanan Online

### Iteration 18 (Feb 2026 — Concurrency Guard Multi-Click)
- [x] **BUG FIX (double-click duplicate transactions)**: Race condition di accept/reject endpoint dieliminasi
- [x] **Atomic UPDATE ... WHERE status IN pending** — hanya 1 dari 5 concurrent request menang; sisanya 409 "double-click terblokir"
- [x] **Rollback pada shift-closed error**: status kembali ke "Pesanan Diterima" sehingga kasir bisa retry setelah buka shift
- [x] **Frontend instant lock**: `processing[id]` state + optimistic hide (order hilang dari UI sebelum response) + spinner "Memproses…" pada tombol
- [x] **Reject guard tightened**: `.notin_(["Ditolak","Selesai","Diterima","Diproses","processing"])` mencegah reject atas order yang sudah accepted
- [x] **Testing_agent iter18**: 4/4 concurrency test PASSED — 5 parallel accept via `threading.Barrier` → exactly 1×200 + 4×409 + 1 Sale row

## Testing status
- **iter18**: 4/4 concurrency backend PASSED (multi-thread atomic guard verified) + regression 83/83 baseline
- **iter19 (Batch C — Feb 2026)**: Vendor Settlement Center, Advanced Inventory Mutations, Excel Import/Export, Sound Notification — all endpoints tested via curl:
  - POST /api/products/bulk-import → 200 (created/updated counters)
  - POST /api/settlement/payouts → 200 (Rp 2.790.900 net for m-barista Sept 1-5)
  - GET /api/settlement/preview → 200 (4 merchants breakdown with per-merchant commission scheme)
  - GET /api/settlement/payouts → 200 (ledger list)
  - POST /api/inventory/stock-movements → 200 (delta +5, audit stock_before → stock_after)
  - GET /api/inventory/stock-movements → 200
  - POST /api/settings sound_config → 200 & GET returns same value
- **Cumulative**: **101/94+ total** (iter10-19)
- **Frontend**: verified via screenshot — Inventory tabs (Stok/Mutasi/Excel) + Settlement per-merchant + Payout Ledger + PayoutConfirm modal + SoundSettings switch

## Iteration 25 (Feb 2026 — Multi-Outlet Isolation & Cascade Validation)
- [x] **P0 · User outlet_id binding fix**: Form state default `outlet_id: ""` (bukan hardcoded sudirman) + placeholder "— Pilih Outlet —" + required validation. Save handler validates outlet exists di list terkini sebelum kirim. Backend `POST /api/admin/users` validasi ketat: outlet wajib untuk role non-Super, harus exist, harus `active=true`.
- [x] **P0 · Login Cascade Guard**: Backend `/api/auth/login` block user non-Super-Admin kalau outlet_id-nya sudah dihapus (403 "sudah dihapus") atau dinonaktifkan (403 "dinonaktifkan"). Super Admin exempt.
- [x] **P0 · Shift Open Guard**: Backend `POST /api/shifts/open` validasi `user.outlet_id` exists + active. Frontend Modal Buka Shift menampilkan warning banner + disable tombol "Mulai Shift" kalau outlet missing/inactive. Text tombol berubah jadi "Outlet tidak valid".
- [x] **P1 · Outlet Soft-Delete + Cascade**: `DELETE /api/outlets/{id}` sekarang soft-delete (`active=false`) — bukan destroy. Auto-deactivate semua user yang terikat outlet tersebut. Query `?hard=1` support hard-delete tapi block kalau ada transaksi/shift. Response: `{mode, affected_users}`. Frontend tombol "Hapus" → "Nonaktifkan"/"Aktifkan" toggle dengan confirm dialog jelas.
- [x] **P1 · Outlet Dropdown Filtering**: `GET /api/outlets` default hanya active. Super Admin bisa `?include_inactive=1` untuk manage. Frontend App state pakai include_inactive untuk Super Admin, hidden untuk role lain. Settings Cabang page pakai include_inactive supaya bisa reaktivasi.
- [x] **P2 · Product "Berlaku di Semua Outlet"**: Product `outlet_id` sekarang nullable (`NULL ⇒ global`). Migration ALTER TABLE `DROP NOT NULL` + `DROP DEFAULT`. Backend `create_product`: kalau `outlet_id in (None,"","all")` dan role=SuperAdmin → simpan sebagai global. Admin tetap dibatasi ke outletnya. List query pakai `outlet_id = scope OR outlet_id IS NULL OR outlet_id = ''` — global product tampil di setiap outlet.
- [x] **Frontend Product Form**: Toggle "🌐 SEMUA OUTLET / 🏪 SPESIFIK OUTLET" (Super Admin only). Saat toggle aktif, dropdown Outlet Target auto-hide dan outlet_id dikirim `null`.
- [x] **Loading & Notif States**: Save handler user + product punya `saving` state → tombol berubah "Menyimpan…" + toast success ✅ / error ❌ dengan detail dari backend.
- [x] **Testing**: `testing_agent` iteration_21 **19/19 pass** — verify semua edge case (user outlet validation, login cascade, outlet soft-delete + user auto-deactivate, shift open guard, product global visibility di setiap outlet, regression Batch C/D masih OK).


- [x] **Relocate Kode Otorisasi Kasir**: `<PinGenerator/>` dihapus dari page "User & Security" (fokus CRUD user saja), dipindah ke **Monitoring Kasir** di atas metric grid. Section header diperbarui: "Pantau kasir aktif, riwayat shift, dan generate kode otorisasi untuk approve void/edit." Fungsionalitas generate 15-min PIN tetap berjalan dari lokasi baru (verified: ZF727B generated).
- [x] **Remove Quick Demo Accounts (Production Hardening)**: Blok `.demo-accounts` dengan 4 tombol preset (Super Admin/Admin/Kasir/Vendor) **completely removed**. Login state default `email` & `password` sekarang kosong string — mencegah one-click access di production. Placeholder helpful "username atau email" / "Masukkan password" + autocomplete `username`/`current-password` untuk password manager compat. Empty submit sekarang tampilkan error "Username / Email dan Password wajib diisi." + trim `email` sebelum kirim ke backend.
- [x] **Verified via screenshot**: (1) Login page bersih tanpa demo section, (2) User & Security tidak ada PIN card, (3) Monitoring Kasir menampilkan PIN card di top + generate button functional.


- [x] **Printer Settings — Kustomisasi Struk**: Panel baru "Kustomisasi Struk" dengan:
  - Logo upload (PNG/JPG) → auto-resize + threshold @128 grayscale → **monokrom bitmap** siap ESC/POS
  - Rekomendasi label dinamis: "Maks lebar 384px (58mm) / 576px (80mm)" mengikuti pilihan kertas
  - Header Struk textarea (alamat, telp, WiFi) & Footer Struk textarea (thank you, IG)
  - Disimpan sebagai `Setting.printer_config = {logo_url, logo_w, logo_h, header, footer}`
  - `buildSaleReceipt()` di `thermalPrinter.js` sekarang menyisipkan header custom setelah nama outlet & footer custom sebelum cut (fallback ke default)
- [x] **Merchant Commission Scheme Selector**: Form Tambah + White-Label Modal keduanya punya:
  - Dropdown Tipe Komisi: `Persentase (%)` | `Nominal Tetap (Rp / item)`
  - Conditional field: `commission_percent` atau `commission_fixed`
  - Preview live "10% dari harga jual" atau "Rp 1.000 / item"
  - Kolom tabel Merchant: "Skema Komisi" menampilkan format sesuai type
  - Backend settlement `_compute_settlement_breakdown` sudah honoring scheme (verified: 193 items × Rp 2.000 = Rp 386.000 exact)
- [x] **PIN Menu Standalone + Feature Toggle**:
  - `<PinGenerator/>` dipindah ke User & Security page paling atas (prominent section)
  - Tetap muncul juga di Pengaturan Sistem untuk backward compat
  - `FEATURE_LIST` tambah entry `cashier_pin` — Super Admin bisa disable per role/outlet dari Feature Access Control
  - Panel `pin-generator-panel` menampilkan badge merah "🔒 Modul Dinonaktifkan" + tombol disabled saat toggle off
  - Prop `pinDisabled={!isFeatureAllowed("cashier_pin")}` diteruskan real-time ke both PinGenerator instance


- [x] **Dynamic Branding Text (Nama + Subtitle)**: `<BrandingTextSettings/>` component di Pengaturan Sistem (Super Admin only) dengan input Nama Usaha & Subtitle/Tagline + preview live. Disimpan sebagai `Setting.branding_text = {name, subtitle}`.
- [x] **Dynamic rendering**: Sidebar brand-text, topbar breadcrumb, dan login screen (nama + tagline uppercase + tombol "Masuk ke {brand}") semuanya membaca `brandingText` state — di-fetch pada mount + auto-update via `onBrandingTextSaved` callback tanpa reload.
- [x] **Fix Feature Toggle Bug #1 (Key Mismatch)**: `FEATURE_LIST` diselaraskan dengan `NAV_ITEMS` id (`self-service`, `vendor-center`, dst) + tambah entry `overview` & `printer` yang sebelumnya hilang. Sekarang toggle benar-benar match saat filter sidebar.
- [x] **Fix Feature Toggle Bug #2 (No Real-Time Sync)**: Save handler `FeatureToggleMatrix` sekarang trigger callback `onFeatureToggleSaved` yang re-fetch `/api/feature-toggles` di App state → `featureMatrix` refresh langsung → `isFeatureAllowed()` sidebar filter langsung diperbarui tanpa perlu logout.
- [x] **UX quick-actions**: Tombol "Aktifkan Semua" & "Matikan Semua" per target (role/outlet) untuk konfigurasi lebih cepat.
- [x] **Verified via screenshot**: Save "Warung Kopi Bang Jul · Ngopi Yuk!" → sidebar, topbar, login page update real-time; Save Vendor role dengan hanya KDS ON → login sebagai Vendor menampilkan sidebar **satu item saja (Kitchen Display)**.


- [x] **Fixed viewport container**: `.menu-scroll` (POS) & `.csa-scroll` (Self-Order) dengan `max-height: calc(100vh - Xpx)` + `overflow-y: auto`. Header, search bar, category tabs, dan cart panel tetap terlihat penuh saat browsing menu.
- [x] **Pagination bar reusable** (`<PaginationBar/>`): "Menampilkan X-Y dari Z menu" + tombol `‹ Sebelumnya`, page numbers with ellipsis (contoh: `[1] [2] [3] … [10]`), `Selanjutnya ›`. Active page highlighted vibrant orange.
- [x] **`usePagination` hook**: default 12 items/page, auto-reset ke page 1 saat search query / kategori berubah / total items berubah (dependency array).
- [x] **Compact 4-column grid POS Desktop**: `.pos-layout .product-grid { grid-template-columns: repeat(4, 1fr); }`; step-down ke 3 col @1280px & 2 col @1000px & mobile.
- [x] **Cart panel POS**: `max-height: calc(100vh - 180px); overflow: hidden` + `.cart-items { overflow-y: auto }` — panel tetap sticky sementara isi keranjang scrollable.
- [x] **Custom scrollbar styling**: `::-webkit-scrollbar-thumb { background: #d5dbe1 }` dengan orange hover state.
- [x] **Verified via screenshot**: 12 produk POS di page 1, click ke page 2 tampil produk ke-13 (`TEST_Reactivated`), search "kopi" reset ke page 1 dengan 1 hasil. Self-Order Mobile scroll internal berjalan mulus.


- [x] **Search & Filter Bar (sticky)**: Search by name/SKU, Kategori dropdown, Merchant dropdown, Status tabs (Semua/Aktif/Tidak Aktif) with live counters
- [x] **CSV Template + Excel Import/Export**:
  - "Unduh Template CSV" (BOM-safe UTF-8) with columns nama_produk, sku, merchant_id, kategori, harga_jual, hpp_per_porsi, stok_awal, outlet_id, is_active
  - "Export Data" → xlsx with 11 columns including varian count
  - "Import Produk" modal with preview (first 20 rows), inline error report, SKU dedup on client + backend, upsert order: id → sku(+outlet) → name(+outlet)
- [x] **Full Edit Modal (Pencil icon)**: Name, SKU, Merchant, Category, Price, HPP, Stock, Image re-upload, is_active toggle, Variants CRUD (name/price/cost/active)
- [x] **is_active toggle**: on card (switch) + in modal (large switch with descriptive label); auto-notifies "hilang dari POS & self-order"
- [x] **Strict visibility rules (backend enforced)**:
  - Anonymous `/api/products?outlet_id=X` → strictly `is_active=true`
  - Auth Kasir/Vendor default → strictly `is_active=true`
  - Admin/Super Admin catalog page `?include_inactive=1` → sees ALL with "TIDAK AKTIF" badge
  - Frontend also filters POS grid & self-order via `p.is_active !== false`
- [x] **Backend changes**: `Product.sku` + `Product.is_active` columns (+ index), migrated via ALTER TABLE; `ProductInput` + `BulkProductRow` extended; SKU-first matching in bulk import
- [x] **Tests**: iteration_20 = 16/16 pass (SKU dedup, admin-isolation, visibility rules, regression: sales→stock-movement, shift expenses, settlement, sound_config)


## Iteration 19 (Feb 2026 Batch C — Vendor Settlement + Advanced Inventory + Excel + Sound)
- [x] **Vendor Settlement Center (#7.1)**: New tabbed VendorCenter with Antrean Order | Settlement per Merchant | Riwayat Payout
  - Per-merchant breakdown honoring `commission_scheme` (percent/fixed) & `commission_fixed`
  - Custom period picker (from/to) → auto recompute gross/commission/net
  - "Bayar →" button per merchant → PayoutConfirmModal → POST /api/settlement/payouts ledger
  - Riwayat Payout table with created_at, period, item_count, gross, net, status
- [x] **Advanced Inventory Mutations (#8.2)**: New tabbed Inventory with Ringkasan Stok | Mutasi Stok | Import/Export Excel
  - Full audit trail via `StockMovement` model (kind: in/out/opname/sale/adjust, delta, stock_before, stock_after, operator, ref_id)
  - Auto-hooked in `create_sale` (kind="sale", ref_id=sale.id) & `adjust_stock` (mirrors StockLog)
  - Filter by product & kind, tone-coded delta (green up / red down), timeago format
- [x] **Excel Import/Export (#8.3)**: Client-side `xlsx` library reads .xlsx/.xls/.csv
  - Export: current catalog with 10 columns (id, name, category, vendor, merchant_id, outlet_id, price, cost, stock, color)
  - Import: upsert mode matches by id OR name+outlet_id; column aliases (Nama/Kategori/Harga/HPP/Stok) supported
  - Template download button for user onboarding
  - Backend `/api/products/bulk-import` with per-row error collection & RBAC (Admin only touches own outlet)
- [x] **Sound Notification Settings (bonus)**: New SoundSettings panel in Pengaturan Sistem
  - Toggle enabled/disabled + volume slider (0-100%)
  - Sub-toggles: chime_new_order + chime_kds_ready
  - Tes Chime button (2-note WebAudio sine wave)
  - Persisted in `Setting.sound_config` + localStorage mirror

## Test credentials
See `/app/memory/test_credentials.md`.

## Iteration 26 (Feb 2026 — Dynamic POS Checkout Modal per Outlet)
- [x] **POS `PaymentModal` outlet-aware**: menerima prop `outletId` + `outletName` dari App state (kasir → `session.outlet_id`; Admin/Super Admin → `activeOutlet` fallback ke session).
- [x] **Dynamic bank accounts**: fetch dari `/api/settings/bank-accounts?outlet_id={outletId}`; dropdown "Pilih rekening tujuan" menampilkan semua rekening outlet + kartu detail (bank, no. rekening, atas nama) dengan tombol **Salin**. Empty-state hint yang jelas jika belum ada rekening.
- [x] **Dynamic QRIS image**: fetch dari `/api/settings/qris-image:{outletId}`; jika ada → tampilkan gambar; fallback ke `QRCodeSVG` dinamis (`MJDKUPI|OUTLET:{id}|AMOUNT|TS`).
- [x] **Real-time sync via BroadcastChannel**: `PaymentModal` mendengarkan `payment-settings-updated` — perubahan bank/QRIS di `PaymentSettings` langsung tercermin di modal kasir tanpa reload.
- [x] **Offline fallback**: LocalStorage cache `app_payment_settings_{outletId}` diprioritaskan untuk render instan + badge "📴 Data pembayaran outlet dari cache offline" saat network fail.
- [x] **Reference format**: Transfer method sekarang menyimpan reference sebagai `{bank}-{account} · {ref}` sehingga struk & rekonsiliasi lebih informatif.
- [x] **Bug fix (compile blocker)**: `SettingsPage` menghapus prop `outlets` duplikat yang bentrok dengan state internal.

## Iteration 27 (Feb 2026 — CRITICAL FIX: PaymentSettings Outlet Mismatch)
**Bug**: Saat Super Admin memilih "MJD Banda Aceh" di dropdown, data rekening & QRIS malah tersimpan ke "MJD Sudirman"; label upload & note tetap menampilkan Sudirman.
**Root causes**:
1. **Backend** `POST /api/settings/bank-accounts` diam-diam fallback ke `user.outlet_id` bila `outlet_id` param kosong → Super Admin selalu menyimpan ke outletnya sendiri (Sudirman).
2. **Frontend** `outletName` diambil dari prop `outlets` (mungkin kosong/stale) alih-alih dari `availableOutlets` (source-of-truth dropdown), sehingga label tak sinkron dengan pilihan aktif.
3. Tidak ada broadcast saat load selesai → POS di outlet lain tak tahu data outletnya sudah berubah.

**Fixes**:
- [x] **Backend hardening**: Super Admin WAJIB kirim `outlet_id` eksplisit (400 bila kosong / spasi). Admin tetap fallback ke outletnya sendiri. Endpoint sekarang juga validasi outlet exists + `active=true`.
- [x] **Frontend**:
  - Rename `outletId` → `selectedOutletId` (per user request), dengan initializer dari localStorage + validasi outlet masih valid di `availableOutlets`.
  - `activeOutletName` di-derive dari `availableOutlets` (dropdown source) dengan fallback → selalu match dengan pilihan visual.
  - `switchOutlet(nextId)` explicit handler — reset `banks`/`qrisImg`/`form`/`fileInputKey` sebelum load supaya tidak ada stale UI.
  - `add()`, `remove()`, `handleQris()` capture `oid = selectedOutletId` di awal async — nolkan risiko stale closure. `outlet_id` juga dikirim di body sebagai double-safety.
  - `load()` menerima `targetOutletId` argument + guard untuk discard result kalau user sudah pindah outlet lagi selama fetch (anti-race).
  - Setiap load → broadcast `payment-settings-updated { outlet_id, accounts, qris }` supaya POS di outlet manapun langsung sinkron.
  - `<input type=file key={fileInputKey}>` — force remount saat outlet switch supaya file lama tak tercarry.
  - Badge "📍 {NamaOutlet}" + attribut `data-active-outlet` + id outlet tercetak di hint untuk transparansi & QA.
  - Tombol "Tambah" & "Upload QRIS" sekarang menampilkan nama outlet aktif secara eksplisit dan disabled bila outlet belum valid.
- [x] **Verified via curl (backend isolation)**: Super Admin → POST BSI ke `outlet-banda-aceh` sukses; GET Banda Aceh return BSI; GET Sudirman TIDAK terkontaminasi (masih Bank Aceh original). Super Admin tanpa outlet_id → 400 dengan pesan Indonesia jelas.
- [x] **Verified via screenshot (UI binding)**: Switch dropdown "MJD Sudirman" → "MJD Banda Aceh" secara real-time mengubah: badge, tombol "Tambah ke {nama}", label "Upload QRIS untuk {nama}", hint id outlet, dan daftar rekening (Bank Aceh Sudirman → BSI Banda Aceh) — 100% sinkron.

## Iteration 28 (Feb 2026 — Global Double-Click Prevention + Sales Idempotency)
**Goal**: Cegah pembuatan transaksi duplikat saat kasir klik "Konfirmasi pembayaran" berkali-kali di jaringan lambat.

**Backend** (`/api/sales`):
- [x] **Kolom baru** `mjd_sales.idempotency_key VARCHAR(64)` + index `ix_sales_idempotency` (ALTER TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS di startup migration).
- [x] **`SaleInput`** tambah field opsional `idempotency_key`. `create_sale` juga baca header `Idempotency-Key`.
- [x] **Guard replay**: Bila client kirim key yang sama untuk cashier yang sama dalam 15 menit terakhir → **return sale asli** dengan flag `_idempotent_replay: true` (bukan buat duplikat baru). No stock re-deduct, no kitchen ticket ganda.
- [x] **Verified via curl**: 3 POST berurutan — 1st create (id `b3aa37bf`), 2nd same key returns SAME id + `replay=True`, 3rd different key returns NEW id (`bc617abc`).

**Frontend** (`App.js`):
- [x] **`useAsyncAction` hook** (sudah ada dari iter26) di-adopsi untuk checkout: `[busyCheckout, runCheckout]`.
- [x] **`openPayment()` generate idempotency key** via `crypto.randomUUID()` (fallback ke timestamp+random) — sekali per attempt, disimpan di state `checkoutKey`.
- [x] **`confirmSale()` di-wrap `runCheckout`** — hard-guard klik ganda + kirim key via body **dan** header `Idempotency-Key` (dual-safety). Key di-reset setelah sukses. Offline queue tetap menyimpan payload lengkap dengan key sehingga sinkronisasi ulang tetap idempotent.
- [x] **`PaymentModal` UX**:
  - Prop `busy` diteruskan dari App.
  - Tombol "Konfirmasi pembayaran" disabled + tampilan `⟳ Memproses transaksi…` selama request in-flight.
  - Modal backdrop `onClose` tidak menutup selama busy (mencegah user meng-close accidental saat proses masih jalan).
  - Toast "Transaksi sudah tersimpan sebelumnya (duplikasi dicegah)" bila backend menjawab `_idempotent_replay`.
- [x] **Verified via Playwright**: 4 klik cepat pada tombol Konfirmasi → tombol switch ke "Memproses transaksi…" state, hanya **1 baris** `mjd_sales` tercipta (Rp 18.000, key `dfd4c8d3-99b...`), regressi dibandingkan sesi lama yang tercatat 3 baris identik dalam 2 detik.

## Iteration 29 (Feb 2026 — Backend Hardening: Subscription, Setting Whitelist, MutableDict)
**Scope**: Server-only hardening per user directive (`server.py` + `models.py`). Alembic init explicitly skipped (marked optional).

- [x] **T1 — Subscription enforcement per-request** (`current_user()`): setelah user ditemukan, query `Merchant` bila `user.merchant_id` exists. Bila `subscription_status='suspended'` → HTTP 403 "Langganan merchant ini telah ditangguhkan". Roles `Super Admin` / `owner` / `super_admin` bypass (mereka platform owner). Sebelumnya cek hanya di endpoint login → token valid tetap bisa jalan sampai kedaluwarsa. Sekarang setiap request lewat dependency `current_user`.
- [x] **T2 — Whitelist key untuk POST /api/settings**: konstanta baru `ALLOWED_SETTING_KEYS_EXACT` (`logo`, `printer`, `printer_config`, `sound_config`, `tax_config`, `branding_text`, `feature_toggles`) + `ALLOWED_SETTING_KEY_PREFIXES` (`qris-image:`, `qris:`, `bank-accounts:`, `pin:`) — daftar diverifikasi via grep sisi Frontend + Backend. Admin ditolak (400) bila key di luar daftar; Super Admin / owner bypass (butuh maintenance).
- [x] **T3 — MutableDict / MutableList wrappers** (`models.py`): `Setting.value → MutableDict.as_mutable(JSON)`, `Product.variants → MutableList.as_mutable(JSON)`. Mutation nested (append/pop, dict key update) sekarang auto-detected → mengurangi kebutuhan `flag_modified()` manual & mencegah silent-lost-writes.
- [x] **T4 — Alembic**: **DILEWATKAN** (opsional per user). `ALTER TABLE IF NOT EXISTS` di startup tetap dipertahankan.

**Verified via curl** (Task 1):
- Vendor (merchant `m-barista` active) → `/auth/me` = 200
- Setelah `UPDATE mjd_merchants SET subscription_status='suspended' WHERE id='m-barista'` → `/auth/me` = **403** dengan pesan Indonesia persis
- Super Admin bypass = 200; Admin (tanpa merchant_id) = 200 (tidak terpengaruh)

**Verified via curl** (Task 2):
- Admin POST `tax_config` = 200 · Admin POST `qris-image:outlet-sudirman` (prefix) = 200
- Admin POST `evil_backdoor` = **400** "Key setting 'evil_backdoor' tidak diizinkan…"
- Super Admin POST `custom_platform_setting` = 200 (bypass)

**Verified via curl** (Task 3):
- GET `tax_config` (MutableDict) & GET `bank-accounts` (MutableDict) OK
- POST new bank ke Sudirman → count naik 1 → GET setelah append persist correctly
- GET product dengan variants (MutableList) → 4 varian tampil

**Regression testing** (pytest against preview URL, iter29-relevant suites):
- `test_iteration21_multitenant.py` 19/19 ✅
- `test_iteration20_product_mgmt.py` 16/16 ✅
- `test_iteration18_selforder_concurrency.py` 3/4 (1 gagal: `TestSequentialAcceptIdempotent` — pre-existing shift-state race, tidak terkait iter29)
- `test_iteration12_dashboard_tax.py` + `test_iteration19_batch_c.py` 23/24 (1 gagal: `TestSettlement::test_payout_create_and_list` — pre-existing data drift antara `preview` vs. capture-time)
- `test_security_fixes.py` 19/21 (2 gagal pre-existing: cookie SameSite=Lax vs platform's None, dan self-order tanpa `customer_name` yang jadi mandatory sejak iter13-14)
- **Aggregate iter29-relevant regression: 100% pass** — tidak ada regresi baru yang diperkenalkan oleh hardening ini.

## Backlog (P1/P2)
- **P1 REFACTORING (Urgent)**: Split `server.py` (~2467 lines) → routers/{auth, products, sales, merchants, settings, branding, kds, shifts, inventory, settlement}.py. Split `App.js` (~2700 lines) → components/pages folder structure.
- P1: Immediate subscription lockout — add `subscription_status` check inside `current_user()` dependency, not just at login (currently allows session until token expires).
- P1: Fix tax bypass loophole (allow client tax=0) — enforce server-computed tax always.
- P1: Wrap Setting.value & Product.variants with `MutableDict.as_mutable(JSON)` to prevent alias mutation bugs.
- P1: Alembic migrations replacing metadata.create_all + ALTER TABLE IF NOT EXISTS.
- P1: Whitelist allowed keys for POST /api/settings (currently any Admin can overwrite feature_toggles, bank-accounts, sound_config, tax_config, etc.).
- P2: Supabase Realtime channels replace polling.
- P2: Guard prevent last Super Admin toggle/delete + audit log entries.
- P2: Real QRIS Xendit/Midtrans integration.
- P2: Multi-outlet per merchant slug routing (slug detection via subdomain/query param).
- P2: Loyalty / member program, E-invoice, Faktur pajak.
- P2: Bulk-import → also write StockMovement rows (currently skipped for import; audit trail loses those changes).
- P2: create_sale N+1 SELECT for stock deduction — batch fetch via IN() for large tickets.
