# TODO

Open items found in the code and in recent work. Remove an item when it is done.

## Done (Pending Production Deployment — Phases 23–24 / Migration `0112`)

- **Phase 23 — Hardened Steadfast Merchant API Client & Courier Operations (2026-11-25):**
  - **Alembic Migration `0112_steadfast_courier_integration.py` (single head `0112`, `down_revision="0111"`):** Additive tables `courier_shipments` (partial unique index on non-null `consignment_id`), `courier_webhook_events` (`event_key` unique idempotency), and `courier_locations` (`(provider, district, police_station)` unique), plus widened `order_activities.action` CHECK (`courier_booked`, `courier_webhook`, `return_requested`).
  - Hardened async `SteadfastClient` (`app/services/courier/steadfast_client.py`) with `{};<>$` sanitizer & field truncation, Redis-backed 3-strike 10-minute `401` circuit breaker (never retries 401), 60s Redis caches, per-item HTTP 200 bulk error inspection, and upgraded `SteadfastProvider` (`/fraud_check/score/{phone}` with 404 fallback).
  - Mounted `/api/v1/admin/courier/steadfast/*` (`ping`, `book`, `bulk-book`, `refresh-status`, `tracking`, `pickup-request`, `return-requests`, `overview`, `sync-locations`) + public cached `GET /api/v1/delivery/locations`.
- **Phase 24 — Steadfast Webhook Automation, Superadmin COD Reconciliation & Customer Live Tracking (2026-11-25):**
  - Mounted `POST /api/v1/webhooks/steadfast` (`STEADFAST_WEBHOOK_SECRET` constant-time auth, fail closed if empty, idempotent `courier_webhook_events`).
  - Strict accounting rules: never finalizes orders/accounting on `*_approval_pending`; auto-transitions confirmed `delivered` orders with customer notifications + WS + Web Push; flags `partial_delivered` without overwriting totals; sets `is_return_received=True` ONLY on `cancelled_return_received` or `partial_delivered_return_received`; alerts + optional Telegram on `hold`/`exceptional`.
  - Superadmin-only (`RequireSuperadmin`) finance & idempotent COD reconciliation endpoints (`/balance`, `/payments`, `/payments/{id}`, `/payments/{id}/reconcile`).
  - Wired sanitized customer-friendly `live_events` & `tracking_url` into `GET /api/v1/customer/orders/{number}/tracking` and `POST /api/v1/orders/lookup`.

## Live in Production (Deployed Migrations `0093`–`0111`)

- Inventory ledger & opening stock (`0093`), sales reports (`0094`), coupons (`0096`), orders desk (`0097`), order print/tracking (`0098`), storefront SEO (`0099`), customer auth/notifications/reviews (`0102`–`0104`), SaaS accounting & superadmin safe deletion (`0105`), dynamic RBAC (`0106`–`0108`), customer phone report & courier check cache (`0109`), real-time WebSocket + Redis Pub/Sub & Direct Communication Engine (`0110`), Web Push notifications (`0111`), Meta CAPI match quality, and Turnstile checkout verification.

## Open / Pending Next Steps

- **Deploy Steadfast Integration (`0112`) to Production (VPS `72.60.199.155`):**
  1. Set `STEADFAST_API_KEY`, `STEADFAST_SECRET_KEY`, `STEADFAST_WEBHOOK_SECRET`, and `COURIER_CHECK_ENABLED=true` in `.env.production` (plus optional `STEADFAST_PICKUP_ADDRESS`, `STEADFAST_PICKUP_PHONE`).
  2. Register `https://mart-api.implesia.com/api/v1/webhooks/steadfast` in Steadfast Merchant Portal with the matching Bearer secret.
  3. Take `pg_dump` backup → pull `main` → `alembic upgrade head` (`0112`, single head) → `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
  4. Deploy frontend (`npm run deploy:vinext`) → run **"Sync Delivery Thanas"** + test `GET /api/v1/admin/courier/steadfast/ping` + book 1 real test parcel.
- **Customer SMS Notifications via SSL Wireless:**
  - Add SSL Wireless provider adapter and connect `SMS_SSLWIRELESS_API_TOKEN` / `SMS_SSLWIRELESS_SID` in `.env.production` once account is active.
- **PATCH product errors:** Bring `PATCH /api/v1/admin/products/{id}` 422 errors in line with `POST`'s Bengali `{"errors": [{"field","message","fix"}]}` contract.
- **Upload size behind production proxy:** Confirm Caddy / Cloudflare limit accepts full 100 MB video gallery saves.
- **Gallery order after save:** New uploads currently append after existing items.
- **Bulk delete and orders / Max quantity low-stock exposure / Slug race / Bengali transliteration / Home media orphan sweep:** Tracked minor backlog items for future hardening.

## Code comments

- No `TODO` / `FIXME` comments in `app/`, `tests/` or `scripts/`.
