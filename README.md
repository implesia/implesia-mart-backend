# Implesia Mart Backend

FastAPI backend for the Implesia Mart storefront and its admin dashboard.

## Current features

- Staff login with access and refresh tokens, logout, and password change. Refresh tokens rotate and can be revoked.
- Three roles: `superadmin`, `editor`, and `viewer`.
- Public product catalog and admin product editing, including images and options.
- Guest and signed-in carts, delivery rates, order quotes, checkout, public order lookup, and an admin order inbox.
- Admin dashboard counts.
- Storefront CMS for home, about, sustainability, shipping, privacy, FAQs, contact, and blogs. Each block has a public read and an editor write route.
- Audit events for selected admin changes. Superadmins can list them.
- Health probes, Prometheus metrics, login and refresh rate limits, and a failed-login alert.
- Local Compose for development. Production boots from the Render blueprint.

SMTP and Turnstile values are in settings. No request handler sends mail or checks a Turnstile token yet.

## Stack

| Concern               | Choice                                                  |
| --------------------- | ------------------------------------------------------- |
| API                   | FastAPI, Pydantic v2, Uvicorn / Gunicorn                |
| Database              | PostgreSQL 16, SQLAlchemy 2.0 async, asyncpg, Alembic   |
| Cache & rate limiting | Redis, slowapi                                          |
| Auth                  | JWT access + refresh (PyJWT), bcrypt, role hierarchy    |
| Logging               | structlog (JSON in production, console in debug)        |
| Quality               | pytest, Ruff, mypy                                      |
| Deploy                | Compose for local dev only; production is `render.yaml` |

Host ports are offset from `implesia-backend` so both APIs can run together: API **8001**, Postgres **5434**, Redis **6381**.

## Environment setup

```bash
just dev-setup
```

That writes `.env` when it is missing, starts Postgres and Redis, builds the API, runs migrations, and creates the admin user. The API is then on <http://localhost:8001>, with docs at `/docs`. Log in as `admin@implesia.com` / `change-me-too`.

To run the API on the host instead:

```bash
cp .env.example .env
# Generate a real key: python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up -d postgres redis

uv sync --frozen --extra dev
source .venv/bin/activate

alembic upgrade head
python -m scripts.create_superuser

uvicorn app.main:app --reload --port 8001
```

Copy `.env.example` and keep `ENVIRONMENT=local`. Production refuses a blank `SECRET_KEY`, the placeholder `change-me-in-production`, and any secret shorter than 32 characters. Leave `TRUSTED_PROXIES` empty when the browser talks to the API directly. Fill it with the proxy address only when a trusted proxy sets `CF-Connecting-IP` or `X-Forwarded-For`.

To exercise every endpoint from a desktop client, open the Bruno collection in [`bruno/`](bruno/README.md).

## API structure

Routes live under `/api/v1`. Interactive docs are at `/docs` when `DEBUG=true`. Bruno has one request per route.

Each storefront page has its own folder under `models`, `schemas`, `services`, and `endpoints`. A public router serves the storefront. An `/admin` router serves the dashboard. Business rules stay in services.

```
app/
  api/deps.py            shared dependencies: db session, current user, role guards
  api/v1/endpoints/      route handlers, one module per resource
    home/ about/ sustainability/ shipping/ privacy/ faqs/ contact/ blogs/
  core/                  settings, security primitives, logging, error envelope
  db/                    declarative base, mixins, async session factory
  models/                SQLAlchemy models, with the same page folders
  schemas/               Pydantic request and response models
  services/              business logic, kept out of the route handlers
alembic/versions/        migrations
scripts/                 operational one-offs and the production start script
tests/                   SQLite unit tests
  integration/           PostgreSQL transactions, locks, constraints, stock
```

| Area        | Public                                                                                | Admin                                                | Minimum role                    |
| ----------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------- | ------------------------------- |
| Health      | `GET /health/live`, `GET /health/ready`                                               | —                                                    | —                               |
| Metrics     | `GET /metrics`                                                                        | —                                                    | —                               |
| Auth        | `POST /api/v1/auth/login`, `refresh`, `logout`                                        | `GET /auth/me`, `POST /auth/change-password`         | viewer for the signed-in routes |
| Catalog     | `GET /api/v1/products`, `GET /api/v1/products/{id}`                                   | `GET` `POST` `PATCH` `DELETE /api/v1/admin/products` | editor                          |
| Cart        | `GET /api/v1/cart`, plus item create, update, and delete                              | `GET /api/v1/admin/carts`                            | editor for the inbox            |
| Delivery    | `GET /api/v1/delivery`                                                                | `GET` `PATCH /api/v1/admin/delivery`                 | editor                          |
| Orders      | `POST /api/v1/orders/quote`, `POST /orders/lookup`, `POST /orders`                    | `GET` `PATCH /api/v1/admin/orders`                   | editor                          |
| Dashboard   | —                                                                                     | `GET /api/v1/admin/dashboard`                        | editor                          |
| Audit       | —                                                                                     | `GET /api/v1/admin/audit-events`                     | superadmin                      |
| Users       | —                                                                                     | `GET` `POST` `PATCH` `DELETE /api/v1/users`          | superadmin                      |
| Home CMS    | `GET /api/v1/home/{banner,trust,categories,featured,showcase,reviews,faq,newsletter}` | `/api/v1/admin/home/...`                             | editor                          |
| Other pages | `GET /api/v1/pages/{about,contact,faqs,blogs,sustainability,shipping,privacy}/...`    | `/api/v1/admin/pages/...`                            | editor                          |

