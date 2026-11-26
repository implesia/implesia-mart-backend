# Changelog

Newest first. Every task adds an entry: date, what changed, files touched, and anything the frontend repo (`implesia-mart`) must change.

- **Home Hero Multi-Template Support (`classic` & `image_only`) (2026-11-26). Done (not live).** Additive migration `0113_home_banner_template.py` (`down_revision = "0112"`). Single Alembic head `0113`.
  - Added `template` (`VARCHAR(32)`, default `'classic'`, check constraint `ck_home_banners_template_known` allowing `'classic'` and `'image_only'`) to `home_banners` (`HomeBanner` + `BannerTemplate` `StrEnum`).
  - Exposed `template` in `GET /api/v1/home/banner` (`HomeBannerPublic`), `GET /api/v1/admin/home/banner` (`HomeBannerRead`), and `PATCH /api/v1/admin/home/banner` (`HomeBannerUpdate`, rejects unknown values with HTTP 422). Existing banners default to `'classic'` and switching templates preserves all slide copy and media intact.
  - Files touched: `alembic/versions/0113_home_banner_template.py`, `app/models/home/banner.py`, `app/schemas/home/banner.py`, `app/services/home/banner_defaults.py`, `app/services/home/banner_service.py`, `tests/test_home_banner.py`, `tests/test_0113_migration.py`, `docs/CHANGELOG.md`.
  - Frontend (`implesia-mart`): reads `template` (`"classic" | "image_only"`) from `GET /api/v1/home/banner` to render either the existing split layout or the full-bleed image-only banner, and updates it via `PATCH /api/v1/admin/home/banner` from `/admin/home/hero`.

- **Phase 24 Steadfast Webhook Automation, Superadmin COD Reconciliation & Customer Live Tracking (2026-11-25). Done (not live).** No new database migration (uses Phase 23 `0112` tables).
  - **Steadfast Webhook Receiver (`app/api/v1/endpoints/webhooks.py`, `app/services/courier/steadfast_webhook_service.py`, `app/api/v1/router.py`, `app/services/telegram_notify.py`):**
    - Mounted `POST /api/v1/webhooks/steadfast` authenticated via `STEADFAST_WEBHOOK_SECRET` (Bearer token or `X-Steadfast-Webhook-Secret` / `X-Webhook-Secret` / `X-Steadfast-Token`, constant-time `hmac.compare_digest`, fails closed when secret is empty).
    - Idempotently records every event in `courier_webhook_events` via deterministic `event_key` so retries never double-process.
    - Enforces strict accounting/status rules: never finalizes orders or accounting on `*_approval_pending`; auto-transitions confirmed `delivered` orders (triggering `delivered_at`, customer in-app notification, WebSocket push, and Web Push); flags `partial_delivered` for staff review without overwriting totals; tracks `cancelled` return progression and sets `is_return_received=True` ONLY on `cancelled_return_received` or `partial_delivered_return_received`; logs alert activity and queues optional Telegram alert on `hold` / `exceptional`.
  - **Superadmin-Only Finance & COD Reconciliation (`app/services/courier/steadfast_finance_service.py`, `app/api/v1/endpoints/admin_courier.py`, `app/models/audit_event.py`, `app/schemas/courier.py`):**
    - Added strictly `RequireSuperadmin` routes (403 for editors/viewers): `GET /api/v1/admin/courier/steadfast/balance`, `GET /api/v1/admin/courier/steadfast/payments` (paginated), `GET /api/v1/admin/courier/steadfast/payments/{payment_id}` (zero-N+1 parcel cross-match), and `POST /api/v1/admin/courier/steadfast/payments/{payment_id}/reconcile` (atomic, idempotent COD settlement updating `courier_shipments.settled_*`, `order.paid_amount`/`due_amount`, `payment_updated` activity, and `COURIER_COD_RECONCILED` audit event).
  - **Live Customer & Public Tracking Wiring (`app/services/courier/tracking_presenter.py`, `app/services/customer_purchased_service.py`, `app/services/order_service.py`, `app/schemas/order.py`):**
    - Enriched `GET /api/v1/customer/orders/{order_number}/tracking` and `POST /api/v1/orders/lookup` with `tracking_url` and sanitized `live_events` (fetching cached 60s `trackings_by_invoice` on demand when active and not yet final; never exposing raw `*_approval_pending`, `fraud_score`, `merchant_reports`, or internal staff notes).
  - Files touched: `app/api/v1/endpoints/webhooks.py`, `app/api/v1/endpoints/admin_courier.py`, `app/api/v1/router.py`, `app/models/audit_event.py`, `app/schemas/courier.py`, `app/schemas/order.py`, `app/services/courier/steadfast_webhook_service.py`, `app/services/courier/steadfast_finance_service.py`, `app/services/courier/steadfast_service.py`, `app/services/courier/tracking_presenter.py`, `app/services/customer_purchased_service.py`, `app/services/order_service.py`, `app/services/telegram_notify.py`, `tests/test_steadfast_webhook_finance.py`, `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`.
  - Frontend (`implesia-mart`): `POST /api/v1/orders/lookup` now also includes additive `tracking_url` (`string | null`) and `live_events` (array of sanitized `{status, label, message, timestamp}`); superadmin finance UI can call `/api/v1/admin/courier/steadfast/balance` and `/payments*`.

- **Phase 23 Hardened Steadfast Merchant API Client & Courier Operations (2026-11-25). Done (not live).** Additive migration `0112_steadfast_courier_integration.py` (`down_revision = "0111"`). Single Alembic head `0112`.
  - **Additive Schema & Models (`alembic/versions/0112_steadfast_courier_integration.py`, `app/models/courier.py`, `app/models/order.py`, `app/models/__init__.py`):**
    - Created `courier_shipments` (partial unique index on non-null `consignment_id`, `cod_amount >= 0` check, `tracking_events` & `raw_payload` JSONB/JSON), `courier_webhook_events` (`event_key` unique idempotency), and `courier_locations` (unique `(provider, district, police_station)`).
    - Widened `order_activities.action` CHECK constraint to include `courier_booked`, `courier_webhook`, and `return_requested`.
  - **Config & Hardened `SteadfastClient` (`app/core/config.py`, `.env.example`, `app/services/redis_client.py`, `app/services/courier/steadfast_client.py`, `app/services/courier/adapters.py`):**
    - Added `STEADFAST_WEBHOOK_SECRET`, `STEADFAST_PICKUP_ADDRESS`, and `STEADFAST_PICKUP_PHONE`.
    - Built async `SteadfastClient` with input sanitization (`{};<>$` → spaces) & exact field truncation (`invoice` 100, `recipient_name` 100, `recipient_phone` 40, `recipient_address` 490, `note` 480), Redis-backed 3-strike 10-minute `401` circuit breaker (never retries 401), 60s Redis caches, and per-item HTTP 200 payload inspection for bulk booking.
    - Upgraded `SteadfastProvider` fraud check to `GET {base}/fraud_check/score/{phone}` (parsing `merchant_reports`, falling back to `/fraud_check/{phone}` on 404/405, never retrying 401).
  - **Admin Courier Operations & Public Locations (`app/schemas/courier.py`, `app/services/courier/steadfast_service.py`, `app/api/v1/endpoints/admin_courier.py`, `app/api/v1/endpoints/delivery.py`, `app/api/v1/router.py`):**
    - Mounted `/api/v1/admin/courier/steadfast/*` (`ping`, `orders/{id}/book`, `orders/bulk-book`, `orders/{id}/refresh-status`, `orders/{id}/tracking`, `pickup-request`, `return-requests`, `overview`, `sync-locations`) with duplicate-booking guard, 60s refresh cooldown, final delivered/returned order sync, and `orders` module RBAC.
    - Added public cached `GET /api/v1/delivery/locations` returning `{ provider, districts: [{ name, areas }], total_areas }`.
  - Files touched: `alembic/versions/0112_steadfast_courier_integration.py`, `app/models/courier.py`, `app/models/order.py`, `app/models/__init__.py`, `app/core/config.py`, `.env.example`, `app/services/redis_client.py`, `app/services/courier/steadfast_client.py`, `app/services/courier/steadfast_service.py`, `app/services/courier/adapters.py`, `app/services/courier/provider.py`, `app/schemas/courier.py`, `app/api/v1/endpoints/admin_courier.py`, `app/api/v1/endpoints/delivery.py`, `app/api/v1/router.py`, `tests/test_0112_migration.py`, `tests/test_steadfast_operations.py`, `tests/test_customer_courier_report.py`, `docs/CHANGELOG.md`, `docs/API.md`.
  - Frontend (`implesia-mart`): admin can call `/api/v1/admin/courier/steadfast/*` for Steadfast booking, bulk booking, status/tracking, pickup/return requests, overview, and location sync; checkout can read `GET /api/v1/delivery/locations` for district/area selectors.

- **Communication migration renumbered to `0110` (2026-11-24).** Merged `origin/testing` (`01f03e9`) into `feat/phases-18-21-realtime-communication`. `testing` already owns `0108` (role seed) and `0109` (`courier_check_results`). The communication schema is now `0110_communication_system.py` (`revision = "0110"`, `down_revision = "0109"`), so `alembic heads` is the single head `0110`. The upgrade only creates `conversations`, `messages`, and `conversation_read_states` (including `ix_conversation_read_states_user_id`, because `user_id` is the second primary-key column), and inserts `communication` rows into `role_permissions` when those roles exist. Constraint, index, and foreign-key names that are already in convention form use `op.f()`, so the naming convention does not prefix them a second time. No existing table or column is dropped or renamed, and no existing row is updated.
  - Files: `alembic/versions/0110_communication_system.py` (renamed from `0108_communication_system.py`), `tests/test_0110_migration.py`, `docs/CHANGELOG.md`, `docs/TODO.md`, `docs/HANDOFF.md`, `docs/WORK_REPORT_2026-11-22.md`, `docs/BUSINESS_LOGIC.md`.
  - Frontend (`implesia-mart`): no endpoint or response change from this renumber.

- **Testing integration (2026-11-24).** Merged the role seed, Meta CAPI/Turnstile, and the customer phone report into `testing`. The courier cache migration is `0109` (`down_revision` `0108`, the role seed) because both branches had used `0108`. `GET /admin/customers/report` and `POST /admin/customers/report/courier-check` stay open to a built-in viewer with orders `read_only` (`viewer_read`). The order list and other protected writes stay 403.
- **Meta CAPI match quality and Turnstile on public checkout (2026-11-24).** No migration.
  - Purchase `user_data` now includes hashed `fn`, `ln`, `ct`, `country` (`bd`), and `external_id` (customer id, or the normalized phone for a guest), plus unhashed `client_ip_address` (`CF-Connecting-IP`, then the first `X-Forwarded-For` entry, then the socket host) and `client_user_agent`. `fbp` and `fbc` were already passed through unhashed. `event_id` stays `purchase_<order_number>`. `META_TEST_EVENT_CODE` was already sent as `test_event_code` when set. Offline and admin-created orders still do not send CAPI.
  - `POST /api/v1/orders` accepts optional `turnstile_token` in the JSON body. When `TURNSTILE_SECRET_KEY` is set, siteverify must succeed. Missing or invalid is 400 `turnstile_failed` with message `নিরাপত্তা যাচাই ব্যর্থ হয়েছে, আবার চেষ্টা করুন`. An idempotency replay of an existing order does not need a new token. Admin and offline orders do not check it. An empty secret skips the check outside production and refuses public checkout in production.
  - Files: `app/services/meta_capi.py`, `app/services/turnstile.py`, `app/services/order_service.py`, `app/api/v1/endpoints/orders.py`, `app/schemas/order.py`, `app/core/config.py`, `.env.example`, `tests/test_meta_capi.py`, `tests/test_turnstile.py`, `bruno/Public/Orders/02 Place Cart Order.bru`, `bruno/Public/Orders/04 Place Direct Order.bru`, docs.
  - Frontend (`implesia-mart`): on `POST /api/v1/orders`, send `turnstile_token` in the JSON body (not `X-Turnstile-Token`). On 400 `{"error": {"code": "turnstile_failed", "message": "নিরাপত্তা যাচাই ব্যর্থ হয়েছে, আবার চেষ্টা করুন", "details": null}}`, show `message` and ask for a new widget token. Retrying an `Idempotency-Key` that already created the order does not need a token. Do not send the token on quote, lookup, or admin/offline orders. The Pixel `eventID` is still `analytics_event_id` (`purchase_<order_number>`). No new response fields.
