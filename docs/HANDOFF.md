# Daily Handoff & Cross-Device Sync — 2026-11-21

> **Purpose:** Single source of truth for resuming work seamlessly between **Office PC** and **Home Laptop** without copying local AI chat databases.
> **Language Preference (Tushar):** Communicate with Tushar in **Bengali (বাংলা)** in chat sessions.
> **Repos Synced:**
> - Backend: `implesia-mart-backend` (`main`, latest feature commit `cabc203`)
> - Frontend: `implesia-mart` (`main`, latest feature commit `46b3a51`)

---

## 1. Planning Workstream (Completed Today)

1. **Customer Dashboard & Reviews Audit (Phases 6–10):**
   - Audited customer auth, profile/avatar, cart merge, 30-day notification retention + physical auto-purge, order tracking, repeat-purchase product history, and verified purchaser product reviews.
   - Produced phase-by-phase specs — **all implemented and merged to `main`**.
2. **SaaS Admin Upgrade & Accounting Audit (Phases A–C Backend / D–G Frontend):**
   - Designed optional `products.supplier_id` + per-variant `product_variants.cost_price`.
   - Fixed accounting accuracy by excluding `returned` orders from realized sales & profit aggregates.
   - Fixed offline counter order sync (`initial_status`/`mark_delivered` aligned to `order_date`, customer `user_id` phone linking, subsequent due payment collection).
   - Designed `RequireSuperadmin`-only safe deletion with dependency impact previews and atomic zero-conflict reconciliation/merge for Orders, Badges, and Suppliers.
   - Designed 7-page SaaS reporting APIs + `.xlsx` exports and per-product analytics.
3. **Notification Architecture Audit:**
   - Confirmed **no WebSocket or SSE** is used currently.
   - Active channels: Admin smart HTTP polling (`25s` visible / `3m` hidden) + Leader-Tab Election + `BroadcastChannel`, Customer `60s` HTTP polling against `customer_notifications`, Admin Telegram Bot push (`telegram_notify.py`), and Customer SMS adapter (`customer_notify.py`, pending SSL Wireless credentials).
   - Future recommendation: **SSE + Web Push** for one-way instant alerts; **WebSocket** only when building two-way live chat.
4. **Cross-Device Sync Standard (Option 2 Adopted):**
   - Sync project state, plans, DevOps status, and pending tasks via Git (`docs/HANDOFF.md`, `docs/WORK_REPORT_*.md`, `docs/TODO.md`, `docs/CHANGELOG.md`) instead of copying local Antigravity SQLite files.

---

## 2. Backend Implementation Summary (Merged to `main`)

- **Customer Platform (`9577b4c`, `d0cd222`, `3973eb2` — Migrations `0102`–`0104`):**
  - Customer role, phone/address/avatar fields, `customer_notifications` (30-day physical purge), `product_reviews`, FK indexes (`0104`), cart merge, activity-based tracking timeline, full purchase history, enriched dashboard summary, and automated order status notifications (new order + single/bulk updates).
- **SaaS Accounting, Reports & Safe Delete (`cabc203` — Migration `0105`):**
  - **Phase A (`0105_product_supplier_and_variant_cost.py`):** Nullable `products.supplier_id` (`ON DELETE SET NULL`, indexed), nullable `product_variants.cost_price`, `order_activities.action` widened with `payment_updated`, offline immediate delivery + `POST /api/v1/admin/orders/{id}/payments`, returned orders excluded from realized sales/profit.
  - **Phase B:** Expanded presets & filters (`today`, `7d`, `this_week`, `this_month`, `last_month`, `this_year`, `supplier_id`, `origin`, `profit_filter`, `sort`), `GET /api/v1/admin/reports/profit-loss`, `/channels`, `/suppliers` (+ `.xlsx` exports), enriched `/products` & `/stock`, and `GET /api/v1/admin/products/{id}/analytics`.
  - **Phase C:** `RequireSuperadmin` on `GET .../delete-impact` and `DELETE` for Orders (atomic stock restoration + offsetting `stock_movements` adjustment rows + `ORDER_DELETED` audit snapshot), Badges (`merge`/`unlink`, system badges protected), and Suppliers (`merge`/`archive`/guarded `hard_delete`).
- **Verification:** `ruff check .` clean, `mypy app` 0 issues, single Alembic head (`0105`), full pytest suite passing (`test_customer_auth.py`, `test_customer_phase6.py`, `test_phase_a_accounting.py`, `test_reports_saas.py`, `test_phase_c_safe_delete.py`, `test_0105_migration.py`).
- **Frontend Companion (`implesia-mart` `46b3a51`):** All Phases 7–10 & D–G implemented and verified (`387/387` tests, 0 lint/type errors, 71-route build clean).

See also: [WORK_REPORT_2026-11-21.md](WORK_REPORT_2026-11-21.md) and [TODO.md](TODO.md).

---

## 3. DevOps & Deployment Status (Pending Production Rollout)

- **Live Audit Conducted Today:**
  - Live API `mart-api.implesia.com` (VPS `72.60.199.155`, Docker Compose) returned `404` on newly added customer/review endpoints → **production does NOT yet have today's code or migrations `0100`–`0105`**.
  - GitHub Actions runs CI checks only (no automatic deploy).
  - Local Cloudflare Workers token verified active for frontend deployment (`npm run deploy:vinext`).
- **Deployment Blocker:**
  - Waiting on Tushar's go-ahead and VPS SSH credentials (provided interactively at deploy time — **never commit credentials to Git**).
- **Exact Production Deployment Sequence:**
  1. Take a PostgreSQL backup (`pg_dump`) on VPS `72.60.199.155` before running migrations.
  2. Pull `main` on VPS and apply migrations through `0105`:
     ```bash
     docker compose -f docker-compose.prod.yml --env-file .env.production run --rm api alembic upgrade head
     ```
  3. Rebuild and restart the API container:
     ```bash
     docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
     ```
  4. Deploy frontend `implesia-mart` (`main`) to Cloudflare Workers (`npm run deploy:vinext`).
  5. Run live smoke tests across storefront customer flows, admin dashboard, 7 report pages + Excel exports, offline walk-in orders, due payments, and superadmin safe delete modals.

---

## 4. Pending Backlog (After Production Deploy)

- [ ] **Production Deploy & Live Smoke Test** (above).
- [ ] **SSL Wireless SMS Integration:** Configure `SMS_SSLWIRELESS_API_TOKEN` & `SMS_SSLWIRELESS_SID` in `.env.production` when active.
- [ ] **PATCH Product 422 Parity:** Align `PATCH /api/v1/admin/products/{id}` validation envelope with Bengali per-field format used by `POST`.
- [ ] **Cloudflare & SEO Manual Checks:** SSL `Full (strict)`, `www` 301 redirect, sitemap submission, and 100 MB video upload limit verification.

---

## 5. How to Resume on Home Laptop (Quick Checklist)

1. Pull latest `main` in both repos:
   ```bash
   git -C implesia-mart-backend pull origin main
   git -C implesia-mart pull origin main
   ```
2. Upgrade local PostgreSQL schema on laptop:
   ```bash
   cd implesia-mart-backend && alembic upgrade head
   ```
3. In a new Antigravity chat on your laptop, say:
   > *"আমার সাথে বাংলায় কথা বলবে। `docs/HANDOFF.md` পড়ো—এখন আমি [ডিপ্লয় / পরবর্তী কাজ] শুরু করতে চাই।"*
