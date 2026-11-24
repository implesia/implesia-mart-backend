# Daily Handoff & Cross-Device Sync — 2026-11-22

> **Purpose:** Single source of truth for resuming work seamlessly between **Home Laptop** and **Office PC** via Git without copying local AI chat databases.
> **Language Preference (Tushar):** Communicate with Tushar in **Bengali (বাংলা)** in chat sessions. Storefront & Customer Dashboard UI text is in **English**.
> **Core Scale Mandate (ALWAYS KEEP IN MIND):**
> - Target scale: **10,000+ active visitors/users** and **1,000+ sellers/dropshippers**.
> - Every schema, SQL query, index, cache, and WebSocket worker must be designed for high concurrency (zero N+1 queries, composite indexes, Redis Pub/Sub across multi-worker Gunicorn/Uvicorn, strict RBAC isolation).

---

## 1. Completed Backend Work — 2026-11-22 (Phases 11–19, Local Verified, Pending Production Deploy)

### Phases 18 & 19 — Real-Time WebSocket + Redis Pub/Sub & Direct Communication Engine (Migration `0110`)
- **Database Pool Hardening (`app/core/config.py`, `app/db/session.py`, `docker-compose.prod.yml`):**
  - Configurable `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=10`, `DB_POOL_TIMEOUT=15`, `DB_POOL_RECYCLE=1800` + `pool_pre_ping=True`.
  - Upgraded `docker-compose.prod.yml` with internal **Redis 7** (`redis:7-alpine`, AOF + `256mb` `allkeys-lru`), `REDIS_URL=redis://redis:6379/0`, and `WEB_CONCURRENCY=3` → `3 × (10 + 10) = 60` max DB connections (< PostgreSQL default `max_connections = 100`).
- **Real-Time WebSocket & Redis Pub/Sub Foundation (`app/services/redis_client.py`, `realtime_hub.py`, `ws_manager.py`, `app/api/v1/endpoints/ws.py`):**
  - Single worker Pub/Sub subscriber loop on `rt:*` (`rt:user:{id}`, `rt:staff:orders`, `rt:staff:communication`, `rt:conv:{id}`) with transparent in-process fallback when Redis is unreachable or `memory://`.
  - Single-use 30s WS auth tickets (`POST /api/v1/auth/ws-ticket`, `POST /api/v1/customer/ws-ticket`, consumed via atomic `GETDEL`), 60s TTL Redis presence (`presence:user:{id}`), sliding-window WS rate limit (`20 events / 10s`), max 5 concurrent sockets/user (`4008`), 4 KB frame cap (`1009`), 60s idle timeout (`4000`), **ZERO PostgreSQL session held in the WS loop**.
  - Live event pushes wired into `order_service.py` (`order.new`) and `notification_service.py` (`notification.created`, `notification.unread`).
- **Seller-Ready Direct Communication Engine (Migration `0110_communication_system.py`, `app/models/communication.py`, `app/services/communication_service.py`, `customer_communication.py`, `admin_communication.py`):**
  - The 2026-11-22 handoff planned these tables as **Next Migration `0108`**. That number is now the role seed (`0108_seed_missing_roles.py`). `0109` is `courier_check_results`. The communication schema is migration `0110` (`revision = "0110"`, `down_revision = "0109"`), the single Alembic head.
  - Additive migration creating `conversations` (`customer_support`, `seller_support`, `customer_seller`; composite DESC scale indexes), `messages` (composite keyset index `(conversation_id, created_at DESC, id DESC)`), and `conversation_read_states`, plus seeding `communication` RBAC defaults (`editor=read_write`, `viewer=read_only`). Constraint names use `op.f()`.
  - Dynamic RBAC module `communication` registered in `permission_service.py` (`superadmin=full`, grantable to custom roles).
  - Strict customer isolation, internal staff note privacy (REST + `last_message_preview` + WS scope filtering), O(1) cursor pagination, single-query aggregated unread counts (zero N+1), `20 msgs / 10s` Redis send rate limit, `/media/chat/` image uploads, and 5-minute throttled offline `CustomerNotification`.
  - Chain: `0107` → `0108` role seed → `0109` courier cache → `0110` communication. Covered by `tests/test_0110_migration.py`, `tests/test_communication.py`, and `tests/test_realtime_ws.py`.

### Phases 11–17 — Security, Dynamic RBAC (`0106`, `0107`), Reviews & Notifications
- Blocked non-staff login on `/api/v1/auth/login` & `/refresh`; 30s refresh rotation grace window in `refresh_token_service.py`.
- Dynamic role permissions (`0106_dynamic_role_permissions.py`) + dynamic custom roles CRUD & safe delete (`0107_dynamic_roles.py`).
- Admin reviews (`admin_reviews.py`), admin notifications (`admin_notifications.py`), single customer notification detail + read/unread toggle, and purchase picker thumbnails.

*(Companion Frontend `implesia-mart`: Phases 11–17 + Phases 20–21 complete and verified with 399 passing tests, 0 lint/type errors, and clean Next.js production build.)*

---

## 2. Production Deployment & WebSocket Proxy Checklist (VPS `72.60.199.155`)

- **Alembic Head:** `0110` on this branch (single head: `0107` → `0108` role seed → `0109` courier cache → `0110` communication). Not merged to `testing` or `main`. Do not run it against production from a laptop.
- **Caddy v2 (`/etc/caddy/Caddyfile`):**
  - Caddy v2 supports WebSocket upgrades natively on `reverse_proxy 127.0.0.1:8000` (HTTP/1.1 upstream, no idle read timeout).
  - Ensure `mart-api.implesia.com` forwards `CF-Connecting-IP` / `X-Forwarded-For` and `.env.production` includes `TRUSTED_PROXIES=127.0.0.1,172.16.0.0/12`.
- **Cloudflare Proxy:**
  - Verify **Network → WebSockets = ON** for `implesia.com` (25s client ping keeps sockets well below Cloudflare's ~100s idle timeout).
  - Verify `CORS_ORIGINS` includes `https://mart.implesia.com` and frontend `NEXT_PUBLIC_MART_API_URL=https://mart-api.implesia.com`.
- **Rollout Sequence (run only with explicit approval):**
  1. `pg_dump` full compressed backup on VPS `72.60.199.155`.
  2. After this branch is merged, `alembic upgrade head` applies through `0110`. Do not run that against production until a backup and an explicit approval. Then `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
  3. Deploy frontend: `npm run deploy:vinext`.
  4. Live smoke test: WS handshake, instant admin/customer notifications, live Customer↔Admin chat + internal note privacy, dynamic RBAC roles, reports, and invoice QR.

---

## 3. Home Laptop Resume Commands (Branch `feat/phases-18-21-realtime-communication`)
```bash
git -C implesia-mart-backend fetch origin
git -C implesia-mart-backend checkout -B feat/phases-18-21-realtime-communication origin/feat/phases-18-21-realtime-communication
cd implesia-mart-backend && alembic upgrade head
```
See full daily details in `docs/WORK_REPORT_2026-11-22.md`.

## 4. Next Milestone Backlog
- **SaaS Dropshipping / Seller Portal (Milestone 2/3):** Seller registration & KYC application → Admin approval → Seller Portal (catalog sync, order fulfillment, commissions, payouts, and activating `seller_support` / `customer_seller` threads already supported by Migration `0110`).
- **SSL Wireless SMS Credentials:** Supply `SMS_SSLWIRELESS_API_TOKEN` and `SMS_SSLWIRELESS_SID` in `.env.production` when ready.
