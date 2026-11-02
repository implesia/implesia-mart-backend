# Project overview: Implesia Mart API

## What it does

FastAPI backend for the Implesia Mart storefront and its admin dashboard. It serves:

- **Storefront (public)**: products, categories, search, CMS pages (home, about, sustainability, shipping, privacy, FAQs, contact, blogs), site header/footer/contact settings, carts, orders, inquiries.
- **Admin (staff)**: editing all of the above, product badges, media uploads, orders and delivery status, dashboard overview, users and audit events.

There are no customer accounts. Shoppers stay anonymous. A guest cart is identified by the `X-Cart-Token` header.

## Tech stack

- Python, FastAPI, Pydantic v2
- SQLAlchemy (async) + Alembic migrations, PostgreSQL 16
- Redis (rate limiting, readiness)
- JWT access/refresh tokens for staff; roles `superadmin` > `editor` > `viewer`
- Tests: pytest on SQLite (plus Postgres integration tests); lint `ruff`; types `mypy`
- Dependencies pinned in `uv.lock`; `justfile` for common tasks; Bruno collection in `bruno/`

## Folder structure

```
app/
  main.py                FastAPI app, middleware, /health, /metrics, /media
  api/deps.py            db session, current user, role guards (require_editor, require_superadmin)
  api/v1/router.py       mounts every public and /admin router under /api/v1
  api/v1/endpoints/      route handlers (one module per resource; page folders home/, about/, ...)
  core/                  settings, security, logging, error envelope
  db/                    declarative base, mixins, async session
  models/                SQLAlchemy models
  schemas/               Pydantic request/response models
  services/              business logic (product_service, badge_service, image_storage, ...)
alembic/versions/        migrations
scripts/                 create_superuser, production start script, one-offs
tests/                   pytest suite
bruno/                   API request collection
docs/                    this documentation
```

## How to run (local)

With Docker Compose (recommended):

```bash
cp .env.example .env      # fill values locally; never commit .env
just dev-setup            # or: docker compose up -d
```

| Service | Host port |
| --- | --- |
| API (uvicorn, `--reload`) | 8001 |
| PostgreSQL | 5434 |
| Redis | 6381 |

On the host instead: `docker compose up -d postgres redis`, `uv sync --frozen --extra dev`, `alembic upgrade head`, `python -m scripts.create_superuser`, `uvicorn app.main:app --reload --port 8001`.

Interactive API docs are at `/docs` when `DEBUG=true`.

Tests: `pytest`, `ruff check .`, `mypy app`.

## Environment variable names

Names only. Values live in `.env` (see `.env.example`) and must never be committed.

- App: `ENVIRONMENT`, `DEBUG`, `SQL_ECHO`, `PROJECT_NAME`, `CORS_ORIGINS`
- Auth: `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `METRICS_TOKEN`
- Postgres: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- Redis: `REDIS_HOST_PORT`, `REDIS_URL`
- Proxy and rate limits: `TRUSTED_PROXIES`, `RATE_LIMIT_DEFAULT`, `RATE_LIMIT_LOGIN_IP`, `RATE_LIMIT_LOGIN_ACCOUNT`, `RATE_LIMIT_REFRESH_IP`, `RATE_LIMIT_REFRESH_ACCOUNT`, `RATE_LIMIT_ORDERS`, `RATE_LIMIT_SEARCH`
- First superuser: `FIRST_SUPERUSER_EMAIL`, `FIRST_SUPERUSER_PASSWORD`
- Mail: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `ORDER_NOTIFICATION_RECIPIENTS`
- `TURNSTILE_SECRET_KEY`

## Connection to the frontend repo

- Frontend repo: `implesia-mart` (Next.js), local dev on port 3001.
- The frontend reaches this API at the base URL in its `NEXT_PUBLIC_MART_API_URL` variable (local default `http://127.0.0.1:8001`).
- Storefront pages call public `/api/v1/...` endpoints. The admin dashboard calls `/api/v1/admin/...` through the frontend's BFF proxy (`/api/proxy/...`), which attaches the staff token.
- The frontend origin must be listed in `CORS_ORIGINS`.
- Uploaded media is served from `/media/...` (files under the media root, folder `products` for product media).