- **Dynamic RBAC role seed and viewer read lock (2026-11-24).**
  - Postgres tests failed because `create_all` adds `fk_users_role_roles` and never inserts `viewer`. Both copies of a concurrent user insert then hit the foreign key, so the unique-email race looked like two conflicts. Migration `0108` (`down_revision` `0107`) inserts the system roles (`superadmin`, `editor`, `viewer`, `customer`), the legacy slugs (`super_admin`, `admin`, `staff`), and any other distinct `users.role`, with `INSERT ... ON CONFLICT (slug) DO NOTHING`. No row is updated, dropped, or renamed. Downgrade leaves the rows in place. The Postgres fixture seeds the same set after truncate.
  - Replacing `require_editor` with module `read` let a `read_only` viewer GET the dashboard, admin products, inquiries, CMS, carts, and the order list (200). Those reads are protected again: the built-in viewer needs `write`. `GET /admin/orders/new` stays allowed at `read`. Reports, inventory, coupons, delivery, pricing, and reviews stay readable. Writes stay 403 at `read_only`. Granting the viewer `read_write` or `full` still opens the module.
  - `tests/integration/test_0093_migration.py` drops and restores `fk_products_supplier_id_suppliers` around the isolated 0093 downgrade. The test was wrong on the current schema: `create_all` includes the migration 0105 product→supplier foreign key, and 0093 drops `suppliers`. A full Alembic downgrade still runs 0105 first. Product and order rows in that test are not rewritten.
  - Files touched:
    - `alembic/versions/0108_seed_missing_roles.py`
    - `app/api/deps.py`, `app/api/v1/endpoints/admin_orders.py`, `app/services/permission_service.py`
    - `tests/conftest.py`, `tests/integration/conftest.py`, `tests/integration/postgres.py`
    - `tests/integration/test_0093_migration.py`, `tests/integration/test_0108_migration.py`
    - `docs/CHANGELOG.md`, `docs/BUSINESS_LOGIC.md`, `docs/API.md`, `docs/TODO.md`
  - Frontend (`implesia-mart`): no new fields. A viewer token is 403 again on GET `/api/v1/admin/dashboard`, `/api/v1/admin/products`, `/api/v1/admin/inquiries`, `/api/v1/admin/site/*` CMS routes, `/api/v1/admin/carts`, and `/api/v1/admin/orders`. `GET /api/v1/admin/orders/new`, reports, inventory, coupons, delivery, pricing, and reviews are unchanged. The roles matrix can still show `read_only` for the viewer; that grant does not open the protected reads until it is `read_write` or `full`.
- **Customer phone report and courier fraud check (2026-11-24). Done (not live).** Additive migration `0109` (`down_revision = "0108"`, the role-seed revision). No existing row is updated.
  - **Report (`GET /api/v1/admin/customers/report?phone=`):** Orders-module read, including a built-in viewer with `read_only`. The order list stays closed to that viewer. Normalizes the phone to `01XXXXXXXXX` (`+880` and `880` accepted; invalid is 422). Matches online and offline orders by that stored phone. Returns the linked account (`{id, name, email}` or null), a summary (status counts, delivered-only `total_spent`, success rate, first/last order, online/offline counts), the newest 50 orders, and `courier_check` from the cache only.
  - **Courier check (`POST /api/v1/admin/customers/report/courier-check?phone=`):** Live call only when `COURIER_CHECK_ENABLED` is true. Steadfast, Pathao, RedX, and one generic HTTPS provider run in parallel, each with its own timeout. A missing key set leaves that provider `not_configured` and makes no network call. Results are upserted into `courier_check_results` (`phone`, `provider`, JSON payload, `checked_at`, unique on phone + provider). Rate limit `RATE_LIMIT_COURIER_CHECK` (default 10/hour) per staff account and per address.
  - Steadfast's count endpoint is the verified adapter (`ok`). Pathao, RedX, and the generic provider are unverified (`unverified` on success). Pathao's published client-id API is not used because it has no fraud-check method.
  - Files touched:
    - `alembic/versions/0109_courier_check_results.py`
    - `app/models/courier_check.py`, `app/models/__init__.py`
    - `app/schemas/customer_report.py`
    - `app/services/customer_report_service.py`, `app/services/courier/`
    - `app/api/v1/endpoints/admin_customers.py`, `app/api/v1/router.py`
    - `app/core/config.py`, `app/rate_limit.py`, `.env.example`, `tests/conftest.py`
    - `tests/test_customer_courier_report.py`, `tests/test_qa_hardening.py`
    - `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`, `docs/TODO.md`
  - Frontend (`implesia-mart`):
    - Admin customer lookup can call `GET /api/v1/admin/customers/report?phone=` and must keep the response shape: `phone`, `customer` (`id`, `name`, `email` or null), `summary` (including `by_status` with all seven statuses, `success_rate` as a 0–1 ratio or null, `total_spent` for delivered orders only), `orders` (max 50: `id`, `number`, `status`, `origin`, `total`, `created_at`, `tracking_number`), and `courier_check`.
    - Refresh calls `POST /api/v1/admin/customers/report/courier-check?phone=` and reads `courier_check` only. `enabled: false` means the server will not call a courier. Provider `status` is `not_configured`, `ok`, `error`, or `unverified`. Null parcel counts mean that provider did not return counts (Pathao rating-only results do this). Do not treat `unverified` as a failure; it means the call returned counts from an unpublished API.
    - `risk_level` is `unknown`, `low`, `medium`, or `high`. `success_rate` is not a percent.

- **Phase 19 High-Scale, Seller-Ready Direct Communication Engine (2026-11-22). Done (not live).**
  - **Additive Migration `0110_communication_system.py` (`down_revision = "0109"`; originally drafted as `0108` / `0107`) & Models (`app/models/communication.py`, `app/models/__init__.py`):**
    - Created `conversations` (`customer_support`, `seller_support`, `customer_seller`; status `open`/`pending`/`resolved`/`closed`; `customer_id`, `seller_id`, `order_id`, `product_id`, `assigned_staff_id`; high-scale composite DESC indexes), `messages` (composite keyset index `(conversation_id, created_at DESC, id DESC)`, `is_internal_note`), and `conversation_read_states` (composite PK `(conversation_id, user_id)`).
    - Idempotently seeded `role_permissions` for module `communication` (`editor=read_write`, `viewer=read_only`).
  - **Dynamic RBAC (`app/services/permission_service.py`):**
    - Registered `communication` (`Communication & Live Chat`) in `MODULE_DEFINITIONS` (`superadmin=full`, `editor=read_write`, `viewer=read_only`, grantable to any custom staff role via `/admin/rbac/roles`).
  - **Communication Service, Schemas & Endpoints (`app/services/communication_service.py`, `app/schemas/communication.py`, `app/api/v1/endpoints/customer_communication.py`, `app/api/v1/endpoints/admin_communication.py`, `app/api/v1/router.py`, `app/services/image_storage.py`, `app/services/redis_client.py`, `app/services/ws_manager.py`, `app/main.py`):**
    - Strict participant & RBAC isolation: customers access only their own threads and never see `is_internal_note=True` messages, internal previews, or internal WS frames (`WSConnectionManager.dispatch_channel` also enforces scope filtering).
    - Zero N+1 queries: batched user loading, single aggregated SQL unread counts, O(1) keyset/cursor pagination (`before_created_at`, `before_id`, `limit <= 50`).
    - Per-user send rate limit (`20 msgs / 10s` via Redis `rl:chat:{user_id}`), text validation (`1–2000` chars), image attachments under `/media/chat/`, real-time `message.created` & `conversation.updated` fan-out via `realtime_hub`, and throttled (`1 per 5 min`) offline `CustomerNotification` (`type="support_message"`).
    - Wired `communication_service.can_access_conversation` into `ws_manager` for WS `subscribe_conversation` authorization.
  - Files touched:
    - `alembic/versions/0110_communication_system.py`
    - `app/models/communication.py`, `app/models/__init__.py`
    - `app/schemas/communication.py`
    - `app/services/communication_service.py`, `app/services/permission_service.py`, `app/services/image_storage.py`, `app/services/redis_client.py`, `app/services/ws_manager.py`
    - `app/api/v1/endpoints/customer_communication.py`, `app/api/v1/endpoints/admin_communication.py`, `app/api/v1/router.py`, `app/main.py`
    - `tests/test_communication.py`, `tests/test_0110_migration.py`
    - `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`
  - Frontend (`implesia-mart`):
    - Customer chat can use `/api/v1/customer/conversations` (list/create-or-reuse), `/messages` (cursor paginated), `/attachment`, `/read`, plus WS `subscribe_conversation` and `message.created` events.
    - Admin inbox can use `/api/v1/admin/communication/summary`, `/conversations` (filter by `type`, `status`, `assigned`, `assigned_staff_id`, `q`), `/conversations/{id}` (context pane with customer profile & recent orders), `/messages`, `/attachment`, `PATCH /conversations/{id}`, and `/read`.

- **Phase 18 Monolith Concurrency Hardening & Real-Time WebSocket + Redis Pub/Sub Foundation (2026-11-22). Done (not live).**
  - **Database Pool Hardening (`app/core/config.py`, `app/db/session.py`, `.env.example`):**
    - Replaced hardcoded production `pool_size=2` with configurable `DB_POOL_SIZE` (default `10`), `DB_MAX_OVERFLOW` (`10`), `DB_POOL_TIMEOUT` (`15`), and `DB_POOL_RECYCLE` (`1800`) alongside `pool_pre_ping=True` for PostgreSQL.
  - **Resilient Async Redis Client & Pub/Sub Hub (`app/services/redis_client.py`, `app/services/realtime_hub.py`, `app/main.py`):**
    - Added bounded `redis.asyncio` client (`max_connections=50`, socket timeouts) with transparent in-process fallback (logs one startup warning if Redis is unreachable or `memory://`).
    - Added single worker background Pub/Sub subscriber loop in FastAPI `lifespan` subscribed to `rt:*` (`rt:user:{user_id}`, `rt:staff:orders`, `rt:staff:communication`, `rt:conv:{conversation_id}`).
    - Added Redis-backed 30s single-use WS auth tickets (`ws:ticket:{token}` consumed via atomic `GETDEL`), 60s TTL presence keys (`presence:user:{user_id}`), and sliding-window WS event rate limiting (`rl:ws:{user_id}`, 20 events / 10s).
  - **Hardened WebSocket Manager & Endpoints (`app/services/ws_manager.py`, `app/api/v1/endpoints/ws.py`, `app/api/v1/endpoints/auth.py`, `app/api/v1/endpoints/customer_auth.py`, `app/api/v1/router.py`, `app/schemas/auth.py`):**
    - Added `POST /api/v1/auth/ws-ticket` (staff with `admin_access`, dynamic RBAC channel scoping) and `POST /api/v1/customer/ws-ticket` (customer personal channel).
    - Added `WS /api/v1/ws?ticket=...` with ZERO PostgreSQL session held in the WS loop, max 5 concurrent sockets/user (close `4008`), 4 KB max frame (`1009`), 60s idle heartbeat timeout (`4000`), `ping`/`pong`, ephemeral `typing` relay, and `subscribe_conversation`.
  - **Real-Time Notification & Order Push (`app/services/order_service.py`, `app/services/notification_service.py`):**
    - New committed online orders publish `order.new` to `rt:staff:orders` (non-blocking, failure-safe).
    - Customer notification creation, single read/unread toggle, and mark-all-read publish `notification.created` / `notification.unread` to `rt:user:{user_id}`.
  - Files touched:
    - `app/core/config.py`, `app/db/session.py`, `.env.example`, `app/main.py`
    - `app/schemas/auth.py`
    - `app/services/redis_client.py`, `app/services/realtime_hub.py`, `app/services/ws_manager.py`
    - `app/api/v1/endpoints/ws.py`, `app/api/v1/endpoints/auth.py`, `app/api/v1/endpoints/customer_auth.py`, `app/api/v1/router.py`
    - `app/services/order_service.py`, `app/services/notification_service.py`
    - `tests/test_realtime_ws.py`, `docs/CHANGELOG.md`, `docs/API.md`
  - Frontend (`implesia-mart`): can now request single-use tickets from `POST /api/v1/auth/ws-ticket` (admin) or `POST /api/v1/customer/ws-ticket` (customer) and open `WS /api/v1/ws?ticket=<token>` for instant order alerts and live customer notifications.

