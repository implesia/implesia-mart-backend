# Daily Handoff & Cross-Device Sync — 2026-11-22

> **Purpose:** Single source of truth for resuming work seamlessly between **Home Laptop** and **Office PC** via Git without copying local AI chat databases.
> **Language Preference (Tushar):** Communicate with Tushar in **Bengali (বাংলা)** in chat sessions.
> **Core Scale Mandate (ALWAYS KEEP IN MIND):**
> - Target scale: **10,000+ active visitors/users** and **1,000+ sellers/dropshippers**.
> - Every schema, SQL query, index, cache, and WebSocket worker must be designed for high concurrency (zero N+1 queries, composite indexes, Redis Pub/Sub across multi-worker Gunicorn/Uvicorn, strict RBAC isolation).

---

## 1. Completed Backend Work — 2026-11-22 Session (Phases 11–17)

- **Security & Session Stability (Phase 11):**
  - Blocked non-staff (`customer`) accounts from `/api/v1/auth/login` and `/api/v1/auth/refresh` (403).
  - Fixed admin auto-logout race condition in `refresh_token_service.py` with a 30s rotation grace window so concurrent polls/tabs/isolates never trigger false family revocation.
- **Enterprise Dynamic RBAC (Phases 16 & 17 — Migrations `0106` & `0107`):**
  - **`0106_dynamic_role_permissions.py`:** `role_permissions` table + `permission_service.py` + `require_module_access()` live enforcement across `/api/v1/admin/*` + `permissions` map in `/api/v1/auth/me`.
  - **`0107_dynamic_roles.py`:** `roles` table (`app/models/role.py`), migrated `users.role` to `String(50)` FK -> `roles.slug`, protected system roles (`superadmin`, `editor`, `viewer`, `customer`), and full custom role CRUD + safe delete with atomic user reassignment (`GET/POST /api/v1/users/roles`, `PATCH/DELETE /api/v1/users/roles/{slug}`, `delete-impact`).
- **Admin Reviews & Notifications (Phases 13 & 14):**
  - Added `admin_reviews.py` (`/api/v1/admin/reviews/overview`, list, `by-product`, edit, delete).
  - Removed customer notification delete access; added `admin_notifications.py`, single notification detail (`GET /api/v1/customer/notifications/{id}`), and read/unread toggle.
- **Inventory Enhancements (Phase 12):** Added product thumbnail URLs to admin product search for New Purchase picker.

*(Companion Frontend `implesia-mart`: All Phases 11–17 implemented including Dynamic RBAC UI, Review Management, Global Admin Table `#` + Checkboxes, Customer Notification Sound + Detail Page + Read/Unread UX, and A4 Customer Invoice with Logo + bottom-right SVG QR Code.)*

---

## 2. Prior Completed Baseline — 2026-11-21 (Already on `main`)
- Customer Auth, Dashboard, Cart Merge, Verified Reviews, 30-day Notifications (`0102`–`0104`).
- SaaS Accounting, 7-page Reports APIs + `.xlsx` exports, Superadmin Safe Delete (`0105`).

---

## 3. Tomorrow's Plan & TODO (Office PC Workstream)

### A. Real-Time Notification & Communication Architecture (WebSocket + Redis Pub/Sub)
- **Current State:** HTTP Polling (Admin 25s/3m, Customer 60s) + Telegram Bot + SMS adapter.
- **Target Upgrade (for 10,000+ users & 1,000+ sellers):**
  - **WebSocket (`wss://mart-api.implesia.com/ws/...`) + Redis Pub/Sub** for real-time instant notifications AND 2-way live messaging across multiple Gunicorn/Uvicorn workers.
  - **PostgreSQL** remains the durable store (`customer_notifications`, `conversations`, `messages`, `conversation_read_states`).
  - **Connection Management:** JWT handshake auth, heartbeat ping/pong, per-user connection cap, Redis presence, graceful fallback for offline users.

### B. Direct Communication System (TODO — Build Next)
- **3 Channels:**
  1. **Customer ↔ Seller** (dropshipper/vendor direct messaging).
  2. **Seller ↔ Admin** (support, approvals, order/payout queries).
  3. **Customer ↔ Implesia Mart Support / Admin**.
- **RBAC & Oversight:**
  - Add `communication` module to `MODULE_DEFINITIONS` so Superadmin can assign it dynamically to any role (e.g., `Communication Manager`, `CMS Management`, `Support Agent`).
  - Admin / permitted staff can monitor threads and reply directly.
- **Planned Tables (Next Migration `0108`):**
  - `conversations` (`id`, `type`, `customer_id`, `seller_id`, `order_id?`, `product_id?`, `assigned_staff_id?`, `status`, `last_message_at`, `created_at`).
  - `messages` (`id`, `conversation_id`, `sender_id`, `sender_role`, `body`, `attachment_url?`, `is_internal_note`, `created_at`).
  - `conversation_read_states` (`conversation_id`, `user_id`, `last_read_at`).

### C. SaaS Dropshipping Platform (Upcoming Major Milestone)
- Seller/Dropshipper registration & application workflow -> Admin review & approval -> Seller portal, product catalog sync, order fulfillment, commissions, payouts.

### D. DevOps & Production Deployment (Pending Rollout)
- Production (`mart-api.implesia.com` VPS `72.60.199.155` & `mart.implesia.com` Cloudflare Workers) is still on an older release (`0100`–`0107` pending).
- Sequence: `pg_dump` backup -> `git pull origin main` -> `alembic upgrade head` (through `0107`) -> rebuild Docker container -> `npm run deploy:vinext` -> Live Smoke Test.
- Verify Caddy & Cloudflare WebSocket proxy support before deploying WebSocket endpoints.

---

## 4. Quick Resume Checklist on Office PC Tomorrow
1. Pull latest `main` in both repos:
   ```bash
   git -C implesia-mart-backend pull origin main
   git -C implesia-mart pull origin main
   ```
2. Apply migrations up to `0107` on Office PC local DB:
   ```bash
   cd implesia-mart-backend && alembic upgrade head
   ```
3. In Antigravity on Office PC, say:
   > *"আমার সাথে বাংলায় কথা বলবে। `docs/HANDOFF.md` পড়ো—আজকে আমরা WebSocket Notification ও Communication System (Customer-Seller-Admin Chat) নিয়ে কাজ করব।"*
