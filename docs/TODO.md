# TODO

Open items found in the code and in recent work. Remove an item when it is done.

## Done (not live / pending production deployment)

- **Dynamic RBAC test fix (2026-11-24).** Migration `0108` seeds missing `roles` rows without rewriting users. Built-in viewer `read_only` is 403 again on dashboard, admin products, inquiries, CMS, carts, and the order list. `GET /admin/orders/new` stays open.

- **Customer Authentication, Notifications & Product Reviews (2026-11-21).**
  - **Alembic Migration 0102:** Added `customer` role to `UserRole` enum, added `phone` (with index and partial unique constraint), `district`, `area`, `address` to `User` model.
  - **Alembic Migration 0103:** Added `avatar_url` (varchar 500) to `User` model; created `customer_notifications` table (with cascade delete, user index, unread index); created `product_reviews` table (rating 1-5, headline, comment, purchase verification, published index).
  - **Alembic Migration 0104:** Added FK indexes `ix_customer_notifications_order_id` and `ix_product_reviews_order_id` so every foreign key column leads an index.
- **Phase C Admin-Only Safe Deletion & Reconciliation (2026-11-21).**
  - Enforced `RequireSuperadmin` on delete and delete-impact endpoints for Orders, Badges, and Suppliers (`GET .../delete-impact` + `DELETE ...`).
  - Order deletion atomically reconciles held stock with offsetting `stock_movements` `adjustment` rows (`sum(movements) == on_hand`), releases coupon redemptions, preserves reviews/notifications/ledger rows with `order_id=NULL`, and writes a complete `ORDER_DELETED` audit snapshot.
  - Badge deletion supports `unlink` and `merge` (deduplicating links & recomputing `products.badge`, protecting `is_system` badges with 409). Supplier deletion supports `merge` (preserving all purchase/COGS history), `archive`, and guarded `hard_delete` (`purchases_count == 0`).
  - Covered by `tests/test_phase_c_safe_delete.py`.
- **Phase B SaaS Reporting APIs & Product Analytics (2026-11-21).**
  - Expanded presets (`today`, `7d`, `this_week`, `this_month`, `last_month`, `this_year`) and filters (`supplier_id`, `origin`, `profit_filter`, product `sort`) across admin reports.
  - Added `GET /api/v1/admin/reports/profit-loss`, `/channels`, `/suppliers` (each with `/export` `.xlsx`), upgraded `/profit`, `/products`, and `/stock` with full SaaS valuation/margin/loss metrics, and added `GET /api/v1/admin/products/{product_id}/analytics`.
  - Covered by `tests/test_reports_saas.py` (all SQL aggregates, dual SQLite/PostgreSQL compatible).