The public catalog returns published products only. A hidden product id answers `404`, the same as a missing id. Lookups use the product UUID. Create and update send `multipart/form-data`: a `payload` JSON field plus image files. List responses include `page`, `page_size`, `total`, and `pages`. Inventory `quantity` stays on the admin API.

A guest cart sends `X-Cart-Token`. Signing in merges that cart into the account cart. Checkout sends an `Idempotency-Key` header. Anonymous buyers look up an order with the order number and the phone used at checkout.

The CMS packages `home`, `about`, `sustainability`, `shipping`, `privacy`, `faqs`, `contact`, and `blogs` each keep their own ensure, list, reorder, and delete logic. Leave that copy in place. When the pattern is stable, a small shared helper can cover the repeated parts. A generic CMS framework is not needed.

### Error format

Every error uses the same envelope:

```json
{ "error": { "code": "validation_error", "message": "...", "details": null } }
```

A rate-limited request returns `429` with code `rate_limited` and no limiter internals.

## Admin roles

Roles are hierarchical: `superadmin` > `editor` > `viewer`. A higher role can call everything a lower role can.

| Role         | Can do                                                          |
| ------------ | --------------------------------------------------------------- |
| `viewer`     | Sign in, read `/auth/me`, change their own password             |
| `editor`     | Products, CMS, delivery rates, carts, orders, and the dashboard |
| `superadmin` | Create and edit staff accounts, and read the audit log          |

Disabling an account, changing a role, changing a password, and changing a product price or stock write an audit event in the same transaction. The audit list is superadmin-only.

## Migration

Schema changes are Alembic revisions in `alembic/versions/`. Apply them with:

```bash
alembic upgrade head
alembic check
alembic revision --autogenerate -m "describe the change"
```

Review an autogenerated file before you commit it. Production runs `alembic upgrade head` from `scripts/start.sh` before Gunicorn listens. That script does not downgrade. Returning to an older image, and when to run `alembic downgrade`, is in [`docs/rollback.md`](docs/rollback.md).

## Testing

```bash
uv sync --frozen --extra dev
uv run pytest          # SQLite unit tests, plus PostgreSQL integration tests when the server is up
uv run ruff check .
uv run mypy app scripts
uv build
python -m scripts.create_superuser
```

Unit tests under `tests/` use SQLite. Integration tests under `tests/integration/` use a throwaway database named `implesia_mart_integration`. They cover transactions, row locks, constraints, and the stock race. The whole integration layer skips when Postgres is unreachable. They never use the local Compose database.

A push or pull request runs the same lint, type check, tests, package build, and Docker image build from `.github/workflows/ci.yml`. Dependencies come from `uv.lock`.

## Deployment

Local containers:

```bash
docker compose up --build
```

The API container is published on host port **8001**. `docker-compose.yml` is local development only: Uvicorn reload, mounted source, and the local database password. It forces `ENVIRONMENT=local` and ignores any hosted `DATABASE_URL` in `.env`.

## Production setup

Production is the Render blueprint in `render.yaml`, not Compose. It creates managed Postgres and managed Redis in Singapore, generates `SECRET_KEY` and `FIRST_SUPERUSER_PASSWORD`, and starts the Docker image with `scripts/start.sh`. That script runs migrations, creates the bootstrap superuser, seeds the home banner when it is empty, then starts Gunicorn. There is no reload and no source mount.

`ENVIRONMENT=production` and `DEBUG=false`. `/docs` is disabled. `TRUSTED_PROXIES` is the platform private network, so a public client cannot spoof forwarded IP headers. `WEB_CONCURRENCY` is 2 workers in that one container. The health check is `GET /health/live`. Readiness is `GET /health/ready` and fails when Postgres or Redis is down.

Backup, retention, restore, and the monthly restore test for that database are in [`docs/backup-restore.md`](docs/backup-restore.md). The free database plan has no backups.

Returning to the previous image, and when to downgrade a migration, is in [`docs/rollback.md`](docs/rollback.md).

`GET /metrics` counts API responses, including 5xx, 401, and 429, and records request latency. It also reports whether Postgres and Redis answered at scrape time. Health probes are not included in those request counts. Gunicorn workers in one container share the counters. No separate metrics service is required.

A failed login writes `failed_login_alert` once per window: 5 failures for the admin email or any superadmin within 10 minutes, and 20 failures for any account within 5 minutes. Those counters are `login_failures_total`, `admin_login_failures_total`, and `failed_login_alerts_total`. An expired access token is not a login failure. Workers share the window through Redis.

Uploads stay on the one API instance, under `/media`. The Gunicorn workers in that container share the disk. `render.yaml` keeps `numInstances: 1`. A second instance would not see the first instance's files, so object storage and a CDN come before scaling out. A new deploy also replaces the container disk, so those files do not survive a redeploy. Local Compose keeps them in the `./media` folder on the host.

Public CMS reads under `/home` and `/pages` hit Postgres on every request. That is enough at the current size. When many readers ask for the same page, cache only those public GETs in Redis or with an HTTP cache, for 30 seconds or with an ETag. Admin, cart, and order responses stay `Cache-Control: no-store`. Product catalog reads stay uncached too, because price and stock change. Delivery rates already send `public, max-age=60`.

Guest carts stay until the shopper returns or signs in. Nothing deletes an unused guest cart. A later scheduled job removes guest carts whose `updated_at` is older than a threshold. Logged-in carts are not part of that job.
