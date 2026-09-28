# Implesia Mart Backend — Bruno

Open this folder as a Bruno collection. Same layout as `implesia-backend/bruno`:

- `bruno.json` + `collection.bru`
- `environments/` — Local, Stage, Production
- `Public/` — no JWT
- `Private/` — Bearer `{{ACCESS_TOKEN}}`

The collection pre-request script also attaches `Authorization` for `/api/v1/admin/*`, `/api/v1/users`, `/auth/me`, and `/auth/change-password`.

## Open in Bruno

1. Bruno → **Open Collection**
2. Select `implesia-mart-backend/bruno`
3. Environment = **Local**

API must be running: `uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload`

Local login: `admin@implesia.com` / `change-me-too` (same as `FIRST_SUPERUSER_PASSWORD` in `.env`).

Stage and Production hosts in the env files are placeholders until those deploys exist.

## Run from the terminal

```bash
cd bruno
npx @usebruno/cli run \
  "Public/Health" \
  "Public/Auth" \
  "Private/Auth/01 Me.bru" \
  "Private/Dashboard" \
  "Private/Users" \
  --env Local
```

That order logs in before the private calls. **Create User** writes `USER_ID`. Get, Update, and Delete use that demo user, never the admin.

Do not include `Private / Auth / Change Password` in this run. It replaces the admin password.

## Error codes

- `401` / `unauthenticated` — run Login again
- `403` / `forbidden` — account is viewer, or the last superadmin is being locked out
- `404` / `not_found` — that user id is not in the database
- `409` / `conflict` — email already exists
- `422` / `validation_error` — path is not a UUID, or the payload is invalid