- **Phase A Backend Schema & Accounting Fixes (2026-11-21).**
  - **Alembic Migration 0105:** Added nullable `products.supplier_id` (FK `suppliers.id ON DELETE SET NULL`, indexed), nullable `product_variants.cost_price` (`Numeric(12, 2)`, non-negative check), and widened `order_activities.action` to include `payment_updated`.
  - Admin product supplier assignment/filter + per-variant `cost_price` (weighted average updated in `create_purchase`, snapshotted to `OrderItem.unit_cost`).
  - Offline order `initial_status`/`mark_delivered` with business-date `delivered_at` alignment, automatic customer `user_id` linking by phone, and payment collection (`POST /api/v1/admin/orders/{id}/payments` + `PATCH` `paid_amount`).
  - Returned orders excluded from realized sales/profit/product/trend calculations; `SalesSummary.manual_discount`, `DeliveryReport.returned_value`, and `ProductReportRow.return_value` exposed.
  - **Customer Auth & Profile Service:** BD phone normalization (`01XXXXXXXXX`), password hashing, JWT access/refresh token rotation, session invalidation on logout.
  - **Endpoints:**
    - `POST /api/v1/customer/auth/register`, `login`, `refresh`, `logout`.
    - `GET` & `PATCH /api/v1/customer/profile` (clean clearing of optional fields via `null`/`""`).
    - `POST /api/v1/customer/change-password`.
    - `POST` & `DELETE /api/v1/customer/profile/avatar` (profile photo upload and removal with owned media cleanup).
    - `POST /api/v1/customer/cart/merge` (merge guest cart into customer account on login).
    - `GET /api/v1/customer/orders` & `GET /api/v1/customer/orders/{number}/tracking` (activity-sourced timestamps, clean `cancelled`/`returned` handling, future-ready `tracking_url` & `live_events`).
    - `GET /api/v1/customer/purchased-products` (full repeat-purchase line history with quantities, totals, order status, and payment breakdown).
    - `GET /api/v1/customer/dashboard-summary` (includes `delivered_orders`, `cancelled_orders`, `total_products_purchased`, `unread_notifications`).
    - `GET /api/v1/customer/notifications`, `PATCH /api/v1/customer/notifications/{id}/read`, `POST /api/v1/customer/notifications/mark-all-read`, `DELETE /api/v1/customer/notifications/{id}` (with automatic 30-day physical purge).
    - `GET /api/v1/products/{id}/reviews`, `GET /api/v1/products/{id}/can-review`, `POST /api/v1/products/{id}/reviews`.
  - **Automated Order Notifications:**
    - Triggered automatically on new online order creation (logged-in or phone-matched customers), admin single-order status updates, and admin bulk-status updates.
  - **Test Suite:** Comprehensive automated tests in `tests/test_customer_auth.py` and `tests/test_customer_phase6.py` covering all flows and Phase 6 upgrades.

## Open / Pending Next Steps

