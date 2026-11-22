# Work Report — 2026-11-22 (Phases 18–21: Real-Time WebSocket, Redis Pub/Sub & Direct Communication Engine)

**Git Branch (Both Repos):** `feat/phases-18-21-realtime-communication`
**Alembic Single Head:** `0108` (`alembic/versions/0108_communication_system.py`)

---

## 1. Completed Work Today (2026-11-22)

### Pre-flight Local Office PC Sync
- Repaired stale `.venv/bin/*` shebangs after workspace folder move and verified Python 3.12, `alembic`, `pytest`, `ruff`, and `mypy`.
- Started local Docker PostgreSQL (`localhost:5434`) & Redis 7 (`localhost:6381`) and upgraded local DB through `0107` and then `0108 (head)`.

### Backend (`implesia-mart-backend`) — Phases 18 & 19 + DevOps Hardening
1. **Phase 18 — Monolith Concurrency Hardening & Real-Time WebSocket + Redis Pub/Sub Foundation:**
   - **Database Pool Hardening** (`app/core/config.py`, `app/db/session.py`, `.env.example`): Replaced hardcoded `pool_size=2` with configurable `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=10`, `DB_POOL_TIMEOUT=15`, `DB_POOL_RECYCLE=1800`, plus `pool_pre_ping=True`.
   - **Resilient Async Redis Client & Pub/Sub Hub** (`app/services/redis_client.py`, `app/services/realtime_hub.py`, `app/main.py`): Bounded async pool (`max_connections=50`), socket timeouts, transparent in-process fallback when Redis is unavailable or `memory://`, single worker Pub/Sub loop on `rt:*` (`rt:user:{id}`, `rt:staff:orders`, `rt:staff:communication`, `rt:conv:{id}`), 30s single-use `GETDEL` WS tickets, 60s TTL presence keys, and sliding-window WS rate limits (`20 events / 10s`).
   - **Hardened WebSocket Manager & Endpoints** (`app/services/ws_manager.py`, `app/api/v1/endpoints/ws.py`, `auth.py`, `customer_auth.py`, `schemas/auth.py`, `router.py`):
     - `POST /api/v1/auth/ws-ticket` (staff with dynamic RBAC channel scoping) & `POST /api/v1/customer/ws-ticket`.
     - `WS /api/v1/ws?ticket=...` with **ZERO PostgreSQL session held inside the WS loop**, max 5 concurrent sockets/user (`4008`), 4 KB max frame (`1009`), 60s idle timeout (`4000`), `ping`/`pong`, ephemeral `typing` relay, and `subscribe_conversation`.
   - **Real-Time Event Push** (`order_service.py`, `notification_service.py`): Publishes `order.new` on committed online orders and `notification.created` / `notification.unread` on customer notification updates.
2. **Phase 19 — High-Scale, Seller-Ready Direct Communication Engine:**
   - **Additive Migration `0108_communication_system.py`** (`revision="0108"`, `down_revision="0107"`) & Models (`app/models/communication.py`, `app/models/__init__.py`):
     - `conversations` (`customer_support`, `seller_support`, `customer_seller`; status `open`/`pending`/`resolved`/`closed`; `customer_id`, `seller_id`, `order_id`, `product_id`, `assigned_staff_id`; high-scale composite DESC indexes).
     - `messages` (composite keyset index `(conversation_id, created_at DESC, id DESC)`, `is_internal_note`).
     - `conversation_read_states` (composite PK `(conversation_id, user_id)`).
     - Idempotently seeds `role_permissions` for `communication` (`editor=read_write`, `viewer=read_only`).
   - **Dynamic RBAC** (`app/services/permission_service.py`): Registered `communication` (`Communication & Live Chat`) in `MODULE_DEFINITIONS` (`superadmin=full`, `editor=read_write`, `viewer=read_only`, assignable to custom staff roles).
   - **Communication Service & Endpoints** (`app/services/communication_service.py`, `app/schemas/communication.py`, `customer_communication.py`, `admin_communication.py`, `image_storage.py`):
     - Customer endpoints: `GET/POST /api/v1/customer/conversations`, `GET/POST /{id}/messages`, `POST /{id}/attachment`, `POST /{id}/read`.
     - Admin endpoints (`require_module_access("communication", ...)`): `GET /summary`, `GET /conversations`, `GET /{id}` (customer profile + recent orders context), `GET/POST /{id}/messages`, `POST /{id}/attachment`, `PATCH /{id}`, `POST /{id}/read`.
     - Strict participant isolation, internal note privacy (never exposed in customer REST, preview, unread count, or customer WS frames), O(1) cursor pagination, single-query aggregated unread counts (zero N+1), `20 msgs / 10s` Redis send rate limit, `/media/chat/` image uploads, and 5-minute throttled offline `CustomerNotification`.
