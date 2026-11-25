# Daily Handoff & Cross-Device Sync — 2026-11-25

> **Purpose:** Single source of truth for resuming work seamlessly between **Home Laptop** and **Office PC** via Git without copying local AI chat databases.
> **Language Preference (Tushar):** Communicate with Tushar in **Bengali (বাংলা)** in chat sessions. Storefront & Customer Dashboard UI text is in **English**.
> **Core Scale Mandate (ALWAYS KEEP IN MIND):**
> - Target scale: **10,000+ active visitors/users** and **1,000+ sellers/dropshippers**.
> - Every schema, SQL query, index, cache, and WebSocket worker must be designed for high concurrency (zero N+1 queries, composite indexes, Redis Pub/Sub across multi-worker Gunicorn/Uvicorn, strict RBAC isolation).

---

## 1. Completed Backend Work — 2026-11-25 (Phases 23–24, Local Verified, Pending Production Deploy)

### Phase 23 — Hardened Steadfast Merchant API Client & Courier Operations (Migration `0112`)
- **Additive Migration `0112_steadfast_courier_integration.py` (Single Alembic head `0112`, `down_revision = "0111"`):**
  - Created `courier_shipments` (partial unique index on non-null `consignment_id`, `cod_amount >= 0`, `tracking_events` & `raw_payload` JSONB/JSON), `courier_webhook_events` (`event_key` unique), and `courier_locations` (unique `(provider, district, police_station)`), and widened `order_activities.action` CHECK (`courier_booked`, `courier_webhook`, `return_requested`).
- **Hardened `SteadfastClient` (`app/services/courier/steadfast_client.py`):**
  - Input sanitizer (`{};<>$` → spaces) & exact Steadfast length caps, Redis-backed 3-strike 10-minute `401` circuit breaker (never retries 401), 60s Redis caches, per-item HTTP 200 payload inspection for bulk booking, and upgraded `SteadfastProvider` (`/fraud_check/score/{phone}` with 404 fallback).
- **Courier Operations & Public Locations (`admin_courier.py`, `steadfast_service.py`, `delivery.py`):**
  - Mounted `/api/v1/admin/courier/steadfast/*` (`ping`, `orders/{id}/book`, `orders/bulk-book`, `orders/{id}/refresh-status`, `orders/{id}/tracking`, `pickup-request`, `return-requests`, `overview`, `sync-locations`) + public cached `GET /api/v1/delivery/locations`.

### Phase 24 — Webhook Automation, Superadmin COD Reconciliation & Customer Live Tracking
- **Webhook Receiver (`app/api/v1/endpoints/webhooks.py`, `steadfast_webhook_service.py`):**
  - `POST /api/v1/webhooks/steadfast` with constant-time `STEADFAST_WEBHOOK_SECRET` auth (fails closed when unset) and deterministic `courier_webhook_events` idempotency.
  - Strict accounting rules: never finalizes on `*_approval_pending`; auto-transitions confirmed `delivered` orders (setting `delivered_at` + customer notification + WS + Web Push); flags `partial_delivered` without overwriting totals; sets `is_return_received=True` ONLY on `cancelled_return_received` or `partial_delivered_return_received`; alerts + optional Telegram on `hold`/`exceptional`.
- **Superadmin-Only Finance & COD Reconciliation (`steadfast_finance_service.py`, `admin_courier.py`):**
  - Strictly `RequireSuperadmin` (`403` for editors/viewers): `GET /balance`, `GET /payments` (paginated), `GET /payments/{id}` (zero-N+1 parcel cross-match), `POST /payments/{id}/reconcile` (atomic, idempotent COD settlement + `COURIER_COD_RECONCILED` audit event).
- **Live Customer & Public Tracking (`tracking_presenter.py`, `customer_purchased_service.py`, `order_service.py`):**
  - Enriched `GET /api/v1/customer/orders/{number}/tracking` and `POST /api/v1/orders/lookup` with `tracking_url` and sanitized `live_events` (60s cached on demand; never leaks `*_approval_pending`, `fraud_score`, `merchant_reports`, or internal notes).

### Already Live in Production (Migrations `0093`–`0111`)
- Inventory (`0093`), Reports (`0094`), Coupons (`0096`), Orders Desk (`0097`–`0098`), SEO (`0099`), Customer Auth/Reviews/Notifications (`0102`–`0104`), SaaS Accounting & Safe Delete (`0105`), Dynamic RBAC (`0106`–`0108`), Customer Phone Report (`0109`), Real-Time WS + Redis Pub/Sub & Communication Engine (`0110`), and Web Push (`0111`).

---

## 2. Steadfast Production Rollout Checklist (VPS `72.60.199.155` — Pending Explicit Approval)
1. **VPS `.env.production`:** Set `STEADFAST_API_KEY`, `STEADFAST_SECRET_KEY`, `STEADFAST_WEBHOOK_SECRET`, and `COURIER_CHECK_ENABLED=true` (plus optional `STEADFAST_PICKUP_ADDRESS` / `STEADFAST_PICKUP_PHONE`).
2. **Steadfast Merchant Portal:** Register `https://mart-api.implesia.com/api/v1/webhooks/steadfast` with the matching Bearer secret.
3. **Backup & Migrate:** Take full `pg_dump` backup → pull `main` → run `alembic upgrade head` (applies **`0112`**, single head).
4. **Rebuild Backend:** `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
5. **Deploy Frontend:** `npm run deploy:vinext` (Cloudflare Workers).
6. **Live Smoke Test:** Run **"Sync Delivery Thanas"** on `/admin/orders/courier` → test `GET /api/v1/admin/courier/steadfast/ping` → book 1 real test parcel → verify webhook delivery, customer tracking, and superadmin balance/payouts.

---

## 3. Next Milestone Backlog
- **SaaS Dropshipping / Seller Portal (Milestone 2/3):** Seller registration & KYC → Admin approval → Seller Portal (catalog sync, orders, commissions, payouts, seller live chat).
- **SSL Wireless SMS Credentials:** Add provider adapter + production credentials when ready.
