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

## 2. Steadfast Production Rollout Checklist (Slasha VPS — In Progress)
1. **Steadfast Merchant Portal (`https://steadfast.com.bd`) — DONE:** API key `implesia-mart-prod` created and Webhook `https://mart-api.implesia.com/api/v1/webhooks/steadfast` saved with Bearer secret.
2. **Pre-Migration DB Backup — DONE:** PostgreSQL 16 snapshot `db-20261125110141.dmp` (`562.4 KB`) completed with status **Succeeded** in Slasha (`implesia-mart-api` → `Services` → `db` → `Backups`).
3. **GitHub `main` — DONE:** `feat/phases-23-26-steadfast-courier` verified and merged into `main` (`19c8207`).
4. **Slasha Environment Variables (NEXT — Before Deploy):** Restore clean newline formatting for all 33 variables (28 original + `COURIER_CHECK_ENABLED=true`, `STEADFAST_BASE_URL=https://portal.packzy.com/api/v1`, `STEADFAST_API_KEY`, `STEADFAST_SECRET_KEY`, `STEADFAST_WEBHOOK_SECRET`) in `implesia-mart-api` → `Settings` → `Environment Variables` → **Save Changes** (no deploy triggered yet; live app still healthy on `ade799b`).
5. **Deploy Backend (`0112`):** Deploy latest `main` in Slasha `Deployments` (`scripts/start.sh` automatically runs `alembic upgrade head` → `0112`) and verify healthy logs.
6. **Deploy Frontend:** Run `npm run deploy:vinext` from `implesia-mart` (`main`) on Cloudflare Workers.
7. **Live Smoke Test:** Open `https://mart.implesia.com/admin/orders/courier` → verify green `Ping` (`GET /api/v1/admin/courier/steadfast/ping`) → click **"Sync Delivery Thanas"** → book 1 test parcel → verify webhook delivery, customer tracking, and superadmin balance/payouts.

---

## 3. Next Milestone Backlog
- **SaaS Dropshipping / Seller Portal (Milestone 2/3):** Seller registration & KYC → Admin approval → Seller Portal (catalog sync, orders, commissions, payouts, seller live chat).
- **SSL Wireless SMS Credentials:** Add provider adapter + production credentials when ready.
