# MJD Kupi — Product Requirements Document

## Original Problem Statement
Build an ultra-complete, responsive, modular POS & ERP Retail Enterprise web application named MJD Kupi with a clean white and vibrant orange desktop-game-launcher-inspired SPA/PWA interface. Required areas include role-based access, multi-tenant vendors, POS, inventory, expenses, product/HPP costing, tenant settlement, QR table ordering, printer/branding settings, financial reports, export, and database persistence with Supabase/Firebase plus localStorage fallback.

## Architecture Decisions
- React SPA with responsive CSS and a fixed operational sidebar.
- Offline-first localStorage is the active client fallback for fast demo operation.
- FastAPI endpoints use the existing MongoDB environment and expose products, stock adjustment, expenses, sales, and dashboard summaries.
- Supabase synchronization is deferred until a valid Transaction Pooler URI is provided; existing protected environment values remain unchanged.
- POS data model separates products by vendor/tenant and sales by line item.

## User Personas
- Super Admin: consolidated oversight across merchants and vendors.
- Merchant Admin: manages outlet products, inventory, expenses, and finance.
- Vendor: monitors tenant products and kitchen/order activity.
- Kasir: completes fast POS transactions and receipts.

## Core Requirements (Static)
- White/orange operational UI, responsive at desktop and mobile widths.
- Role switcher and merchant context in the top bar.
- POS menu search/filter, cart quantities, tax, payment, and receipt.
- Inventory stock summary, restock, stock opname entry point, and low-stock indicators.
- Expense ledger and quick entry.
- Product catalog with price, HPP, margin, and vendor.
- Profit & loss summary, export CSV, and table QR studio.
- Unique data-testid values on user-facing and interactive controls.

## Implemented (2026)
- Full SPA shell with Ringkasan, Terminal POS, Inventori & Stok, Pengeluaran, Produk & HPP, Laporan Keuangan, and QR Meja modules.
- Functional POS cart, quantity controls, category/search filtering, PPN calculation, payment flow, receipt modal, and stock decrement.
- Local product persistence, restock workflow, expense entry, product creation, CSV export, QR/print feedback, and responsive mobile layout.
- FastAPI MongoDB-backed API endpoints for products, stock adjustments, expenses, sales, and dashboard summaries.
- Desktop and mobile smoke testing completed successfully; production frontend build passes.

## Prioritized Backlog
- P0: Connect frontend mutations and initial reads to FastAPI persistence.
- P0: Add JWT login, seeded users, and server-side role permissions.
- P1: Add Supabase Transaction Pooler sync once the project URI is supplied.
- P1: Add real tenant settlement and split kitchen tickets.
- P2: Add real WhatsApp provider, QR payment provider, branding upload, and thermal printer bridge.

## Remaining P0/P1/P2 Features
- P0: Authentication/RBAC is currently a role-switcher demo, not server authentication.
- P0: Frontend actions currently prioritize localStorage; backend business APIs are available but not yet the default client transport.
- P1: Supabase integration is not active because no valid Transaction Pooler URI was supplied.
- P1: Vendor payout, automatic order splitting, and audit-grade stock opname calculations remain next phase.
- P2: Production QRIS/WhatsApp, printer configuration, backup/restore UI, and branded upload.

## Next Tasks
1. Supply and validate the Supabase Transaction Pooler URI.
2. Wire React reads/mutations to FastAPI with localStorage queue fallback.
3. Add JWT authentication and role permission guards.
4. Extend settlement, kitchen tickets, printer, and real notification integrations.