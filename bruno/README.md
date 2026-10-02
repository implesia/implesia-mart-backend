# Implesia Mart Backend — Bruno

Open this folder as a Bruno collection. Same layout as `implesia-backend/bruno`:

- `bruno.json` + `collection.bru`
- `environments/` — Local, Stage, Production
- `Public/` — no JWT
- `Private/` — Bearer `{{ACCESS_TOKEN}}`

The collection pre-request script also attaches `Authorization` for `/api/v1/admin/*` (dashboard and products), `/api/v1/users`, `/auth/me`, and `/auth/change-password`. `GET /api/v1/products` is public and does not send a token.

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
  "Private/Products/01 List Products.bru" \
  "Private/Products/02 Create Product.bru" \
  "Private/Products/03 Get Product.bru" \
  "Private/Products/05 Update Product.bru" \
  "Private/Products/06 Set Stock.bru" \
  "Public/Products" \
  "Private/Products/07 Delete Product.bru" \
  "Private/Users" \
  --env Local
```

That order logs in before the private calls. **Create Product** writes `PRODUCT_ID`. Get, update, delete, and the public product page all use that id. **Create User** writes `USER_ID`. Get, Update, and Delete user use that demo user, never the admin.

Do not include `Private / Auth / Change Password` in this run. It replaces the admin password.

## Error codes

- `401` / `unauthenticated` — run Login again
- `403` / `forbidden` — account is viewer, or the last superadmin is being locked out
- `404` / `not_found` — that user or product is not in the database, or the product is hidden
- `409` / `conflict` — email or product slug already exists
- `422` / `validation_error` — path is not a UUID, the page is out of range, or the payload is invalid