- **Daily Handoff & Cross-Device Sync Doc (2026-11-21).**
  - Added `docs/HANDOFF.md` consolidating today's Planning decisions (Customer Platform Phases 6–10, SaaS Admin Phases A–G, Notification Architecture audit, Bengali communication preference), backend & frontend implementation summary, DevOps live audit & production deployment runbook, pending backlog, and Home Laptop resume steps.
  - Files touched: `docs/HANDOFF.md`, `docs/CHANGELOG.md`. Matching handoff added in `implesia-mart`.

- **Phase C Admin-Only Safe Deletion, Impact Analysis & Reconciliation (2026-11-21). Done (not live).** Strict `RequireSuperadmin` RBAC, atomic transactions, no new migrations.
  - **Orders (`app/api/v1/endpoints/admin_orders.py`, `app/services/order_admin_service.py`, `app/schemas/order.py`):**
    - Added `GET /api/v1/admin/orders/{order_id}/delete-impact` (`RequireSuperadmin`) returning order summary, held stock restore items, movement count, coupon redemption code, review/notification counts, and report impact warning.
    - Added `DELETE /api/v1/admin/orders/{order_id}` (`RequireSuperadmin`, body `{confirm: true, reconcile_stock: bool = true, reason: str}`): atomically locks products/variants, restores held stock AND inserts offsetting positive `adjustment` rows into `stock_movements` (keeping `sum(movements) == on_hand`), writes a full `ORDER_DELETED` audit snapshot in `audit_events`, cleans up cascading order children while nulling `order_id` on historical movements/reviews/notifications, and returns `{deleted_order_number, stock_restored_units, coupon_released, reports_synced}`.
  - **Badges (`app/api/v1/endpoints/admin_badges.py`, `app/services/badge_service.py`, `app/schemas/badge.py`):**
    - Restricted `DELETE /api/v1/admin/badges/{badge_id}` to `RequireSuperadmin` and added `GET /api/v1/admin/badges/{badge_id}/delete-impact` (`RequireSuperadmin`).
    - Upgraded `DELETE /api/v1/admin/badges/{badge_id}` with optional body `{mode: "unlink" | "merge" = "unlink", target_badge_id}`: protects `is_system=True` badges (409), merges or unlinks `ProductBadgeLink` rows (deduplicating products that already carry the target badge), recomputes `products.badge`, logs `BADGE_DELETED` in `audit_events`, and deletes atomically.
  - **Suppliers (`app/api/v1/endpoints/admin_inventory.py`, `app/services/inventory_service.py`, `app/schemas/inventory.py`):**
    - Restricted `DELETE /api/v1/admin/inventory/suppliers/{supplier_id}` to `RequireSuperadmin` and added `GET /api/v1/admin/inventory/suppliers/{supplier_id}/delete-impact` (`RequireSuperadmin`).
    - Upgraded `DELETE /api/v1/admin/inventory/suppliers/{supplier_id}` with optional body `{mode: "merge" | "archive" | "hard_delete" = "archive", target_supplier_id, reason, unlink_products}`: `merge` moves all purchases & products atomically to `target_supplier_id`, logs `SUPPLIER_MERGED`, and hard-deletes the old supplier; `archive` soft-deletes while preserving purchases and unlinking products; `hard_delete` is allowed only when `purchases_count == 0` (409 otherwise).
  - Files touched:
    - `app/models/audit_event.py`
    - `app/schemas/order.py`, `app/schemas/badge.py`, `app/schemas/inventory.py`
    - `app/services/order_admin_service.py`, `app/services/badge_service.py`, `app/services/inventory_service.py`
    - `app/api/v1/endpoints/admin_orders.py`, `app/api/v1/endpoints/admin_badges.py`, `app/api/v1/endpoints/admin_inventory.py`
    - `tests/test_phase_c_safe_delete.py`, `tests/test_product_badges.py`, `tests/test_inventory.py`, `tests/test_phase_a_accounting.py`
    - `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`, `docs/TODO.md`
  - Frontend (`implesia-mart`):
    - Only `superadmin` users should see Delete controls for Orders, Badges, and Suppliers; call the `/delete-impact` preview endpoint before confirming deletion/merge/archive.
    - `DELETE /api/v1/admin/inventory/suppliers/{id}` now returns `200 OK` with `SupplierDeleteResult` instead of `204`.

- **Phase B SaaS Reporting APIs & Product Analytics (2026-11-21). Done (not live).** SQL aggregates only, no new migrations.
  - **Expanded Report Presets & Filters (`app/schemas/report.py`, `app/services/report_service.py`, `app/api/v1/endpoints/admin_reports.py`):**
    - Expanded `preset` across all report endpoints to `today`, `7d`, `this_week`, `this_month`, `last_month`, `this_year`.
    - Added optional `supplier_id`, `origin` (`online` / `offline`), and `profit_filter` (`all` / `profit` / `loss` / `unknown_cost`) across report endpoints, plus `sort` (`revenue`, `profit`, `margin`, `units_sold`, `cost`, `stock_value`) on `/products` and `/products/export`.
  - **Profit & Loss Summary (`GET /api/v1/admin/reports/profit-loss` + `/export`) & Upgraded `ProfitReport`:**
    - Returns full P&L waterfall: `gross_sales`, `product_discount`, `coupon_discount`, `manual_discount`, `delivery_charge`, `returned_order_value`, `net_realized_sales`, `total_cost` (COGS), `gross_profit`, `loss_amount` (negative-margin line losses), `net_profit`, `margin_percent`, `collected_amount` (paid_amount / settled COD / Bangla QR advance), `due_amount`, `unknown_cost_lines`, `unknown_cost_units`, `unknown_cost_revenue`.
    - Upgraded `ProfitReport` with additive `loss_amount` and `net_profit`.
  - **Upgraded Product Performance (`GET /api/v1/admin/reports/products` + `/export`):**
    - Added per-product `slug`, `sku`, `category_name`, `supplier_id`, `supplier_name`, `avg_selling_price`, `unit_cost_avg`, `current_cost_price`, `current_stock`, `stock_value`, `is_loss`, and `returned_units`, with SQL-level `profit_filter` and `sort`.
  - **Channel & Payment Method Breakdown (`GET /api/v1/admin/reports/channels` + `/export`):**
    - Splits realized orders/units/net_sales/COGS/profit/margin/collected/due by `origin` (`online`/`offline`) AND by `payment_method` (`cod`, `bangla_qr`, `cash`, `bkash`, `nagad`, `card`, `due`).
  - **Supplier Performance Report (`GET /api/v1/admin/reports/suppliers` + `/export`):**
    - Aggregates per supplier: `linked_products_count`, `purchase_count`, `total_purchased_units`, `total_purchase_spend`, `units_sold`, `sales_revenue`, `cogs`, `net_profit`, `margin_percent`, `current_stock_units`, `current_stock_value`, plus report-wide totals.
  - **Upgraded Stock Valuation (`GET /api/v1/admin/reports/stock` + `/export`):**
    - Added `selling_price`, `potential_retail_value`, `expected_profit_on_hand`, `supplier_name` on `StockRow` and `potential_retail_value`, `expected_profit_on_hand`, `missing_cost_count` on `StockSummary`.
  - **Single Product Performance Analytics (`GET /api/v1/admin/products/{product_id}/analytics`):**
    - Added editor+ endpoint returning current stock/retail value, lifetime and last-30-day sales/COGS/profit/loss/margin/returns, and the 20 most recent stock movements.
  - Files touched:
    - `app/schemas/report.py`
    - `app/services/report_service.py`
    - `app/api/v1/endpoints/admin_reports.py`, `app/api/v1/endpoints/admin_products.py`
    - `tests/test_reports_saas.py`
    - `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`, `docs/TODO.md`
  - Frontend (`implesia-mart`):
    - Admin Reports Hub can call `/profit-loss`, `/channels`, `/suppliers`, enriched `/products` (with `sort` & `profit_filter`), upgraded `/stock`, and new presets (`today`, `7d`, `this_year`) plus `supplier_id` / `origin` filters and `.xlsx` exports.
    - Admin Product View page can call `GET /api/v1/admin/products/{product_id}/analytics` for lifetime/30d P&L, stock valuation, and recent stock movements.

- **Phase A Backend Schema & Accounting Fixes (2026-11-21). Done (not live).** Additive-only migration `0105` (`down_revision = "0104"`).
  - **Optional Supplier on Products + Per-Variant Cost Price (`alembic/versions/0105_product_supplier_and_variant_cost.py`, `app/models/product.py`, `app/schemas/product.py`, `app/services/product_service.py`, `app/services/variant_service.py`, `app/services/inventory_service.py`):**
    - Added nullable `products.supplier_id` (`UUID`, FK `suppliers.id ON DELETE SET NULL`, indexed `ix_products_supplier_id`) and nullable `product_variants.cost_price` (`Numeric(12, 2)`, check `>= 0`).
    - Admin product create/update accept optional `supplier_id` (validated active/non-deleted; `null` clears), admin reads return `supplier_id`, `supplier_name`, and `supplier` (`{id, name}`), and `GET /api/v1/admin/products` supports optional `supplier_id` filtering. Public storefront product endpoints never expose supplier or `cost_price`.
    - Admin variant create/update/read support optional `cost_price` per variant (preserving existing variant cost when omitted on edit). Online checkout, offline order creation/item edits, stock movements, and inventory exports use `variant.cost_price` when set, falling back to `product.cost_price`. `inventory_service.create_purchase` updates per-variant weighted-average `cost_price` when `variant_id` is set.
  - **Offline Order Complete Sync Fixes (`app/schemas/order.py`, `app/services/order_admin_service.py`, `app/services/order_service.py`, `app/api/v1/endpoints/admin_orders.py`):**
    - Added `initial_status: Literal["new", "confirmed", "delivered"] = "new"` and `mark_delivered: bool = False` on `OfflineOrderCreate`. Creating an offline order as `delivered` immediately sets `delivered_at = order.ordered_at or now`; delivering an offline order with `ordered_at` later preserves `delivered_at = order.ordered_at` so backdated offline sales align cleanly on their business date across all reports.
    - Automatically links `Order.user_id` on offline order creation when a registered customer matches `payload.phone`.
    - Added `POST /api/v1/admin/orders/{order_id}/payments` (`OrderPaymentCreate`) and `paid_amount` / `payment_reference` support on `PATCH /api/v1/admin/orders/{order_id}` (`OrderUpdate`), validating `0 <= paid_amount <= total`, recomputing `due_amount = total - paid_amount`, and logging `payment_updated` activity (migration `0105` widens `order_activities.action`).
  - **Returned-Order Accounting Bugfix (`app/services/report_service.py`, `app/schemas/report.py`):**
    - Excluded returned orders (`Order.status != 'returned'`) from realized sales revenue, order count, units sold, shipping, COGS, profit, trend, and no-sale-30d queries while keeping `delivery_report` (`delivered`, `returned`, new `returned_value`, `return_rate_percent`) and `product_report` (`return_count`, new `return_value`) reporting returns separately.
    - Exposed `manual_discount` separately alongside `coupon_discount` in `SalesSummary` and the sales Excel export.
  - Files touched:
    - `alembic/versions/0105_product_supplier_and_variant_cost.py`
    - `app/models/product.py`, `app/models/order.py`
    - `app/schemas/product.py`, `app/schemas/order.py`, `app/schemas/report.py`
    - `app/services/product_service.py`, `app/services/variant_service.py`, `app/services/inventory_service.py`, `app/services/order_service.py`, `app/services/order_admin_service.py`, `app/services/report_service.py`
    - `app/api/v1/endpoints/admin_products.py`, `app/api/v1/endpoints/admin_orders.py`
    - `tests/test_phase_a_accounting.py`, `tests/integration/test_0105_migration.py`, `tests/test_reports.py`
    - `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`, `docs/TODO.md`
  - Frontend (`implesia-mart`):
    - Admin product form & list can send/filter optional `supplier_id`, read `supplier_id`/`supplier_name`/`supplier` on admin product responses, and edit optional per-variant `cost_price`.
    - Admin offline order form can pass `initial_status: "delivered"` (or `mark_delivered: true`) for walk-in counter sales.
    - Admin order detail can collect due/partial payments via `POST /api/v1/admin/orders/{order_id}/payments` or update `paid_amount` via `PATCH /api/v1/admin/orders/{order_id}`.
    - Admin sales/delivery/product report screens can read `SalesSummary.manual_discount`, `DeliveryReport.returned_value`, and `ProductReportRow.return_value`.

