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
- JWT cookie authentication with four seeded demo roles, protected role permissions, logout, demo credentials, and multi-outlet switching.
- Self-service meja with table selection, QRIS code persistence, menu cart, and order submission to the vendor queue.
- Vendor Center with kitchen queue, status updates, commission settlement, net payout calculation, and payout request feedback.
- POS, product, stock, and self-order actions now attempt backend API persistence and retain localStorage fallback.
- Desktop and mobile smoke testing completed successfully; production frontend build passes.

## Prioritized Backlog
- P0: Connect initial product/expense reads to FastAPI persistence and add offline sync queue.
- P0: Add production password rotation and account administration.
- P1: Add Supabase Transaction Pooler sync once the project URI is supplied.
- P1: Add real tenant settlement ledger and split kitchen tickets per vendor.
- P2: Add real WhatsApp provider, QR payment provider, branding upload, and thermal printer bridge.

## Remaining P0/P1/P2 Features
- P0: Initial product and expense hydration still uses seeded client data; API write-through is active for POS, products, restock, QRIS, and self-order.
- P1: Supabase integration is not active because no valid Transaction Pooler URI was supplied.
- P1: Real payout transfer, automatic kitchen ticket printing, and audit-grade stock opname calculations remain next phase.
- P2: Production QRIS/WhatsApp, printer configuration, backup/restore UI, and branded upload.

## Next Tasks
1. Supply and validate the Supabase Transaction Pooler URI.
2. Add background sync queue for offline writes and initial API hydration.
3. Add password rotation and user administration screens.
4. Extend settlement, kitchen tickets, printer, and real notification integrations.