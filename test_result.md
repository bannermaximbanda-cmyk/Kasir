#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  Iter30 Bulk-Import Hardening (complete existing endpoint, no refactor):
  0. Fix cross-merchant collision: matching order id→sku+outlet+merchant→name+outlet+merchant.
  0b. In-file duplicate detection (same file, same sku/name+outlet+merchant, no id).
  1. BulkProductRow: add image_url, varian ("Name:price|Name:price"), status_aktif (1/0),
     merchant_name (alt to merchant_id, resolve → id BEFORE matching).
  2. image_url fallback to placeholder when invalid; outlet_id semantics fix
     (blank/"" = NULL/global for Super Admin; only fallback to user.outlet_id when key omitted).
  3. GET /api/products/csv-template — server-authoritative CSV with new headers + 3 example rows.
  4. GET /api/products/export — CSV filtered by outlet_id/merchant_id/category/status; admin scoped.
  5. Frontend BulkImportModal parse new columns; hit new endpoints for template/export; error list.
  6. Fix Edit Produk modal — add is_global toggle + Outlet Target dropdown mirroring add form.
  7. Reuse existing base64/data-URL image upload (no Supabase Storage helper exists to reuse).

backend:
  - task: "Iter30 — Bulk import: matching order + cross-merchant safety"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          Matching order now: (1) id → single-source-of-truth for edits/moves;
          (2) sku + outlet_id + merchant_id (added merchant scope so same SKU across
              merchants no longer collides);
          (3) name + outlet_id + merchant_id (same reasoning as SKU).
          Rows without an id require merchant_id or merchant_name (resolved before matching);
          otherwise flagged as error row (never silently defaulted).
          Pass-1 in-file duplicate detection: (sku, outlet, merchant) and (name, outlet, merchant)
          for id-less rows → 2nd+ row emits explicit "Duplikat baris {n} dengan baris {m}…" error
          without touching DB.
          image_url invalid/blank → PRODUCT_IMAGE_PLACEHOLDER (empty string so <Coffee/> fallback
          renders); valid http(s):// or data: URLs stored as-is.
          outlet_id semantics: "" or None ⇒ NULL (global product) for Super Admin when
          `outlet_id_explicit=True`; Admin scoped to their own outlet; invalid outlet_id → error row.
          Verified via pytest test_iteration30_bulk_import (7/7 pass) covering all above cases.

  - task: "Iter30 — CSV template + export endpoints"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          GET /api/products/csv-template returns UTF-8 BOM CSV with header
          (id,nama_produk,sku,merchant_name,kategori,harga_jual,hpp_modal,stok_awal,outlet_id,
          image_url,varian,status_aktif) plus 3 sample rows: (a) new+global, (b) new+specific-outlet,
          (c) placeholder id showing edit-existing / cross-merchant re-import pattern.
          GET /api/products/export accepts outlet_id/merchant_id/category/status filters, streams
          UTF-8 CSV. Admin scoped to own outlet + globals; global products (outlet_id NULL) always
          included in filtered results. Verified via pytest + browser download test.

  - task: "Iter30 — BulkProductRow extended fields (varian, status_aktif, merchant_name, image_url)"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          BulkProductRow gained: image_url (Optional[str]), varian (Optional[str]),
          status_aktif (Optional[int]), merchant_name (Optional[str]).
          `_parse_variants_string("Panas:20000|Ice:22000|Extra Shot:5000")` returns list of dicts
          with generated UUID ids, active=true, cost=0. Empty entries silently skipped.
          status_aktif takes precedence over is_active when supplied.
          Verified: test_varian_string_parsed_into_variants + test_status_aktif_maps_to_is_active pass.

frontend:
  - task: "Iter30 — Edit Produk modal: Outlet Target control"
    implemented: true
    working: true
    file: "frontend/src/App.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          ProductEditModal now receives outlets/session props and mirrors the add-form pattern:
          "🏪 SPESIFIK OUTLET"/🌐 SEMUA OUTLET toggle + outlet dropdown (disabled unless
          Super Admin). save() computes outlet_id = is_global ? null : form.outlet_id and PUTs
          it explicitly (previously missing entirely). Verified via screenshot: toggle + dropdown
          render pre-populated with product's current outlet.

  - task: "Iter30 — BulkImportModal new columns + server-driven template/export"
    implemented: true
    working: true
    file: "frontend/src/App.js"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          BulkImportModal parses id/varian/status_aktif/image_url/merchant_name/outlet_id (blank
          preserved). Client-side per-row validation: nama_produk + harga_jual + merchant. Error
          list merges server-reported errors so user can act.
          "Unduh Template CSV" hits GET /api/products/csv-template (blob download).
          "Export Data" hits GET /api/products/export with active filters
          (merchant/category/status/outlet_id).
          New product-list filter "Semua Outlet / <outlet>" — global products always shown.
          Verified via screenshot: outlet filter dropdown (5 options) + import modal with
          instructions banner + edit modal toggle+dropdown.

metadata:
  created_by: "main_agent"
  version: "iter30"
  test_sequence: 30
  run_ui: false