- **QA & Migration Polish (2026-11-21). Done (not live).**
  - **Migration 0104 (`alembic/versions/0104_index_customer_order_fks.py`):** Additive-only indexes `ix_customer_notifications_order_id` and `ix_product_reviews_order_id` (and matching SQLAlchemy model indexes on `CustomerNotification` and `ProductReview`) so every foreign key column leads an index.
  - Updated `tests/integration/test_site_header_migration.py` to apply migration `0100` before calling `site_header_service.public_view` so the integration suite leaves the schema at HEAD.
  - Files touched: `alembic/versions/0104_index_customer_order_fks.py`, `app/models/notification.py`, `app/models/review.py`, `tests/integration/test_site_header_migration.py`, `docs/TODO.md`, `docs/CHANGELOG.md`, `docs/BUSINESS_LOGIC.md`.

- **Phase 6 Customer Dashboard Backend Upgrades (2026-11-21). Done (not live).** Additive-only, no new migrations.
  - **Dashboard Summary (`GET /api/v1/customer/dashboard-summary`):** Added `delivered_orders`, `cancelled_orders`, `total_products_purchased` (sum of `OrderItem.quantity` across non-cancelled/non-returned orders), and `unread_notifications` (count within the last 30 days) alongside existing `total_orders`, `active_orders`, `total_spent`, `customer_name`, `phone`, and `email`. Moved query logic into `customer_purchased_service.get_dashboard_summary`.
  - **Profile & Avatar:**
    - Added `DELETE /api/v1/customer/profile/avatar` to clear `avatar_url`, delete the owned file from `avatars/` storage, and return `CustomerProfileRead`. Replacing an avatar via `POST /api/v1/customer/profile/avatar` now also deletes the previous owned avatar file.
    - Updated `CustomerProfileUpdate` and `customer_auth_service.update_profile` so explicitly sending `null` or `""` (or whitespace) for `email`, `district`, `area`, or `address` cleanly clears the column to `NULL` while omitting a field preserves it.
  - **Notification 30-Day Auto-Deletion & Complete Triggers:**
    - Added throttled opportunistic execution of `purge_expired_notifications(db)` on notification list and creation (plus per-user expired cleanup on list and standalone `purge_expired_notifications` helper) so notifications older than 30 days are physically deleted from `customer_notifications`.
    - Triggered `create_order_status_notification` on new online order placement (`order_service.create_order`, for logged-in or phone-matched customers; skipped on idempotency replays), after commit on admin single-order status updates (`order_service.update_order`, now defaulting `notify_customer=True` and seeing updated courier/tracking fields), and on admin bulk status updates (`order_admin_service.bulk_status`, with optional `notify_customer` / `notification_language` on `BulkStatusRequest`).
    - Added `DELETE /api/v1/customer/notifications/{notification_id}` for customers to delete their own individual notification (404 if missing or owned by another user).
  - **Order Tracking Upgrade (`GET /api/v1/customer/orders/{order_number}/tracking`):**
    - Pulls real step timestamps from `order_activities` (`status_changed` rows) plus `order.created_at`, `order.delivered_at`, and `order.returned_at` instead of reusing `order.updated_at` for every completed step.
    - Cleanly handles `cancelled` and `returned` terminal statuses (lists reached forward steps followed by the terminal `cancelled` or `returned` step instead of falling back to step 0).
    - Added future-ready fields `tracking_url: str | None = None` and `live_events: list[dict] = []` on `OrderTrackingDetail` for Steadfast/Pathao live tracking integration.
  - **Purchased Products History Upgrade (`GET /api/v1/customer/purchased-products`):**
    - Returns full purchase line history across eligible orders without dropping repeat purchases of the same product across different orders.
    - Added `quantity`, `line_total`, `order_status`, `paid_amount`, `due_amount`, and `payment_status` (`paid` / `partial` / `cod_due` / `unpaid`) while keeping `can_review` accurate per product.
  - Files touched:
    - `app/schemas/customer.py`, `app/schemas/order.py`
    - `app/services/customer_auth_service.py`, `app/services/customer_purchased_service.py`, `app/services/notification_service.py`, `app/services/order_service.py`, `app/services/order_admin_service.py`
    - `app/api/v1/endpoints/customer_auth.py`, `app/api/v1/endpoints/customer_orders.py`
    - `tests/test_customer_phase6.py`
    - `docs/CHANGELOG.md`, `docs/API.md`, `docs/BUSINESS_LOGIC.md`, `docs/TODO.md`
  - Frontend (`implesia-mart`):
    - Dashboard overview can read `delivered_orders`, `cancelled_orders`, `total_products_purchased`, and `unread_notifications` from `GET /api/v1/customer/dashboard-summary`.
    - Profile page can call `DELETE /api/v1/customer/profile/avatar` to remove an avatar, and send `null` or `""` in `PATCH /api/v1/customer/profile` to clear optional fields (`email`, `district`, `area`, `address`).
    - Notifications drawer/page can call `DELETE /api/v1/customer/notifications/{notification_id}` to remove individual notifications.
    - Order tracking view should render `timeline` dynamically (including `cancelled`/`returned` terminal steps and nullable `timestamp`) and may read optional `tracking_url` and `live_events`.
    - Purchased products list receives full line history (repeat purchases of the same `product_id` across orders; key list items by `order_number + product_id` or index rather than `product_id` alone) and can display `quantity`, `line_total`, `order_status`, `paid_amount`, `due_amount`, and `payment_status`.

- **Customer Authentication, Customer Notifications & Verified Product Reviews (2026-11-21). Done (not live).**
  - **Migration 0101:** Added `customer` role to `UserRole` enum. Added nullable columns `phone` (varchar 20), `district` (varchar 80), `area` (varchar 120), and `address` (varchar 500) to `users` model. Added partial unique index on `phone` (where phone is not null).
  - **Migration 0103:** Added nullable `avatar_url` (varchar 500) to `users`. Created `customer_notifications` table (UUID pk, user_id FK cascade, order_id FK set null, type, title, message, is_read, language, timestamps, composite indexes on user_id + created_at and user_id + is_read). Created `product_reviews` table (UUID pk, product_id FK cascade, user_id FK cascade, order_id FK set null, rating 1-5, headline, comment, is_verified_purchase, is_published, timestamps, indexes on product_id + is_published + created_at and user_id + product_id).
  - **Customer Authentication & Profile Service:**
    - Standardized 11-digit Bangladesh phone validation and normalization (`013-019`).
    - Password hashing and verification with secure JWT session issuance (`access_token` and `refresh_token`).
    - Customer login accepts either phone or email.
    - Endpoints: `POST /api/v1/customer/auth/register`, `login`, `refresh`, `logout`, `GET`/`PATCH /api/v1/customer/profile`, `POST /api/v1/customer/change-password`, `POST /api/v1/customer/avatar`, `POST /api/v1/customer/cart/merge`.
  - **Orders, Tracking & Purchased Products:**
    - Customer orders list and detail endpoints with authorization check (only owner can view).
    - Courier tracking endpoint (`/api/v1/customer/orders/{number}/tracking`) returning carrier, tracking code, and timeline.
    - Purchased products endpoint (`/api/v1/customer/purchased-products`) returning past ordered items and review eligibility (`can_review`).
    - Customer dashboard statistics endpoint (`/api/v1/customer/dashboard-summary`).
  - **Verified Product Reviews:**
    - Customers can only review products from eligible orders (`confirmed`, `packed`, `shipped`, `delivered`).
    - Duplicate reviews per user/product are blocked with ConflictError (409).
    - Public reviews list with summary metrics (average rating, review count, 1-5 star histogram).
  - **Automated Customer In-App Notifications:**
    - Status updates on orders automatically trigger notification creation for registered customers with localized messages.
    - Notification feed and mark-as-read endpoints.
  - Files touched:
    - `alembic/versions/0101_customer_role_and_fields.py`
    - `alembic/versions/0103_customer_notifications_and_reviews.py`
    - `app/models/user.py`, `app/models/notification.py`, `app/models/review.py`
    - `app/schemas/customer.py`, `app/schemas/review.py`, `app/schemas/order.py`
    - `app/services/customer_auth_service.py`, `app/services/customer_purchased_service.py`, `app/services/notification_service.py`, `app/services/review_service.py`, `app/services/order_service.py`
    - `app/api/v1/endpoints/customer_auth.py`, `app/api/v1/endpoints/customer_orders.py`, `app/api/v1/endpoints/reviews.py`
    - `tests/test_customer_auth.py`, `tests/test_customer_phase6.py`
    - `docs/TODO.md`, `docs/CHANGELOG.md`

