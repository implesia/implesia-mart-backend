# Implesia Mart Backend

FastAPI backend for the Implesia Mart storefront and its admin dashboard.

**Current scope:** project foundation, staff authentication, admin dashboard summary, the home-page banner, and deploy. Other storefront pages follow the same page folders. Order management uses the same layout and will be added once the order fields are specified.

## Stack

| Concern               | Choice                                                |
| --------------------- | ----------------------------------------------------- |
| API                   | FastAPI, Pydantic v2, Uvicorn / Gunicorn              |
| Database              | PostgreSQL 16, SQLAlchemy 2.0 async, asyncpg, Alembic |
| Cache & rate limiting | Redis, slowapi                                        |
| Auth                  | JWT access + refresh (PyJWT), bcrypt, role hierarchy  |
| Logging               | structlog (JSON in production, console in debug)      |
| Quality               | pytest, Ruff, mypy                                    |
| Deploy                | Docker Compose locally, Render via `render.yaml`      |

Host ports are offset from `implesia-backend` so both APIs can run together: API **8001**, Postgres **5434**, Redis **6381**.

## Getting started

```bash
just dev-setup
```

That writes `.env` when it is missing, starts Postgres and Redis, builds the API, runs migrations, and creates the admin user. The API is then on <http://localhost:8001>, with docs at `/docs`. Log in as `admin@implesia.com` / `change-me-too`.

To run the API on the host instead:

```bash
cp .env.example .env
# Generate a real key: python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up -d postgres redis

uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

alembic upgrade head
python -m scripts.create_superuser

uvicorn app.main:app --reload --port 8001
```

The API is then on <http://localhost:8001> with interactive docs at `/docs`.

To exercise every endpoint from a desktop client, open the Bruno collection in [`bruno/`](bruno/README.md).

To run everything in containers instead, use `docker compose up --build`. The API container is published on host port **8001**.

## Commands

```bash
pytest
ruff check . && ruff format .
mypy app scripts
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
alembic check
python -m scripts.create_superuser
```

## Layout

```
app/
  api/deps.py            shared dependencies: db session, current user, role guards
  api/v1/endpoints/      route handlers, one module per resource
    home/                one folder per storefront page (banner today)
  core/                  settings, security primitives, logging, error envelope
  db/                    declarative base, mixins, async session factory
  models/                SQLAlchemy models
    home/                page models
  schemas/               Pydantic request and response models
    home/
  services/              business logic, kept out of the route handlers
    home/
alembic/versions/        migrations
scripts/                 operational one-offs and the production start script
tests/                   pytest suite
```

Each storefront page gets its own folder under `models`, `schemas`, `services`, and `endpoints`. The home banner is the first page. New resources still split model, schema, service, then a public router and an `/admin` router.

## API

| Method                        | Path                           | Minimum role |
| ----------------------------- | ------------------------------ | ------------ |
| `GET`                         | `/health/live`                 | —            |
| `GET`                         | `/health/ready`                | —            |
| `POST`                        | `/api/v1/auth/login`           | —            |
| `POST`                        | `/api/v1/auth/refresh`         | —            |
| `GET`                         | `/api/v1/auth/me`              | viewer       |
| `POST`                        | `/api/v1/auth/change-password` | viewer       |
| `GET`                         | `/api/v1/products`                        | —            |
| `GET`                         | `/api/v1/products/{id}`                   | —            |
| `GET`                         | `/api/v1/admin/dashboard`                 | editor       |
| `GET` `POST`                  | `/api/v1/admin/products`                  | editor       |
| `GET` `PATCH` `DELETE`        | `/api/v1/admin/products/{id}`             | editor       |
| `GET`                         | `/api/v1/home/banner`                     | —            |
| `GET` `PATCH`                 | `/api/v1/admin/home/banner`               | editor       |
| `GET` `POST` `PATCH` `DELETE` | `/api/v1/admin/home/banner/slides[/{id}]` | editor       |
| `GET` `POST` `PATCH` `DELETE` | `/api/v1/users[/{id}]`                    | superadmin   |

Roles are hierarchical: `superadmin` > `editor` > `viewer`.

The public catalog returns published products only. A hidden product id answers `404`, the same as a missing id. Lookups use the product UUID, never the slug. Create and update send `multipart/form-data`: a `payload` JSON field plus image files. List responses include `page`, `page_size`, `total`, and `pages`, and omit the long product-page copy; that loads on the detail route. Inventory `quantity` stays on the admin API.

### Error format

Every error uses the same envelope:

```json
{ "error": { "code": "validation_error", "message": "...", "details": null } }
```

## Deploy

`render.yaml` defines a Postgres database, a Redis instance, and a Docker web service in Singapore. On boot, `scripts/start.sh` runs migrations, creates the bootstrap superuser from `FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD`, seeds the home banner when it is empty, then starts Gunicorn.

`/docs` is disabled when `ENVIRONMENT=production`.

## Next

Order management (checkout capture, admin inbox, status changes, dashboard counts) lands in the same `models` / `schemas` / `services` / `endpoints` layout. SMTP and Turnstile settings are already in config for that step.