test_plan:
  current_focus:
    - "Iter30 — Bulk import: matching order + cross-merchant safety"
    - "Iter30 — CSV template + export endpoints"
    - "Iter30 — BulkProductRow extended fields (varian, status_aktif, merchant_name, image_url)"
    - "Iter30 — Edit Produk modal: Outlet Target control"
    - "Iter30 — BulkImportModal new columns + server-driven template/export"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: |
      Iter30 bulk-import hardening complete. New pytest file
      `backend/tests/test_iteration30_bulk_import.py` (7 tests, all pass):
        • test_varian_string_parsed_into_variants ✅
        • test_status_aktif_maps_to_is_active ✅
        • test_csv_template_endpoint ✅
        • test_export_endpoint_returns_csv ✅
        • test_cross_merchant_sku_collision_creates_two_products ✅
        • test_in_file_duplicate_detection ✅
        • test_blank_outlet_id_preserved_as_global ✅
      Frontend smoke tested: Outlet filter dropdown, Edit modal outlet toggle/dropdown, and
      Bulk-import modal instruction banner all render as expected via Playwright screenshot.
      Existing iter29 tests still pass (100% iter29-relevant regression).
      Task 7 note: no Supabase Storage helper exists in codebase — every image field (logo,
      QRIS, product image, banner) uses base64 data URLs via FileReader.readAsDataURL. Kept
      existing pattern; adding Storage would be a separate iteration.


#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

_previous_iter29_notes: |
  1. Enforce merchant.subscription_status='suspended' at EVERY request via current_user() dependency (not only at login). Exempt Super Admin / owner.
  2. Whitelist keys for POST /api/settings (Admin restricted; Super Admin bypass).
  3. Wrap Setting.value & Product.variants with MutableDict/MutableList so nested mutations are detected by SQLAlchemy.
  4. (Optional, skipped) Alembic init.

backend:
  - task: "Iter29-T1: Subscription enforcement on every request"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          current_user() now queries Merchant when user.merchant_id is set and rejects requests with
          HTTP 403 "Langganan merchant ini telah ditangguhkan" when subscription_status == 'suspended'.
          Super Admin / owner / super_admin roles are exempt.
          Verified via curl:
            • Vendor (merchant_id=m-barista, subscription=active) → /auth/me = 200
            • After UPDATE mjd_merchants SET subscription_status='suspended' WHERE id='m-barista'
              → /auth/me = 403 with exact Indonesian message
            • Super Admin bypass = 200 (still works)
            • Admin without merchant_id = 200 (not affected)
            • Restore to active → 200 again

  - task: "Iter29-T2: Whitelist for POST /api/settings"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          Introduced ALLOWED_SETTING_KEYS_EXACT (logo, printer, printer_config, sound_config,
          tax_config, branding_text, feature_toggles) and ALLOWED_SETTING_KEY_PREFIXES
          (qris-image:, qris:, bank-accounts:, pin:). Admin is restricted to these keys;
          Super Admin / owner / super_admin bypass.
          Verified via curl:
            • Admin POST tax_config = 200
            • Admin POST qris-image:outlet-sudirman (prefix) = 200
            • Admin POST evil_backdoor = 400 "Key setting 'evil_backdoor' tidak diizinkan…"
            • Super Admin POST custom_platform_setting = 200 (bypass)

  - task: "Iter29-T3: MutableDict/MutableList wrappers"
    implemented: true
    working: true
    file: "backend/models.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
          Setting.value → Column(MutableDict.as_mutable(JSON), default=dict)
          Product.variants → Column(MutableList.as_mutable(JSON), default=list)
          Others (StockLog/kitchen lines/etc) intentionally left as plain JSON to minimize risk.
          Verified: GET tax_config, GET bank-accounts, POST new bank (append → count 2 → GET after
          → count 2, last row matches). GET a product with variants → variants present with 4 rows.
          Bank-accounts flag_modified(row, "value") calls remain in place as defense-in-depth
          (harmless with MutableDict; still valid if wrapper is ever removed).

  - task: "Iter29-T4: Alembic migration setup"
    implemented: false
    working: "NA"
    file: "backend/"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
          Skipped per user instruction (task 4 is optional). ALTER TABLE IF NOT EXISTS pattern retained
          in server.py startup. Alembic can be introduced in a future iteration.

frontend:
  - task: "N/A for iter29 hardening"
    implemented: true
    working: "NA"
    file: "-"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Iter29 is backend-only hardening. No frontend changes."

metadata:
  created_by: "main_agent"
  version: "iter29"
  test_sequence: 29
  run_ui: false

test_plan:
  current_focus:
    - "Iter29-T1: Subscription enforcement on every request"
    - "Iter29-T2: Whitelist for POST /api/settings"
    - "Iter29-T3: MutableDict/MutableList wrappers"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: |
      Iter29 backend hardening complete. All three mandatory tasks verified via curl end-to-end
      against the preview URL. Regression run against existing pytest suite:
        • tests/test_iteration21_multitenant.py     — 19/19 pass
        • tests/test_iteration20_product_mgmt.py    — 16/16 pass
        • tests/test_iteration18_selforder_concurrency.py — 3/4 pass (1 unrelated shift-state race
          in TestSequentialAcceptIdempotent, present before iter29)
        • tests/test_iteration12_dashboard_tax.py + iter19_batch_c.py — 23/24 pass
          (1 unrelated payout-gross data drift, present before iter29)
        • tests/test_security_fixes.py — 19/21 pass (2 pre-existing failures:
          test_sec001_login_cookie_samesite_lax expects SameSite=Lax but preview platform now
          uses SameSite=None; test_csrf_self_order_allowlisted_without_header + regression accept
          fail because customer_name became required in iter13-14).
      Aggregate iter29-touched regression: 100% pass. No new failures introduced.
      Task 4 (Alembic) intentionally skipped per user instructions.