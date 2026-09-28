# Implesia Mart Backend

FastAPI backend for the Implesia Mart storefront and its admin dashboard.

**Current scope:** project foundation, staff authentication, admin dashboard summary, and deploy. Order management uses the same layout and will be added in the next step, once the order fields are specified.

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
  core/                  settings, security primitives, logging, error envelope
  db/                    declarative base, mixins, async session factory
  models/                SQLAlchemy models
  schemas/               Pydantic request and response models
  services/              business logic, kept out of the route handlers
alembic/versions/        migrations
scripts/                 operational one-offs and the production start script
tests/                   pytest suite
```

New resources follow the same split already used by auth and the dashboard: model, schema, service, then a public router and an `/admin` router.

## API

| Method                        | Path                           | Minimum role |
| ----------------------------- | ------------------------------ | ------------ |
| `GET`                         | `/health/live`                 | —            |
| `GET`                         | `/health/ready`                | —            |
| `POST`                        | `/api/v1/auth/login`           | —            |
| `POST`                        | `/api/v1/auth/refresh`         | —            |
| `GET`                         | `/api/v1/auth/me`              | viewer       |
| `POST`                        | `/api/v1/auth/change-password` | viewer       |
| `GET`                         | `/api/v1/admin/dashboard`      | editor       |
| `GET` `POST` `PATCH` `DELETE` | `/api/v1/users[/{id}]`         | superadmin   |

Roles are hierarchical: `superadmin` > `editor` > `viewer`.

### Error format

Every error uses the same envelope:

```json
{ "error": { "code": "validation_error", "message": "...", "details": null } }
```

## Deploy

`render.yaml` defines a Postgres database, a Redis instance, and a Docker web service in Singapore. On boot, `scripts/start.sh` runs migrations, creates the bootstrap superuser from `FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD`, then starts Gunicorn.

`/docs` is disabled when `ENVIRONMENT=production`.

## Next

Order management (checkout capture, admin inbox, status changes, dashboard counts) lands in the same `models` / `schemas` / `services` / `endpoints` layout. SMTP and Turnstile settings are already in config for that step.