- **Deploy to Production (VPS 72.60.199.155):**
  - Run `alembic upgrade head` to apply migrations through `0105` (including `0102`–`0105`) on the production database.
  - Rebuild API container: `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
- **Customer SMS Notifications via SSL Wireless:**
  - Connect real SMS credentials (`SMS_SSLWIRELESS_API_TOKEN`, `SMS_SSLWIRELESS_SID`) in `.env.production` once account is active.
- **Frontend Product Reviews UI & Header Notifications Drawer (2026-11-21):** Done in `implesia-mart` (Phases 8–10).

- **Storefront SEO settings are done, not live**: migration 0099 creates `site_settings` with three nullable columns and does not seed a row. It sits on 0098 from the orders desk branch. Do not run it against production from a laptop, and do not run it ahead of 0097 and 0098. Empty fields stay null so the storefront keeps its built-in title, description, and title template until an editor saves them.
- **Order print, tracking, and customer SMS are done, not live**: migration 0098 adds two nullable claim timestamps, a tracking index, and the `customer_message` activity value. It does not rewrite totals or statuses. Do not run it against production from a laptop. Estimated delivery is computed on print, not stored. Public lookup is still `POST /api/v1/orders/lookup`. Customer texts are not delivered. `CUSTOMER_SMS_ENABLED` stays false. `CUSTOMER_SMS_PROVIDER` is `log` or `noop` only. To send real SMS, open an SSL Wireless ISMS Plus (SMS Plus) account at the panel behind `https://ismsplus.sslwireless.com/api-documentation` and supply `SMS_SSLWIRELESS_API_TOKEN` (their `api_token`) and `SMS_SSLWIRELESS_SID` (their registered sender id). Whitelist the API server's outbound IP in that panel. Their single-SMS URL is `https://smsplus.sslwireless.com/api/v3/send-sms` (`SMS_SSLWIRELESS_API_URL`). Those three names are comments in `.env.example` and the API does not read them. Setting them does nothing until a provider adapter is added. `ADMIN_BASE_URL` must be the storefront origin or the status link is omitted. Offline orders still do not send Meta CAPI, the Telegram new-order or cancel alert, or a GA event. A low-stock Telegram can still fire from the stock claim.
- **Orders desk is done, not live**: migration 0097 adds nullable-or-default columns and `order_activities`. It does not rewrite existing totals or statuses. Do not run the migration against production from a laptop.
- **Coupons are done, not live**: migration 0096 adds the coupon tables and two nullable columns on `orders`. Checkout, the admin coupon API, and the coupon report work on this branch. They are not on production until this branch is merged and `alembic upgrade head` is run. Do not run it against production from a laptop. There is no new environment variable. A coupon is never deleted; turn it off. A return keeps the redemption; a cancellation gives the use back.
- **Telegram alerts are not live**: checkout and the new-order feed work without them. A message is sent only when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` are set on the API host. `TELEGRAM_NOTIFY_ORDER_CANCELLED` and `TELEGRAM_NOTIFY_LOW_STOCK` stay off until set to true. `ADMIN_BASE_URL` is the storefront origin used in the order link. Leave the token and chat ids out of the repo.
- **Meta Purchase events are not live**: the server sends a Conversions API `Purchase` only when `META_PIXEL_ID` and `META_CAPI_TOKEN` are set on the API host. `META_TEST_EVENT_CODE` is for Events Manager test events. Leave the token out of the repo. Until those are set, checkout still works and the order response still includes `analytics_event_id`.
- **Sales reports after migration 0094**: back up the database, merge PR #8 (migration 0092), then PR #9 (migration 0093), then the reports PR, and run `alembic upgrade head`. 0094 only adds nullable columns and indexes. It does not rewrite old orders. Do not run it against production from a laptop. There is no `cancelled_at`: the delivery report counts a cancellation by `updated_at` while the status is `cancelled`, so a later courier or tracking edit moves that day.
- **Opening stock after migration 0093**: back up the database, merge the cost-price PR (#8) first, then this ledger, run `alembic upgrade head`, then run opening stock once (`POST /api/v1/admin/inventory/opening-stock` or `python -m scripts.opening_stock`). Running it twice does not duplicate rows. Do this while orders are quiet; the command locks each product row.
- **PATCH product errors**: `PATCH /api/v1/admin/products/{id}` still returns the default 422 envelope with English messages. Create (`POST`) already returns the Bengali `{"errors": [{"field","message","fix"}]}` contract. Bring update in line and tell the frontend.
- **Browser verification**: the admin bulk-delete UI has passed lint, type check, build and curl checks but has not had a full manual browser walkthrough.
- **Upload size behind the production proxy**: videos are capped at 50 MB each by the API, and the frontend BFF allows request bodies up to 110 MB. Confirm the production reverse proxy / Cloudflare limit accepts a full gallery request of that size.
- **Gallery order after save**: newly uploaded files are appended after existing gallery items, so the order the admin arranged can change after save.
- **Bulk delete and orders**: deleting products that appear in past orders is allowed (order lines keep name and price, lose the product link). Decide whether that should need extra confirmation.

- **Max quantity exposes low stock**: `max_per_order` / `max_quantity` are min(limit, stock), so a stock count below the limit is visible to shoppers. Decide whether that is acceptable or whether to expose only the limit and refuse at cart time.
- **Product cards**: list/card discount badges come from `compare_at_price` (= base %, or the cheapest variant's compare-at); they do not show quantity tiers (by design). For variant products the badge shows the cheapest variant's %, not the largest.
- **Slug race**: slug uniqueness against other products and redirect rows is checked in the service, not by a DB constraint, so two simultaneous saves could collide (the unique index on `products.slug` still blocks two products with the same current slug).
- **Transliteration is approximate**: Bengali schwa deletion is not modelled fully (e.g. "আয়না" → `ayona`). Admins can edit the slug after create; improve the rules if needed.
- **Category `updated_at`** changes only when the category row changes, not when its products change; the storefront sitemap uses it as is.
- **Home media orphans**: a file uploaded through `POST /admin/home/media/image|video` whose save then fails (validation error, closed tab) stays in the bucket or on disk; nothing sweeps unreferenced files in `home-media/` (same as other CMS uploads).
- **R2 copy**: this change does not upload the files already on the VPS volume. Run the copy in `docs/deploy-media-persistence.md`, then the named volume is only a fallback.

## Code comments

- No `TODO` / `FIXME` comments in `app/`, `tests/` or `scripts/` as of 2026-11-02.