- **Storefront SEO settings (2026-11-16). Done (not live).** Branched from `cursor/admin-orders-management-aaf2` (PR #18) so the migration chain stays one head. Do not merge this ahead of that branch. Do not run the migration against production from a laptop. No new environment variable.
  - There was no site/store settings model. Header, footer, contact, payment, and pricing stay their own resources. This adds one `site_settings` row (slug `main`) for the home/default title, meta description, and optional title template.
  - Migration **0099** (`down_revision` **0098**), additive only. New table `site_settings`. `seo_title` (varchar 70, nullable), `seo_description` (varchar 170, nullable), `seo_title_template` (varchar 80, nullable). No row is seeded. No existing row is updated. Downgrade drops only that table.
  - Public `GET /api/v1/site/settings` (`Cache-Control: public, max-age=60`). Admin `GET` and `PATCH /api/v1/admin/site/settings` (editor or above, `Cache-Control: no-store`, audited). Body: `{ seo_title, seo_description, seo_title_template }`, each a string or `null`. PATCH omits a field to keep it. `null` or `""` clears it. A set template must contain `%s` once and no other `%`.
  - Files: `alembic/versions/0099_site_seo_settings.py`, `app/models/site_settings.py`, `app/schemas/site_settings.py`, `app/services/site_settings_service.py`, `app/api/v1/endpoints/site_settings.py`, `app/api/v1/router.py`, `tests/test_site_settings.py`, `tests/integration/test_0099_migration.py`, `bruno/Public/Site/`, `bruno/Private/Site/`, docs.
  - Frontend (`implesia-mart`): stop hardcoding the home/default title, meta description, and title template as the only source. Read `GET /api/v1/site/settings`. Use `seo_title` as the default/home title, `seo_description` as the default meta description, and `seo_title_template` as the title template (replace `%s` with the page title, for example `%s | Implesia Mart`). A `null` field means keep the current built-in default for that field. The response may be cached for 60 seconds. Admin Settings calls `GET` and `PATCH /api/v1/admin/site/settings` with the staff token (editor). Send `null` or `""` to clear a field. Do not send a fallback string in place of null. Lengths: title 70, description 170, template 80.
- **Order print fields, public tracking, and customer status messages (2026-11-16). Done (not live).** Do not run the migration against production from a laptop. Do not deploy.
  - Migration **0098** (`down_revision` **0097**), additive only. Nullable `orders.customer_sms_confirmed_at` and `orders.customer_sms_shipped_at`. Index `ix_orders_tracking_number_lower` on `lower(tracking_number)`. `order_activities.action` may also be `customer_message`. No existing row is updated. Totals, statuses, and dates stay as they were. The new timestamps stay NULL. Downgrade refuses while any activity is `customer_message`, then drops only the new index, the new check value, and the two columns.
  - `POST /api/v1/admin/orders/print-data` adds `invoice_id` (`INV-` plus the order number's hex body; no new sequence), `order_number` (same as `number`), `estimated_delivery_date` (computed, not stored: order date in Asia/Dhaka plus `DELIVERY_DAYS_INSIDE_DHAKA` default 2 for inside and suburban, or `DELIVERY_DAYS_OUTSIDE_DHAKA` default 5 for outside), `email` (`""` when none), `full_address`, and per item `variant_label`, `sku`, `product_id_short` (first 8 hex characters of the product UUID, `""` if the product is gone), `quantity`, `unit_price`, `line_total`. Existing money fields are the stored totals.
  - `POST /api/v1/orders/lookup` is still the only public status lookup. Body is the phone plus exactly one of `number` or `tracking_number`. Both or neither is 422. A wrong phone and an unknown id are the same 404. Response adds `timeline` (`status` and `at` only) and `items[].variant_label`. `due_amount` is the cash still due. No address, email, notes, or staff fields. Limit stays `RATE_LIMIT_ORDER_LOOKUP` (default 30/minute) per client address.
  - A real move to `confirmed` or `shipped` (single or bulk, online or offline) can queue a short Bengali message. The status call does not wait and does not fail if the send fails. The same status is not sent twice. The result is an activity row `customer_message`. `CUSTOMER_SMS_ENABLED` defaults off. `CUSTOMER_SMS_PROVIDER` is `log` or `noop` only. No handset is contacted. The link, when `ADMIN_BASE_URL` is set, is `{ADMIN_BASE_URL}/order-status?number={number}`.
  - No SMS account is connected. The API does not read `SMS_SSLWIRELESS_API_TOKEN`, `SMS_SSLWIRELESS_SID`, or `SMS_SSLWIRELESS_API_URL`. Those names are comments in `.env.example` only. A real send needs an SSL Wireless ISMS Plus (SMS Plus) account: the API token and the registered sender id (`sid`) from that panel, and the server's outbound IP whitelisted there. The send URL they document is `https://smsplus.sslwireless.com/api/v3/send-sms`. Setting the variables does nothing until a provider adapter is added. Until then `log` writes the text to the API log and `noop` drops it.
  - Files: `alembic/versions/0098_order_print_and_customer_sms.py`, `app/models/order.py`, `app/schemas/order.py`, `app/services/customer_notify.py`, `app/services/order_service.py`, `app/services/order_admin_service.py`, `app/services/product_options.py`, `app/core/config.py`, `.env.example`, tests, `bruno/`, docs.
  - Frontend (`implesia-mart`): print and invoice screens should read `invoice_id`, `order_number`, `estimated_delivery_date`, `email`, `full_address`, `courier_name`, `tracking_number`, and each item's `title`, `variant_label`, `sku`, `product_id_short`, `quantity`, `unit_price`, `line_total`. The order-status page calls the same `POST /api/v1/orders/lookup` with `{ number, phone }` or `{ tracking_number, phone }`, never both. Read `status`, `timeline` (`status`, `at`), `courier_name`, `tracking_number`, `items`, `subtotal`, `shipping`, `total`, `due_amount`. Prefill the order number from `?number=`. Do not show address, email, or staff fields. Customer texts are not delivered until an SMS account is connected on the API host. The exact contract is in `docs/API.md`.
- **Admin orders desk (2026-11-16). Done (not live).** No new environment variable on that change. Do not run the migration against production from a laptop.
  - Migration **0097** (`down_revision` **0096**), additive only. New columns on `orders`: `origin` (NOT NULL, server default `online`), `call_status` (NOT NULL, server default `not_called`), `manual_discount` (NOT NULL, default 0), `paid_amount` (NOT NULL, default 0), `printed_at` (nullable), `ordered_at` (nullable). New table `order_activities`. Status check widened with `packed`. Payment check widened with `cash`, `bkash`, `nagad`, `card`, `due`. No existing row is updated. Totals, coupons, and statuses stay as they were. Existing rows read as `origin=online`. Downgrade refuses while any order is `packed` or uses an offline payment method, then drops only the new table, checks, indexes, and columns.
  - Status flow: `new` → `confirmed` → `packed` → `shipped` → `delivered`, plus `cancelled` and `returned`. `confirmed` is the ready-to-pack queue. Old rows are not rewritten, so a `confirmed` order from before this change must be packed before it can ship. Transitions are enforced on single and bulk updates. Cancel restores stock and gives the coupon use back. Return restores stock and keeps the coupon use. Nothing is hard-deleted.
  - `orders.origin` is `online` or `offline`. This is not `orders.source` (`cart` or `direct`). Offline create reuses checkout stock, cost snapshot, and server totals. Staff may set a unit price, a manual discount, and a delivery charge. Those are validated. Client totals are not accepted. Offline orders do not send Meta Purchase, the Telegram new-order or cancel alert, or a GA event. A low-stock Telegram can still fire from the stock claim. They show up in the order list, history, dashboard, sales reports, and Excel exports like any other order.
  - New editor routes under `/api/v1/admin/orders`: `GET /overview`, `GET /customers`, `GET /ready-to-pack`, `POST /offline`, `POST /bulk-status`, `POST /printed`, `POST /print-data`, `PUT /{id}/items`. The list accepts origin, payment, call status, courier, and a date range, and returns `status_counts`. Detail adds history, a duplicate warning, courier fields, and the activity log. The contract is in `docs/API.md`.
  - Files: `alembic/versions/0097_orders_management.py`, `app/models/order.py`, `app/schemas/order.py`, `app/schemas/payment.py`, `app/schemas/report.py`, `app/services/order_service.py`, `app/services/order_admin_service.py`, `app/services/dashboard_service.py`, `app/services/report_service.py`, `app/api/v1/endpoints/admin_orders.py`, `app/api/v1/endpoints/orders.py`, tests, `bruno/Private/Orders/`, docs.
  - Frontend (`implesia-mart`): build the orders desk against `docs/API.md`. Use `origin`, not `source`, for online versus offline. Ready to pack is status `confirmed`. Do not fire the browser Purchase or GA event when `origin` is `offline`. `POST /api/v1/orders` omits the new staff fields. Dashboard status slices are now seven, including `packed`. There is no `ROADMAP.md` in this repo.
- **Coupons (2026-11-10). Done (not live).** Stacked on PR #14 (`cursor/telegram-order-alerts-f0d3`). Do not merge into `main` or `testing` ahead of that branch. No new environment variable.
  - Migration **0096** (`down_revision` **0095**), additive only. New tables `coupons`, `coupon_products`, `coupon_categories`, `coupon_redemptions`. Nullable `orders.coupon_code` and `orders.coupon_discount`. No existing row is updated. Old orders stay NULL and their totals are not rewritten. Downgrade drops only the new tables, the new check, and the two columns.
  - The shopper sends only `coupon_code`. The discount, free delivery, and the new total are computed on the server. A quote reports a bad code and still returns prices. Placing an order re-checks the code in the same transaction with the coupon row locked (`SELECT … FOR UPDATE` on PostgreSQL) and rejects the order when the code is no longer valid. The redemption is written in that transaction.
  - Cancelling an order marks the redemption cancelled, so the use comes back. Returning an order leaves the redemption counted.
  - Sales, profit, product, and trend figures subtract the coupon. `GET /api/v1/admin/reports/coupons` and `/export` count uses by the day the order was placed.
  - Files: `alembic/versions/0096_coupons.py`, `app/models/coupon.py`, `app/schemas/coupon.py`, `app/services/coupon_service.py`, `app/api/v1/endpoints/admin_coupons.py`, `app/services/order_service.py`, `app/services/report_service.py`, `app/services/meta_capi.py`, `app/schemas/order.py`, `app/schemas/report.py`, `app/models/order.py`, `app/core/exceptions.py`, `app/api/v1/router.py`, `app/api/v1/endpoints/admin_reports.py`, tests, `bruno/Private/Coupons/`, `bruno/Private/Reports/`, docs.
  - Frontend (`implesia-mart`): send optional `coupon_code` on quote and on order create. Do not send a discount amount or a total. Read `coupon` on the quote and `coupon_code` / `coupon_discount` on the order. Show the Bangla `message` from a quote's invalid coupon, and from `error.message` when create returns 422. Admin coupon screens call `/api/v1/admin/coupons` (viewer reads, editor writes). The coupon report is `GET /api/v1/admin/reports/coupons`. The contract is in `docs/API.md`. There is no delete. Code generation stays in the admin UI.
- **Telegram order alerts and staff new-order feed (2026-11-10). Done (not live).** Stacked on PR #13 (`cursor/meta-capi-purchase-7f88`). Do not merge into `main` or `testing` ahead of that branch.
  - `GET /api/v1/admin/orders/new` (any signed-in staff, including viewer). Query: `since` (optional ISO-8601) and `limit` (1–50, default 20). Newest first, strictly `created_at > since` and `created_at <= now`. No `since` means the last 24 hours. Response: `{"now", "items": [{id, number, customer_name, total, payment_method, created_at}]}`. `payment_method` is the stored value `cod` or `bangla_qr`. Anonymous is 401. The editor order list is unchanged (viewer still 403 there).
  - `ix_orders_created_at` already exists (migration 0005). No second index.
  - Migration **0095** (`down_revision` **0094**), additive only. `orders.telegram_notified_at` (timestamptz, nullable). No row is updated. Downgrade drops only that column.
  - After a new order commits, one Telegram message can go to every `TELEGRAM_CHAT_IDS` chat. The claim is `UPDATE … WHERE telegram_notified_at IS NULL` in the request, before the HTTP task is queued, so a second worker or an idempotency-key replay does not send again. Empty `TELEGRAM_BOT_TOKEN` or empty chat ids: no HTTP, the column stays NULL, checkout is unchanged. Failure, timeout, or an exception is logged with the order number only and the shopper still gets 201.
  - The message is Telegram HTML: order number, customer name, phone, area, each product with quantity, total, COD due or Bangla QR advance paid and remaining, and `{ADMIN_BASE_URL}/admin/orders/{id}` when the base URL is set. The storefront list uses that UUID path (`app/admin/orders/[number]` is only the folder name; the link value is `order.id`).
  - `TELEGRAM_NOTIFY_ORDER_CANCELLED` and `TELEGRAM_NOTIFY_LOW_STOCK` default off. Cancel alerts when a status change actually becomes `cancelled`. Low stock alerts when a product's on-hand quantity crosses from above 5 to 5 or below (`LOW_STOCK_THRESHOLD`, same cutoff as the stock report). A later sale while it stays at or below 5 does not alert again. Made-to-order (NULL quantity) does not alert. Admin product-form quantity edits do not alert.
  - Files: `alembic/versions/0095_order_telegram_notified_at.py`, `app/services/telegram_notify.py`, `app/services/order_service.py`, `app/services/inventory_service.py`, `app/api/v1/endpoints/admin_orders.py`, `app/api/v1/endpoints/admin_inventory.py`, `app/api/v1/router.py`, `app/schemas/order.py`, `app/models/order.py`, `app/core/config.py`, `.env.example`, `tests/test_telegram_orders.py`, `tests/integration/test_0095_migration.py`, `tests/conftest.py`, `bruno/Private/Orders/04 New Orders.bru`, docs.
  - Frontend (`implesia-mart`): poll `GET /api/v1/admin/orders/new` with the staff token (viewer is allowed). Send the previous `now` as `since`. Read `items[].number` (not a separate `order_number` on this payload) and `payment_method` as `cod` or `bangla_qr`. No storefront change. Telegram stays off until `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, and optionally `ADMIN_BASE_URL` are set on the API host. Do not put the token in the repo.
- **Meta Conversions API Purchase on order create (2026-11-10). Done (not live).**
  - After a new order commits, the API sends one Meta `Purchase` event in the background. A network error, timeout, or exception is logged with the order number only and does not change the 201 response. The same idempotency key and later status updates do not send again. No migration.
  - `POST /api/v1/orders` accepts an optional `tracking` object (`fbp`, `fbc`, `event_source_url`, each a string or null, max 500). Missing, unknown, or invalid values are ignored. Clients that omit `tracking` are unchanged.
  - The order response already returns the number as `number`. It now also returns `order_number` (the same string) and `analytics_event_id` (`purchase_` plus that string) on every `OrderRead`, including admin reads. Public lookup is unchanged.
  - The event is sent only when both `META_PIXEL_ID` and `META_CAPI_TOKEN` are set. `META_TEST_EVENT_CODE` is optional. Empty pixel id or token disables sending with no error. No id or token is stored in the repo.
  - Files: `app/services/meta_capi.py`, `app/services/order_service.py`, `app/api/v1/endpoints/orders.py`, `app/schemas/order.py`, `app/core/config.py`, `.env.example`, `tests/test_meta_capi.py`, `tests/conftest.py`, docs.
  - Frontend (`implesia-mart`): on `POST /api/v1/orders`, you may send `tracking: { fbp, fbc, event_source_url }`. Read `order_number` and `analytics_event_id` from the 201 body. The browser Pixel `Purchase` `eventID` must be `analytics_event_id` (`purchase_<order_number>`), the same id the server sends, so Meta can deduplicate. `number` is still the order number.
- **Testing branch: 0094 migration test survives the 0092 column cycle (2026-11-10).**
  - On the shared Postgres integration database, `test_0092_migration` drops `orders.delivered_at` and `orders.returned_at` and adds them back. PostgreSQL drops `ix_orders_delivered_at` and `ix_orders_returned_at` with those columns. Migration 0092 does not recreate them; they belong to 0094. `test_0094_migration` treated a present `channel` column as "0094 is already applied" and its downgrade failed with `index "ix_orders_returned_at" does not exist`.
  - The test now creates those two indexes when they are missing before it downgrades, and again in its cleanup. The migration files are unchanged.
  - Files: `tests/integration/test_0094_migration.py`, docs. Frontend: no change.
- **Admin sales reports (2026-11-10).** Depends on the unmerged inventory ledger (PR #9, migration 0093) and the cost-price work (PR #8, migration 0092). This branch is based on `cursor/inventory-ledger-2808` and its PR targets that branch. Do not merge it into `main` before those two.
  - Migration **0094** (`down_revision` **0093**), additive only. `orders.channel` (varchar 32, nullable, indexed, no server default) and `order_items.unit_cost` (numeric(12, 2), nullable, null or `>= 0`). Indexes on `orders.delivered_at` and `orders.returned_at`. No row is updated. Old orders stay `channel` NULL and old lines stay `unit_cost` NULL. `orders.source` and `ck_orders_source_known` are unchanged. Downgrade drops only the new indexes, the check, and the two columns.
  - New checkout orders store `channel = "website"` and copy `products.cost_price` onto each line as `unit_cost`. A later cost edit does not change the line. Neither field is on a public response.
  - Read-only reports at `/api/v1/admin/reports` (any signed-in staff, including viewer). Dates are Asia/Dhaka. Sales count by `delivered_at`. See BUSINESS_LOGIC.md and API.md for each metric.
  - The dashboard overview is SQL aggregates. Its delivered count uses `delivered_at`. Revenue, orders, and the chart still follow `created_at`.
  - Every report has an `.xlsx` export. The sheet states the filter and the dates. Money cells are numbers.
  - Files: `alembic/versions/0094_order_channel_and_unit_cost.py`, `app/models/order.py`, `app/services/order_service.py`, `app/services/shop_sql.py`, `app/services/report_service.py`, `app/services/dashboard_service.py`, `app/services/inventory_excel.py`, `app/schemas/report.py`, `app/api/v1/endpoints/admin_reports.py`, `app/api/v1/router.py`, `tests/test_reports.py`, `tests/test_dashboard.py`, `tests/integration/test_0094_migration.py`, `tests/integration/test_reports_postgres.py`, `bruno/Private/Reports/`, docs.
  - Frontend (`implesia-mart`): no storefront change. Do not add `unit_cost`, `channel`, or `cost_price` to public types. An admin reports screen can call the new `/api/v1/admin/reports` routes (viewer reads). The dashboard "delivered" number is now orders delivered in the window, not orders created then and still in status delivered.
- **Inventory ledger (2026-11-09).** Depends on the unmerged cost-price work (PR #8, migration 0092). This branch is based on `cursor/order-delivery-cost-price-d6aa` and its PR targets that branch so it can merge after PR #8.
  - New tables only, migration **0093** (`down_revision` **0092**): `suppliers`, `purchases`, `purchase_items`, `stock_movements`, `import_batches`, plus indexes and checks. A PostgreSQL trigger blocks DELETE and any edit of a movement except nulling a foreign key when the parent row is deleted. No existing column or row is changed. Downgrade drops only those tables and the trigger. Current stock numbers stay as they are until a purchase, adjustment, or order moves them.
  - Admin API under `/api/v1/admin/inventory` (viewer read, editor or above write): suppliers, purchases, movements, stock adjustments, opening stock, `.xlsx` export, blank import templates, and a two-step import (preview, then confirm). Purchases update stock and `products.cost_price` by weighted average. Order claim writes a `sale` movement and cancel/return write `cancel` or `return`, in the same transaction as the stock change. `python -m scripts.opening_stock` records opening balances without changing counts and is safe to run twice.
  - `openpyxl` added in `pyproject.toml` and `uv.lock`.
  - Files: `alembic/versions/0093_inventory_ledger.py`, `app/models/inventory.py`, `app/models/__init__.py`, `app/schemas/inventory.py`, `app/services/inventory_service.py`, `app/services/inventory_excel.py`, `app/services/order_service.py`, `app/api/v1/endpoints/admin_inventory.py`, `app/api/v1/router.py`, `scripts/opening_stock.py`, `tests/test_inventory.py`, `tests/integration/test_0093_migration.py`, `tests/test_qa_hardening.py`, docs.
  - Frontend (`implesia-mart`): no storefront change. Do not add `unit_cost` or ledger fields to public product types; the public API does not send them. An admin inventory screen can call the new `/api/v1/admin/inventory` routes (viewer reads, editor writes).
- **Order delivery timestamps and admin-only product cost (2026-11-09).**
  - `orders.delivered_at` and `orders.returned_at` (timestamptz, nullable). The first time an order becomes `delivered` or `returned`, that column is set to the current UTC time and never overwritten. Admin `OrderRead` (list, detail, update, and the placed-order response) includes both; public order lookup does not.
  - `products.cost_price` (numeric(12, 2), nullable, `>= 0`). Readable and writable on the admin product create, update, get, and list for editor or above. It is not on any public product schema (catalog, detail, search, category products, home cards).
  - Migration **0092** (additive; `down_revision` 0091). Adds the three columns, check `ck_products_cost_price_non_negative`, and `ix_orders_status` (there was no index leading with `orders.status`). Backfill sets the timestamps from the earliest `audit_events` row with action `ORDER_STATUS_CHANGED` and `metadata.to` of `delivered` or `returned`. There is no separate status-history table. An order with no such row stays NULL. `created_at` / `updated_at` are not used. Downgrade drops only the new columns, that check, and `ix_orders_status`.
  - Files: `alembic/versions/0092_order_timestamps_and_cost_price.py`, `app/models/order.py`, `app/models/product.py`, `app/schemas/order.py`, `app/schemas/product.py`, `app/services/order_service.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_order_timestamps.py`, `tests/test_cost_price.py`, `tests/integration/test_0092_migration.py`, `tests/integration/test_order_timestamps.py`, `tests/test_product_urls.py`, docs.
  - Frontend (`implesia-mart`): admin order screens can show `delivered_at` and `returned_at` (ISO datetimes, or null). Admin product create/update can send `cost_price` (number or null) and admin product reads return it. Do not add `cost_price` to any storefront product type; the public API does not send it.
- **Order phone accepts +880 / 880 spellings (2026-11-03).**
  - `OrderCreate.phone` and `OrderLookup.phone` now use the shared `normalize_phone` (`app/schemas/inquiry.py`): `01XXXXXXXXX`, `8801XXXXXXXXX` or `+8801XXXXXXXXX`, spaces, dashes, dots, brackets and Bengali digits ignored, stored as `01XXXXXXXXX` (same as existing rows). Before, `+8801…` was reduced to 13 digits and rejected with 422. Operator prefix must be 013–019 (as for inquiries and site contact); 010–012 are now refused. Error message unchanged.
  - Files: `app/schemas/order.py`, `tests/test_order_phone.py`, docs. No migration. Frontend: checkout validation updated in the same task.
- **Bangla QR payment: admin QR image and partial advance at checkout (2026-11-03).**
  - New table `payment_settings` (one row, slug `main`) with the Bangla QR image path. Public `GET /api/v1/site/payment` (`no-store`) → `{bangla_qr_src, bangla_qr_enabled}` (`null`/`false` when none). Admin (editor auth, audited, `no-store`): `GET /api/v1/admin/site/payment`, `POST …/qr` (multipart `image`, checked by bytes, 5 MB, rate-limited; replacing deletes the old file), `DELETE …/qr`. Files go to the new `media/payment/` folder.
  - Orders: `payment_method` may be `cod` or `bangla_qr`. New columns `advance_percent` (25/50/75/100), `advance_amount`, `due_amount`, `payment_reference` (transaction ID / sender number). The server computes `advance = ceil(total × % / 100)` and `due = total − advance`; the client never sends amounts. `bangla_qr` is refused (422) while no QR is set; percent and reference are validated. `QuoteRead.bangla_qr_options` gives the four choices for the quoted total (empty with no QR). `OrderRead` / `PublicOrderRead` return the payment fields; only `OrderRead` has `payment_reference`.
  - Migration **0091** (additive; applied to the local dev DB only, downgrade checked): creates `payment_settings` (no seed row → feature off until a QR is uploaded), adds the four order columns, replaces the check `ck_orders_ck_orders_payment_cod` (double-prefixed name from 0005) with `ck_orders_payment_known`, adds `ck_orders_advance_percent_known` and `ck_orders_advance_non_negative`. No row is updated. Downgrade refuses while any `bangla_qr` order exists.
  - Tests: `tests/test_bangla_qr_payment.py` (ceil split, upload/replace/delete + live public read + auth, refused without QR, invalid percent/reference/client amounts, stored split in placed and admin order, COD due = total).
  - Files: `alembic/versions/0091_bangla_qr_payment.py`, `app/models/payment_settings.py`, `app/models/order.py`, `app/models/__init__.py`, `app/schemas/payment.py`, `app/schemas/order.py`, `app/services/payment_service.py`, `app/services/order_service.py`, `app/services/image_storage.py`, `app/api/v1/endpoints/site_payment.py`, `app/api/v1/router.py`, `tests/test_bangla_qr_payment.py`, docs.
  - Frontend (`implesia-mart`, branch `feat/bangla-qr-payment`): admin "Payment QR" page, QR card on the product page, "Bangla QR" checkout method sending `payment_method` / `advance_percent` / `payment_reference`, payment block in admin order details. Deploy the backend (and run 0091) before the frontend.
- **Uploaded media is stored in Cloudflare R2 (2026-11-03).**
  - Photos and videos are uploaded to the S3-compatible bucket when `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `MEDIA_PUBLIC_BASE_URL` are all set. The object key is `<folder>/<name>` (the same layout as the old disk path). The database value stays `/media/<folder>/<name>`. `Content-Type` is set from the sniffed type.
  - `GET` and `HEAD /media/<folder>/<name>` answer `307` to `MEDIA_PUBLIC_BASE_URL/<folder>/<name>` in that mode. Paths that leave the known folders, or that contain `..`, are `404`.
  - Deleting an owned media reference deletes the object. When the five settings are empty, writes, reads, and deletes stay on `media_root` (local disk), which is what tests and local Compose use. A partial set of the five settings refuses to start.
  - Existing files on the VPS volume are not moved by the app. The copy command (rclone or `aws s3 sync`, same keys) is in `docs/deploy-media-persistence.md`.
  - Removed the committed Wrangler account cache and ignored `.wrangler/`.
  - Files: `app/core/config.py`, `app/core/media_files.py`, `app/services/image_storage.py`, `app/main.py`, `pyproject.toml`, `uv.lock`, `tests/test_object_storage.py`, `tests/conftest.py`, `tests/test_deploy_config.py`, `.env.example`, `.gitignore`, `docker-compose.prod.yml`, `render.yaml`, `docs/deploy-media-persistence.md`, docs.
  - Frontend: no API change. Keep using the `/media/...` values the API returns. The browser follows the redirect to `https://media.implesia.com/...`. If an image optimizer refuses a redirect to another host, allow `media.implesia.com` or load that host directly.
- **Showcase choices: published products from any category (2026-11-03).**
  - Bug 1: `choices` in `GET /api/v1/admin/home/showcase` were "every product in the row key's category subtree", with no `published` filter. So the Add product modal listed hidden products (live: the `fashion` category holds only hidden products) and never the published ones (live: all 5 published products are in `electronics-2`).
  - Bug 2: the Trending row has key `gadgets`, but live has no `gadgets` category (`GET /categories/gadgets` → 404), so its `choices` were empty and the frontend disabled "Add product".
  - Fix: `choices` = every published product (title order), the same list for each row, read once per request. `POST`/`PATCH /admin/home/showcase/rows/{key}/items` accept any published product and reject a hidden one with 422 "Choose a published product" (an edit may keep the product already in that slot even if it was hidden since). The row key is now only an identifier; the old "Choose a product from this category" 422 is gone. First-run seeding still picks published products from the key's category. No migration, response shape unchanged.
  - Tests: `tests/test_home_showcase.py` (hidden product refused; new `test_showcase_choices_are_published_products_from_any_category`).
  - Files: `app/services/home/showcase_service.py`, `tests/test_home_showcase.py`, docs.
  - Frontend (`implesia-mart`, branch `feat/showcase-trending`): Trending row shown under the hero with a new tile design, admin copy says "published products". No API change needed there; deploy both together.
- **Variant products keep their card discount after a save (2026-11-03).**
  - Bug: saving a variant product in the dashboard without changing its variants sends `price` + `compare_at_price: null`; the update wrote those on the product row and skipped the variant roll-up. Product cards read `products.compare_at_price`, so the struck-through price and the `-X%` badge vanished (live: every product had `compare_at_price: null` in `GET /api/v1/products` while its variants still had compare-at prices, e.g. ৳945 / ৳1,350).
  - Fix: `product_service.update_product` now calls `variant_service.sync_price` for variant products after every save, so `price` / `compare_at_price` always come from the cheapest active variant (same rule as `rollup`, shared helper `_copy_cheapest_price`).
  - Migration **0090** (data only, no schema change): re-syncs `price` / `compare_at_price` of products with variants from their variants. Plain products, variants, carts and orders are untouched; no downgrade action. Checked on the local DB: the broken row was repaired, plain products' checksum unchanged.
  - Test: `tests/test_variants.py::test_saving_the_form_keeps_the_card_price_from_the_variants`.
  - Files: `app/services/product_service.py`, `app/services/variant_service.py`, `alembic/versions/0090_variant_card_price_resync.py`, `tests/test_variants.py`, docs.
  - Frontend: no change needed. The product card (`app/(client)/products/_components/product-card.tsx`) already shows the selling price, the struck-through regular price and a `-X%` badge top-right (custom badges sit top-left) whenever `compare_at_price > price`.
- **Quantity discount on the line total, rounded up (2026-11-02).**
  - New rule in the one pricing function (`pricing_service.price_line`, used by the product page block, cart, quote and order): `total = selling price × quantity`, `final = ceil(total − total × tier % / 100)`, `discount = total − final`. Replaces the old "unit price − round(regular × extra %)" rule. Tier lookup is unchanged (nearest tier at or below the quantity; none → no discount). Integer maths in `discounted_total()` (hundredths of a percent), so 2772 stays 2772. The browser still never sends a price.
  - Response shape unchanged, meaning changed: `unit_price` on cart, quote and order lines is now the quantity-1 selling price; `line_total` is the discounted, rounded-up amount, so `unit_price × quantity − line_total` = the quantity discount in taka. `quantity_discount_percent` is the tier % applied to the line. No migration; placed orders keep their stored snapshot (older orders keep the old per-unit prices).
  - Tests: `tests/test_pricing.py` (owner examples 700 × 2/3/4, nearest lower tier, no tiers, exact integer maths, updated cart/quote/order expectations); expected totals updated in `tests/test_cart.py`, `tests/test_orders.py`, `tests/test_variants.py`.
  - Files: `app/services/pricing_service.py`, `app/schemas/cart.py` (comment), `tests/test_pricing.py`, `tests/test_cart.py`, `tests/test_orders.py`, `tests/test_variants.py`, docs.
  - Frontend (`implesia-mart`, same task): `lib/mart-api/pricing.ts` mirrors the rule for instant display; product page shows `qty × price = total − discount (x %) = final`; cart drawer and checkout show the quantity discount line from `quantity_discount_percent`.
- **Home video/media section (2026-11-02).**
  - New table `home_media` (migration **0089**, additive, no seed row; applied to the local dev DB only). Model `HomeMedia`, schemas `app/schemas/home/media.py` (`MediaWrite`, `MediaAdmin`, `MediaPublic`, `MediaUploaded`), service `app/services/home/media_service.py`, endpoints `app/api/v1/endpoints/home/media.py`.
  - Public `GET /api/v1/home/media` → the section or `null` (inactive, empty, or no usable media). Admin (editor auth, audited, `no-store`): `GET`/`PUT /api/v1/admin/home/media`, `POST /api/v1/admin/home/media/image` (5 MB), `POST /api/v1/admin/home/media/video` (MP4/WEBM, 50 MB). Files are stored in `media/home-media/` (new storage folder); replaced or dropped files are deleted on save.
  - Validation: YouTube links reuse `youtube_id()` and are stored as the id; button link must be `/path` or `https://`; `cta_enabled` needs label and link; publishing needs a heading and the chosen type's media.
  - Frontend must: call `GET /api/v1/home/media` with no cache and render it above the testimonials; add the admin editor that uploads files to `…/image` / `…/video` and then `PUT`s `youtube_url` (link) rather than the id. Done in the frontend repo in the same task.
  - Files: `alembic/versions/0089_home_media.py`, `app/models/home/media.py`, `app/models/__init__.py`, `app/schemas/home/media.py`, `app/services/home/media_service.py`, `app/services/image_storage.py`, `app/api/v1/endpoints/home/media.py`, `app/api/v1/router.py`, `tests/test_home_media.py`, `tests/test_write_schema.py` (write-schema count 130 → 131), docs.
- **SEO follow-ups: `updated_at` for the sitemap, readable Bengali slugs (2026-11-02).**
  - `PublicProductCard` (list items, `GET /products/by-slug/{slug}`, `GET /products/{id}`) and category tree nodes (`GET /categories/tree`) now return `updated_at` (ISO datetime, the row's last change). Additive, nullable in the schema; no migration.
  - New products with a Bengali title get a phonetic Latin slug (`app/services/transliteration.py`): "স্মার্ট ঘড়ি" → `smart-ghori` instead of `smaartt-ghddi`. Only `allocate_slug` on create uses it; existing slugs never change (editing a title keeps the slug) and an explicit `slug` in the payload still wins. Duplicates get `-2`, `-3`…
  - Files: `app/schemas/product.py`, `app/schemas/category.py`, `app/services/product_service.py`, `app/services/category_service.py`, `app/services/transliteration.py`, `tests/test_product_seo.py`, `tests/test_product_urls.py` (`updated_at` is no longer in its "internal fields" list).
  - Frontend (same day): sitemap categories and real `lastModified`, product JSON-LD shipping/return policy/AggregateOffer, catalog canonicals and 307, verification meta, HSTS, gallery alt fallback.
- **Product SEO fields and editable slug (2026-11-02).**
  - `products.seo_title` (max 120), `seo_description` (max 320), `seo_keywords` (max 500, comma separated, trimmed and de-duplicated), all default `""`. Accepted on `POST`/`PATCH /admin/products` (on PATCH, omitted or `null` = keep) and returned in `AdminProductRead` and `PublicProductDetail`.
  - `PATCH /admin/products/{id}` accepts `slug` (lowercased; `^[a-z0-9]+(-[a-z0-9]+)*$`, max 160). A slug used by another product returns 409 `{"errors": [{"field": "slug", "message", "fix"}]}` (Bengali); a bad format is 422.
  - Old slugs keep working: on a slug change the old slug is stored in the new table `product_slug_redirects` (slug PK, product_id FK ON DELETE CASCADE). `GET /products/by-slug/{slug}` falls back to it (published products only). Changing back to an old slug, or a new product taking an old slug, removes that redirect row.
  - Migration `0088_product_seo_fields` (additive: 3 columns with server default `''` and the new table; has a downgrade). Applied to the local dev DB only; products, published count and price sum unchanged.
  - Files: `alembic/versions/0088_product_seo_fields.py`, `app/models/product.py`, `app/models/__init__.py`, `app/schemas/product.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_product_seo.py`.
  - Frontend (same day): admin SEO section (preview, counters, slug), storefront metadata and JSON-LD use the fields, `htmlLimitedBots` head-metadata fix and per-page share cards.
- **Admin-configurable max quantity per order (replaces the hardcoded 5).**
  - `pricing_settings.max_quantity` (default 10, 1–1000): the store-wide limit of pieces of one product (or one option) per order. `GET`/`PUT /api/v1/admin/pricing` read/write it as `max_quantity_per_order`; omitting it on `PUT` keeps the stored value.
  - A product's `max_order_quantity` is now "custom limit": NULL = use the store-wide limit, a number (1–1000) replaces it for that product (higher or lower).
  - Cart add/update, quote and order check the quantity against min(effective limit, stock). Over the limit: 422 "এই পণ্যটি এক অর্ডারে সর্বোচ্চ Nটি নেওয়া যাবে।" (Bengali digits). Over stock: "স্টকে এতগুলো নেই। পরিমাণ কমিয়ে আবার চেষ্টা করুন।" (no count). The quote marks such a line `available: false` as before.
  - Removed every hardcoded 5: `cart_service.MAX_QTY`, `variant_service.PLATFORM_MAX_QTY`, `le=5` in the cart/order/product schemas and the DB CHECKs. The hard ceiling is now `QUANTITY_CEILING = 1000` (`app/schemas/pricing.py`).
  - API: `PublicProductDetail.max_per_order` and the new `PublicVariant.max_quantity` = min(effective limit, stock); cart lines' `max_quantity` the same. So 8 pieces (30 % with the default tiers) can be bought when the limit allows.
  - Migration `0087_order_quantity_limit` (non-destructive): adds the column (server default 10) with a 1–1000 CHECK, widens the product min/max and cart/order line quantity CHECKs from 5 to 1000. Applied to the local dev DB only; products, prices and the row count unchanged.
  - Files: `alembic/versions/0087_order_quantity_limit.py`, `app/models/pricing.py`, `app/models/product.py`, `app/models/cart.py`, `app/models/order.py`, `app/schemas/pricing.py`, `app/schemas/product.py`, `app/schemas/cart.py`, `app/schemas/order.py`, `app/services/pricing_service.py`, `app/services/variant_service.py`, `app/services/cart_service.py`, `app/services/order_service.py`, `app/services/product_service.py`, `tests/test_pricing.py`, `tests/test_variants.py`, `tests/test_product_create_errors.py`, `tests/integration/test_stock.py`, `tests/integration/test_variants.py`.
  - Note: because the exposed maximum is min(limit, stock), a product whose stock is below the limit reveals that stock count through `max_per_order` / `max_quantity`.
  - Frontend (same day): Admin › Discounts field, product form "store-wide / custom" limit, quantity selectors and messages up to the new limit.
- **Dynamic discounts: regular price, base %, quantity tiers, order price snapshot.**
  - One pricing function (`app/services/pricing_service.py`) prices the product page block, cart lines, the quote and the order. The browser never sends a price (`unit_price` in a cart/order body is still a 422).
  - Rule: `total % = min(base % + extra % of the highest tier reached, max %, 99.99 %)`. Unit price = quantity-1 price − round(regular × (total − base) / 100), Decimal, half up, whole taka. So 28 % + 2 % at 8 pieces = 30 %; ৳1,000 → ৳700.
  - Default tiers: 2 → +0.25, 3 → +0.5, 4 → +0.75, 5 → +1, 6 → +1.25, 7 → +1.5, 8+ → +2. Default max 90 %.
  - New table `pricing_settings` (singleton: `tiers_enabled`, `max_discount` in hundredths, `tiers` JSON), seeded with the defaults. `GET` (staff) / `PUT` (editor+) `/api/v1/admin/pricing`, `Cache-Control: no-store`.
  - `products`: `base_discount` (hundredths, NULL = derived from price/compare_at), `tier_mode` (`global`/`custom`), `tiers` (JSON). Admin create/update accept `regular_price`, `base_discount_percent`, `tier_mode`, `tiers`; the API then stores `price` = quantity-1 selling price and `compare_at_price` = regular price (None without a discount). Re-sending the same price/compare_at keeps a saved base %; changing them clears it (derived again).
  - `order_items`: `regular_price`, `base_discount`, `quantity_discount`, `total_discount` snapshot (nullable; older orders stay NULL). Order lines are priced from the locked product row.
  - Responses: `AdminProductRead` + `regular_price`, `base_discount_percent`, `tier_mode`, `tiers`; `PublicProductDetail.pricing`; cart lines + `regular_price`, `base/quantity/total_discount_percent`, `pricing`; quote lines + `regular_price` and the % fields; `OrderRead` items + snapshot fields. Public order lookup unchanged.
  - Migration `0086_dynamic_discounts` (additive; existing prices untouched — verified on the dev DB: same row count, price sums and checksum before/after).
  - Existing tests that buy 2+ pieces now expect the default tier discount (`tests/test_cart.py`, `tests/test_orders.py`, `tests/test_variants.py`); `tests/integration/test_stock.py` follows the new `_claim` signature; `tests/test_catalog_categories.py` ignores the `pricing` block's `min_quantity` when checking that stock is never exposed.
  - Files: `alembic/versions/0086_dynamic_discounts.py`, `app/models/pricing.py`, `app/models/product.py`, `app/models/order.py`, `app/models/__init__.py`, `app/schemas/pricing.py`, `app/schemas/product.py`, `app/schemas/cart.py`, `app/schemas/order.py`, `app/services/pricing_service.py`, `app/services/product_service.py`, `app/services/cart_service.py`, `app/services/order_service.py`, `app/api/v1/endpoints/admin_pricing.py`, `app/api/v1/endpoints/admin_products.py`, `app/api/v1/router.py`, `tests/test_pricing.py` and the tests above.
  - Frontend (same day): admin product form (regular price, base %, live selling price, global/custom tiers), `/admin/pricing` settings page, product page and cart show the total % for the quantity, admin order shows the snapshot.
  - Limitation: one cart line is capped at 5 pieces (`MAX_QTY`), so the 6/7/8+ tiers cannot be reached yet. (Fixed by the max-quantity entry above.)
## 2026-11-02 (summary of today's work)

- **Showcase:** test that a pinned product drops out of `GET /home/showcase` once it is hidden (admin view still lists it). No API change. File: `tests/test_home_showcase.py`.
- **Custom thumbnails for gallery videos and YouTube items.**
  - `GalleryImage.thumbnail` (admin and public gallery items); always empty for photos.
  - New multipart parts on `POST` / `PATCH /admin/products`: `thumbnails` (image files, same checks as gallery photos: JPEG/PNG/WEBP/GIF, 5 MB) and `thumbnail_targets` (JSON list, one per file: a gallery item id, or `video:<n>` for the n-th video uploaded in the same request).
  - A replaced or removed thumbnail file is deleted from disk (it is one of the product's owned media refs); thumbnails are also deleted with the product.
  - Error "Thumbnail does not match a video" (create: Bengali `{errors}` on field `images`).
  - Files: `app/schemas/product.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_product_media.py`.
  - Frontend: admin gallery "Add / Change / Remove thumbnail" and the storefront poster with a play button (frontend repo, same day).
- **Docs**: added `docs/AI_INSTRUCTIONS.md`, `PROJECT_OVERVIEW.md`, `BUSINESS_LOGIC.md`, `API.md`, `CHANGELOG.md`, `TODO.md`; added root `AGENTS.md`; README now points to `docs/AI_INSTRUCTIONS.md`.
- **Bulk product delete** (`8d3800c`): `DELETE /api/v1/admin/products/bulk` with `{"ids": [...]}`, editor+, max 100, partial success with `deleted` / `skipped` / `failed`. Files: `app/schemas/product.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_product_bulk_delete.py`.
  - Frontend: `/admin/products` row checkboxes, select-all and "Delete selected" use this endpoint (frontend commit `d724296`).
- **Gallery videos and YouTube** (`0728d82`): MP4/WEBM upload up to 50 MB, YouTube links stored as ids.
- **Drafts** (`f7f964c`): products save as drafts with only a name; publishing needs price, category and main image.
- **Frontend-only fix, no API change**: the Image/Video options in the admin Gallery "+ Add" menu did not open the file picker, and YouTube items were dropped on save (frontend commit `179fea3`).

# History from git log

## 2026-11-02

- Add admin bulk product delete endpoint (`8d3800c`)
- feat(products): gallery videos (MP4/WEBM upload, 50 MB) and YouTube links (`0728d82`)
- feat(products): save products as drafts with only a name (`f7f964c`)

## 2026-11-01

- feat(products): field-level Bengali errors on admin product create (`ebb1fdc`)
- feat(badges): admin-managed custom product badges (`1862f58`)

## 2026-10-27

- Blog posts: name every invalid field in 422/409 errors (`b1461ca`)
- feat(contact): central dynamic site contact settings (`fbe177c`)

## 2026-10-26

- feat(site): admin-managed storefront header menu (`43f84c9`)
- test(catalog): cover inline category creation then product assignment (`6027726`)
- fix(qa): script-scheme guard for admin href fields, FK indexes (migration 0081), hardening tests (`9d44102`)
- feat(footer): admin-managed site footer config (migration 0080, public + admin API, tests) (`b3cb29e`)
- feat(home): content-managed promo banner API, upload and migration 0079 (`1e4eadb`)
- feat(blogs): validated cover upload, cover/SEO fields, legacy-safe reads, migration 0078 (`411af2b`)
- feat(search): global search API, catalog q filter and trigram index migration 0077 (`f88ca31`)

## 2026-10-25

- feat(api): public order items expose product_id; tests for id-based product addressing (`8f26f1f`)
- test(catalog): type annotations for variant tests (no new mypy errors) (`2effdeb`)
- docs: fix README table gap (`142a0cd`)
- docs: place the variants note after the endpoint table (`6f77fd2`)
- docs: keep the README endpoint table intact (`c17745a`)
- test(catalog): variant unit and PostgreSQL integration tests; docs for variant_id (`6579150`)
- feat(catalog): product variants with per-variant price and stock (`a88b321`)
- test(catalog): category tree, visibility, deletion, product assignment and legacy-compat tests (`d26919f`)
- feat(catalog): attach cycle trigger to the model and add Postgres integration tests for tree, FKs and stock races (`c3d47b1`)
- fix(stock): stock refusals use a generic message that never names the remaining count (`6b3d822`)
- fix(catalog): migration 0075 uses convention-aware check names and legacy tile labels (`facfb26`)
- feat(catalog): public category tree and admin category endpoints (`b9419da`)
- feat(catalog): category-aware product schemas, services and legacy adapters (`6dd30ac`)
- feat(catalog): add categories table, products.category_id and migration 0075 (`33f10df`)

## 2026-10-17

- feat(categories): nest home categories with validated parent links (`88dfbcb`)
- fix(deploy): persist uploaded media on a named volume in production compose (`b122430`)
- feat(inquiries): store storefront inquiries with admin API (`8790670`)

## 2026-10-15

- chore(bruno): send single optional image in sustainability requests (`1ae60d0`)
- test(sustainability): cover optional single image for every section (`df73f15`)
- feat(sustainability): make section photos optional and single with legacy-compatible API (`64dfc59`)
- test(about): cover single-image write, validation and upload (`593b20b`)
- feat(db): migration 0071 archives extra about images, keeps first (`5c6b503`)
- feat(about): single image for hero, story and dress sections (`66e3576`)

## 2026-10-14

- QA remediation phase 1+2 (backend.patch) (`4b8e2ee`)

## 2026-10-07

- Keep new products hidden and public order lookup free of a delivery address. (`1bf0f36`)

## 2026-10-06

- Point the public Mart API at the VPS hostname. (`17cd1af`)
- Dial the VPS by hostname so Cloudflare can reach the Mart API. (`dacc033`)
- Point the mart API hostname at the VPS instead of Render. (`3a9891f`)
- Skip TLS for private database hostnames. (`77e6516`)

## 2026-10-05

- Point the Production Bruno environment at the mart API. (`5238d4a`)

## 2026-10-04

- Give the API user a writable media directory so production can boot. (`41a9fc1`)
- more professional, modern, performance improve and security improve done (`4b16f24`)
- Pin Python dependencies in uv.lock so image builds stay reproducible. (`30b45be`)
- Add FAQ, shipping, and privacy page CMS APIs. (`d7dfb08`)
- more api created done (`ba26a0f`)

## 2026-10-03

- more modified (`8c7b454`)
- about page more api create done (`dbaee1c`)
- home page all section api create and integration done (`66efb66`)
- home page all section all api create done (`620cfad`)
- dashboad overview api created done (`d1b424d`)
- quantity, color added (`0df573c`)
- delivary status change (`62cdd47`)
- modified (`3fd1690`)
- Allow the mart storefront origin in production CORS. (`cb0fed1`)
- order system api modified (`29d6035`)
- order system complete (`f4eaedf`)

## 2026-10-02

- cart api crate done (`d9c318f`)
- products api created done (`74e6055`)

## 2026-09-28

- bruno file updated (`90604f4`)
- bruno file updated (`0df58a3`)
- project setup (`085d465`)
