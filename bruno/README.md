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
  "Public/Home" \
  "Private/Auth/01 Me.bru" \
  "Private/Dashboard" \
  "Private/Products/01 List Products.bru" \
  "Private/Products/02 Create Product.bru" \
  "Private/Products/03 Get Product.bru" \
  "Private/Products/05 Update Product.bru" \
  "Private/Products/06 Set Stock.bru" \
  "Public/Products" \
  "Private/Products/07 Delete Product.bru" \
  "Private/Home" \
  "Private/Users" \
  --env Local
```

That order logs in before the private calls. **Create Product** writes `PRODUCT_ID`. Get, update, delete, and the public product page all use that id. **Create User** writes `USER_ID`. Get, Update, and Delete user use that demo user, never the admin.

**Home / Create Slide** writes `BANNER_SLIDE_ID` and keeps the new slide unpublished. Get, Update, and Delete use that fixture. The public hero stays the five live slides.

**Home / Create Benefit** writes `TRUST_ITEM_ID` and keeps the new benefit hidden. Update, Reorder, and Delete use that fixture. Run List Benefits before Create so Reorder has every id. The public trust strip stays the live benefits.

**Home / Create Category** writes `CATEGORY_TILE_ID` and keeps the new tile hidden. Update, Reorder, and Delete use that fixture. Run List Categories before Create so Reorder has every id. The public category grid stays the live tiles.

**Home / Create Featured Product** writes `FEATURED_ITEM_ID` for a catalog product that is not already on the rail. Update, Reorder, and Delete use that fixture. Run List Featured and Pick Catalog Product first. Delete removes only the fixture, so the live rail returns to the seeded products.

**Home / Create Showcase Product** creates a hidden catalog product, adds it to the gadgets row, then deletes both. The public rows stay the seeded products. Run List Showcase first so Reorder has every gadgets id.

**Home / Create Review** adds a hidden screenshot to the review row, then deletes it. The public row stays the six seeded reviews. Run List Reviews first so Reorder has every id.

**Home / Create FAQ** adds a hidden question, then deletes it. The public list stays the six seeded questions. Run List FAQ first so Reorder has every id.

**Home / Create Perk** adds a hidden perk, then deletes it. The public subscribe block stays the three seeded perks. Run List Newsletter first so Reorder has every id.

**Pages / Update About Hero** uploads a left photo and changes the title, then **Restore About Hero** puts the seeded banner back. The public about hero stays the seeded heading and two photos.

**Pages / Create Stat** adds a hidden stat, then deletes it. The public about bar stays the four seeded stats. Run List Stats first so Reorder has every id.

**Pages / Create Story** adds a hidden story, then deletes it. The public about page stays the seeded story. Run List Stories first so Reorder has every id.

**Pages / Create Dress** adds a hidden custom-dress block, then deletes it. The public about page stays the seeded block. Run List Dresses first so Reorder has every id.

**Pages / Hide Vision** turns the vision card off, then **Restore Vision** puts the seeded card back. Run them together so the public about page stays both cards.

**Pages / Create Value** adds a hidden principle, then deletes it. The public about page stays the four seeded principles. Run List Values first so Reorder has every id.

**Pages / Create Step** adds a hidden order step, then deletes it. The public about page stays the four seeded steps. Run List Steps first so Reorder has every id.

**Pages / Hide Cta** turns the closing block off, then **Restore Cta** puts the seeded block back. Run them together so the public about page keeps the closing block.

**Pages / Update Sustainability Hero** uploads a left photo and changes the title, then **Restore Sustainability Hero** puts the seeded banner back. The public sustainability hero stays the seeded heading and two photos.

**Pages / Create Stat** adds a hidden habit, then deletes it. The public sustainability page stays the four seeded habits. Run List Impact first so Reorder has every id.

**Pages / Hide Origin Photo** hides the second photo, then **Restore Origin** puts both seeded photos back. Run them together so the public sustainability page keeps both photos.

Do not include `Private / Auth / Change Password` in this run. It replaces the admin password.

## Error codes

- `401` / `unauthenticated` — run Login again
- `403` / `forbidden` — account is viewer, or the last superadmin is being locked out
- `404` / `not_found` — that user or product is not in the database, or the product is hidden
- `409` / `conflict` — email or product slug already exists
- `422` / `validation_error` — path is not a UUID, the page is out of range, or the payload is invalid