3. **Production DevOps Audit (`docker-compose.prod.yml`):**
   - Added internal `redis:7-alpine` service (`--appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru`, persistent `implesia-mart-redis-data` volume, healthcheck) and `WEB_CONCURRENCY=3` with `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=10` (`3 × 20 = 60 < 100` PG `max_connections`).
   - Documented Caddy v2 + Cloudflare WebSocket proxy setup and 4-step VPS rollout runbook in `docs/HANDOFF.md` & `docs/TODO.md`.
4. **Backend Verification:**
   - `ruff check .`: All checks passed.
   - `mypy app`: 0 issues in 414 source files.
   - `alembic heads` & `alembic current`: `0108 (head)`.
   - `pytest tests/test_0108_migration.py tests/test_communication.py tests/test_realtime_ws.py -v`: **17 passed**.

### Frontend (`implesia-mart`) — Phases 20 & 21
1. **Phase 20 — Monolith-Friendly Shared WebSocket Client & Instant Notification Upgrade:**
   - **Same-Origin BFF Ticket Routes**: `POST /api/auth/ws-ticket` (`app/api/auth/ws-ticket/route.ts`, `lib/auth/bff.ts`) & `POST /api/customer/ws-ticket` (`app/api/customer/ws-ticket/route.ts`), plus `lib/realtime/ws-url.ts`.
   - **Shared Leader-Tab WS Client** (`lib/realtime/ws-client.ts`, `lib/realtime/use-realtime.ts`): Isolated `"admin"` and `"customer"` scopes, `localStorage` lease + `BroadcastChannel` leader election (1 live socket across 10+ tabs), 25s heartbeat ping, exponential backoff with jitter (`1s → 30s`), automatic re-ticket & conversation re-subscribe, and `connected` / `reconnecting` / `fallback_polling` states.
   - **Instant Notifications**: Upgraded Admin `OrderAlertsProvider` (`order.new` instant chime/toast/notification + 5-min connected reconciliation / 25s-3m fallback) and `CustomerNotificationBell` (`notification.created` & `notification.unread` instant badge/dropdown/chime + 5-min sync / 60s fallback).
2. **Phase 21 — Full Live Communication UI:**
   - **Customer BFF Proxy Routes & Typed Clients**: `app/api/customer/conversations/**`, `lib/mart-api/communication.ts`, `lib/mart-api/admin-communication.ts`.
   - **Customer Live Support**: 2-pane responsive `/dashboard/messages` page (`Start New Support Chat` modal with optional Order selector, live WS streaming, cursor `Load older messages`, typing indicator, image attachments, status badges), live unread badge in Customer Dashboard sidebar (`Support Chat`), and floating storefront `SupportChatWidget` (hidden on `/admin`, `/checkout`, and `/dashboard/messages`).
   - **Admin Communication Center (`/admin/communication`)**: Dynamic RBAC guard (`useAdminPermissions("communication")`), sidebar `CommunicationBadge`, and 3-pane SaaS Inbox (`ConversationListPane`, `MessageThreadPane` with Public Reply vs amber-lock Internal Staff Note switcher, and collapsible `ContextPane` with customer profile, linked order/product, recent orders, staff assignment, and status control). Automatically surfaces `Communication & Live Chat` in `/admin/rbac/roles`.
3. **Frontend Verification:**
   - `npm test`: **399 passed, 0 failed** (`tests/realtime-ws-client.test.ts`, `tests/communication-ui.test.ts` + full suite).
   - `npm run lint`: **0 errors**.
   - `npm run typecheck`: **0 errors**.
   - `npm run build`: **Next.js 16.2.4 production build passed**.

---

## 2. How to Pull & Resume on Home Laptop

Run these commands on your Home Laptop to get all of today's changes in both repos:

```bash
# 1. Backend
cd /path/to/implesia-mart-backend
git fetch origin
git checkout -B feat/phases-18-21-realtime-communication origin/feat/phases-18-21-realtime-communication
# Make sure local Postgres & Redis are running, then apply migration 0108:
alembic upgrade head
alembic current   # should print: 0108 (head)

# 2. Frontend
cd /path/to/implesia-mart
git fetch origin
git checkout -B feat/phases-18-21-realtime-communication origin/feat/phases-18-21-realtime-communication
npm install
npm test
```

---

## 3. Remaining / Next Steps
- [ ] Review & merge `feat/phases-18-21-realtime-communication` into `main` in both repos when ready.
- [ ] Run production rollout on VPS `72.60.199.155` (`pg_dump` → `alembic upgrade head` through `0108` → rebuild API + Redis 7 → deploy Cloudflare Workers frontend → live smoke test).
- [ ] Start **Milestone 2/3: SaaS Dropshipping / Seller Portal** (seller application/approval, seller catalog & fulfillment, activating `seller_support` and `customer_seller` channels).
