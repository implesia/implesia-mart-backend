# Changelog

Newest first. Every task adds an entry: date, what changed, files touched, and anything the frontend repo (`implesia-mart`) must change.

- **Bangla QR payment: admin QR image and partial advance at checkout (2026-11-03).**
  - New table `payment_settings` (one row, slug `main`) with the Bangla QR image path. Public `GET /api/v1/site/payment` (`no-store`) → `{bangla_qr_src, bangla_qr_enabled}` (`null`/`false` when none). Admin (editor auth, audited, `no-store`): `GET /api/v1/admin/site/payment`, `POST …/qr` (multipart `image`, checked by bytes, 5 MB, rate-limited; replacing deletes the old file), `DELETE …/qr`. Files go to the new `media/payment/` folder.
  - Orders: `payment_method` may be `cod` or `bangla_qr`. New columns `advance_percent` (25/50/75/100), `advance_amount`, `due_amount`, `payment_reference` (transaction ID / sender number). The server computes `advance = ceil(total × % / 100)` and `due = total − advance`; the client never sends amounts. `bangla_qr` is refused (422) while no QR is set; percent and reference are validated. `QuoteRead.bangla_qr_options` gives the four choices for the quoted total (empty with no QR). `OrderRead` / `PublicOrderRead` return the payment fields; only `OrderRead` has `payment_reference`.
  - Migration **0091** (additive; applied to the local dev DB only, downgrade checked): creates `payment_settings` (no seed row → feature off until a QR is uploaded), adds the four order columns, replaces the check `ck_orders_ck_orders_payment_cod` (double-prefixed name from 0005) with `ck_orders_payment_known`, adds `ck_orders_advance_percent_known` and `ck_orders_advance_non_negative`. No row is updated. Downgrade refuses while any `bangla_qr` order exists.
  - Tests: `tests/test_bangla_qr_payment.py` (ceil split, upload/replace/delete + live public read + auth, refused without QR, invalid percent/reference/client amounts, stored split in placed and admin order, COD due = total).
  - Files: `alembic/versions/0091_bangla_qr_payment.py`, `app/models/payment_settings.py`, `app/models/order.py`, `app/models/__init__.py`, `app/schemas/payment.py`, `app/schemas/order.py`, `app/services/payment_service.py`, `app/services/order_service.py`, `app/services/image_storage.py`, `app/api/v1/endpoints/site_payment.py`, `app/api/v1/router.py`, `tests/test_bangla_qr_payment.py`, docs.
  - Frontend (`implesia-mart`, branch `feat/bangla-qr-payment`): admin "Payment QR" page, QR card on the product page, "Bangla QR" checkout method sending `payment_method` / `advance_percent` / `payment_reference`, payment block in admin order details. Deploy the backend (and run 0091) before the frontend.
- **Uploaded media is stored in Cloudflare R2 (2026-11-03).**
  - Photos and videos are uploaded to the S3-compatible bucket when `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `MEDIA_PUBLIC_BASE_URL` are all set. The object key is `<folder>/<name>` (the same layout as the old disk path). The database value stays `/media/<folder>/<name>`. `Content-Type` is set from the sniffed type.
  - `GET` and `HEAD /media/<folder>/<name>` answer `307` to `MEDIA_PUBLIC_BASE_URL/<folder>/<name>` in that mode. Paths that leave the known folders, or that contain `..`, are `404`.
  - Deleting an owned media reference deletes the object. When the five settings are empty, writes, reads, and deletes stay on `media_root` (local disk), which is what tests and local Compose use. A partial set of the five settings refuses to start.
  - Existing files on the VPS volume are not moved by the app. The copy command (rclone or `aws s3 sync`, same keys) is in `docs/deploy-media-persistence.md`.
  - Removed the committed Wrangler account cache and ignored `.wrangler/`.
  - Files: `app/core/config.py`, `app/core/media_files.py`, `app/services/image_storage.py`, `app/main.py`, `pyproject.toml`, `uv.lock`, `tests/test_object_storage.py`, `tests/conftest.py`, `tests/test_deploy_config.py`, `.env.example`, `.gitignore`, `docker-compose.prod.yml`, `render.yaml`, `docs/deploy-media-persistence.md`, docs.
  - Frontend: no API change. Keep using the `/media/...` values the API returns. The browser follows the redirect to `https://media.implesia.com/...`. If an image optimizer refuses a redirect to another host, allow `media.implesia.com` or load that host directly.
- **Showcase choices: published products from any category (2026-11-03).**
  - Bug 1: `choices` in `GET /api/v1/admin/home/showcase` were "every product in the row key's category subtree", with no `published` filter. So the Add product modal listed hidden products (live: the `fashion` category holds only hidden products) and never the published ones (live: all 5 published products are in `electronics-2`).
  - Bug 2: the Trending row has key `gadgets`, but live has no `gadgets` category (`GET /categories/gadgets` → 404), so its `choices` were empty and the frontend disabled "Add product".
  - Fix: `choices` = every published product (title order), the same list for each row, read once per request. `POST`/`PATCH /admin/home/showcase/rows/{key}/items` accept any published product and reject a hidden one with 422 "Choose a published product" (an edit may keep the product already in that slot even if it was hidden since). The row key is now only an identifier; the old "Choose a product from this category" 422 is gone. First-run seeding still picks published products from the key's category. No migration, response shape unchanged.
  - Tests: `tests/test_home_showcase.py` (hidden product refused; new `test_showcase_choices_are_published_products_from_any_category`).
  - Files: `app/services/home/showcase_service.py`, `tests/test_home_showcase.py`, docs.
  - Frontend (`implesia-mart`, branch `feat/showcase-trending`): Trending row shown under the hero with a new tile design, admin copy says "published products". No API change needed there; deploy both together.
- **Variant products keep their card discount after a save (2026-11-03).**
  - Bug: saving a variant product in the dashboard without changing its variants sends `price` + `compare_at_price: null`; the update wrote those on the product row and skipped the variant roll-up. Product cards read `products.compare_at_price`, so the struck-through price and the `-X%` badge vanished (live: every product had `compare_at_price: null` in `GET /api/v1/products` while its variants still had compare-at prices, e.g. ৳945 / ৳1,350).
  - Fix: `product_service.update_product` now calls `variant_service.sync_price` for variant products after every save, so `price` / `compare_at_price` always come from the cheapest active variant (same rule as `rollup`, shared helper `_copy_cheapest_price`).
  - Migration **0090** (data only, no schema change): re-syncs `price` / `compare_at_price` of products with variants from their variants. Plain products, variants, carts and orders are untouched; no downgrade action. Checked on the local DB: the broken row was repaired, plain products' checksum unchanged.
  - Test: `tests/test_variants.py::test_saving_the_form_keeps_the_card_price_from_the_variants`.
  - Files: `app/services/product_service.py`, `app/services/variant_service.py`, `alembic/versions/0090_variant_card_price_resync.py`, `tests/test_variants.py`, docs.
  - Frontend: no change needed. The product card (`app/(client)/products/_components/product-card.tsx`) already shows the selling price, the struck-through regular price and a `-X%` badge top-right (custom badges sit top-left) whenever `compare_at_price > price`.
- **Quantity discount on the line total, rounded up (2026-11-02).**
  - New rule in the one pricing function (`pricing_service.price_line`, used by the product page block, cart, quote and order): `total = selling price × quantity`, `final = ceil(total − total × tier % / 100)`, `discount = total − final`. Replaces the old "unit price − round(regular × extra %)" rule. Tier lookup is unchanged (nearest tier at or below the quantity; none → no discount). Integer maths in `discounted_total()` (hundredths of a percent), so 2772 stays 2772. The browser still never sends a price.
  - Response shape unchanged, meaning changed: `unit_price` on cart, quote and order lines is now the quantity-1 selling price; `line_total` is the discounted, rounded-up amount, so `unit_price × quantity − line_total` = the quantity discount in taka. `quantity_discount_percent` is the tier % applied to the line. No migration; placed orders keep their stored snapshot (older orders keep the old per-unit prices).
  - Tests: `tests/test_pricing.py` (owner examples 700 × 2/3/4, nearest lower tier, no tiers, exact integer maths, updated cart/quote/order expectations); expected totals updated in `tests/test_cart.py`, `tests/test_orders.py`, `tests/test_variants.py`.
  - Files: `app/services/pricing_service.py`, `app/schemas/cart.py` (comment), `tests/test_pricing.py`, `tests/test_cart.py`, `tests/test_orders.py`, `tests/test_variants.py`, docs.
  - Frontend (`implesia-mart`, same task): `lib/mart-api/pricing.ts` mirrors the rule for instant display; product page shows `qty × price = total − discount (x %) = final`; cart drawer and checkout show the quantity discount line from `quantity_discount_percent`.
- **Home video/media section (2026-11-02).**
  - New table `home_media` (migration **0089**, additive, no seed row; applied to the local dev DB only). Model `HomeMedia`, schemas `app/schemas/home/media.py` (`MediaWrite`, `MediaAdmin`, `MediaPublic`, `MediaUploaded`), service `app/services/home/media_service.py`, endpoints `app/api/v1/endpoints/home/media.py`.
  - Public `GET /api/v1/home/media` → the section or `null` (inactive, empty, or no usable media). Admin (editor auth, audited, `no-store`): `GET`/`PUT /api/v1/admin/home/media`, `POST /api/v1/admin/home/media/image` (5 MB), `POST /api/v1/admin/home/media/video` (MP4/WEBM, 50 MB). Files are stored in `media/home-media/` (new storage folder); replaced or dropped files are deleted on save.
  - Validation: YouTube links reuse `youtube_id()` and are stored as the id; button link must be `/path` or `https://`; `cta_enabled` needs label and link; publishing needs a heading and the chosen type's media.
  - Frontend must: call `GET /api/v1/home/media` with no cache and render it above the testimonials; add the admin editor that uploads files to `…/image` / `…/video` and then `PUT`s `youtube_url` (link) rather than the id. Done in the frontend repo in the same task.
  - Files: `alembic/versions/0089_home_media.py`, `app/models/home/media.py`, `app/models/__init__.py`, `app/schemas/home/media.py`, `app/services/home/media_service.py`, `app/services/image_storage.py`, `app/api/v1/endpoints/home/media.py`, `app/api/v1/router.py`, `tests/test_home_media.py`, `tests/test_write_schema.py` (write-schema count 130 → 131), docs.
- **SEO follow-ups: `updated_at` for the sitemap, readable Bengali slugs (2026-11-02).**
  - `PublicProductCard` (list items, `GET /products/by-slug/{slug}`, `GET /products/{id}`) and category tree nodes (`GET /categories/tree`) now return `updated_at` (ISO datetime, the row's last change). Additive, nullable in the schema; no migration.
  - New products with a Bengali title get a phonetic Latin slug (`app/services/transliteration.py`): "স্মার্ট ঘড়ি" → `smart-ghori` instead of `smaartt-ghddi`. Only `allocate_slug` on create uses it; existing slugs never change (editing a title keeps the slug) and an explicit `slug` in the payload still wins. Duplicates get `-2`, `-3`…
  - Files: `app/schemas/product.py`, `app/schemas/category.py`, `app/services/product_service.py`, `app/services/category_service.py`, `app/services/transliteration.py`, `tests/test_product_seo.py`, `tests/test_product_urls.py` (`updated_at` is no longer in its "internal fields" list).
  - Frontend (same day): sitemap categories and real `lastModified`, product JSON-LD shipping/return policy/AggregateOffer, catalog canonicals and 307, verification meta, HSTS, gallery alt fallback.
- **Product SEO fields and editable slug (2026-11-02).**
  - `products.seo_title` (max 120), `seo_description` (max 320), `seo_keywords` (max 500, comma separated, trimmed and de-duplicated), all default `""`. Accepted on `POST`/`PATCH /admin/products` (on PATCH, omitted or `null` = keep) and returned in `AdminProductRead` and `PublicProductDetail`.
  - `PATCH /admin/products/{id}` accepts `slug` (lowercased; `^[a-z0-9]+(-[a-z0-9]+)*$`, max 160). A slug used by another product returns 409 `{"errors": [{"field": "slug", "message", "fix"}]}` (Bengali); a bad format is 422.
  - Old slugs keep working: on a slug change the old slug is stored in the new table `product_slug_redirects` (slug PK, product_id FK ON DELETE CASCADE). `GET /products/by-slug/{slug}` falls back to it (published products only). Changing back to an old slug, or a new product taking an old slug, removes that redirect row.
  - Migration `0088_product_seo_fields` (additive: 3 columns with server default `''` and the new table; has a downgrade). Applied to the local dev DB only; products, published count and price sum unchanged.
  - Files: `alembic/versions/0088_product_seo_fields.py`, `app/models/product.py`, `app/models/__init__.py`, `app/schemas/product.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_product_seo.py`.
  - Frontend (same day): admin SEO section (preview, counters, slug), storefront metadata and JSON-LD use the fields, `htmlLimitedBots` head-metadata fix and per-page share cards.
- **Admin-configurable max quantity per order (replaces the hardcoded 5).**
  - `pricing_settings.max_quantity` (default 10, 1–1000): the store-wide limit of pieces of one product (or one option) per order. `GET`/`PUT /api/v1/admin/pricing` read/write it as `max_quantity_per_order`; omitting it on `PUT` keeps the stored value.
  - A product's `max_order_quantity` is now "custom limit": NULL = use the store-wide limit, a number (1–1000) replaces it for that product (higher or lower).
  - Cart add/update, quote and order check the quantity against min(effective limit, stock). Over the limit: 422 "এই পণ্যটি এক অর্ডারে সর্বোচ্চ Nটি নেওয়া যাবে।" (Bengali digits). Over stock: "স্টকে এতগুলো নেই। পরিমাণ কমিয়ে আবার চেষ্টা করুন।" (no count). The quote marks such a line `available: false` as before.
  - Removed every hardcoded 5: `cart_service.MAX_QTY`, `variant_service.PLATFORM_MAX_QTY`, `le=5` in the cart/order/product schemas and the DB CHECKs. The hard ceiling is now `QUANTITY_CEILING = 1000` (`app/schemas/pricing.py`).
  - API: `PublicProductDetail.max_per_order` and the new `PublicVariant.max_quantity` = min(effective limit, stock); cart lines' `max_quantity` the same. So 8 pieces (30 % with the default tiers) can be bought when the limit allows.
  - Migration `0087_order_quantity_limit` (non-destructive): adds the column (server default 10) with a 1–1000 CHECK, widens the product min/max and cart/order line quantity CHECKs from 5 to 1000. Applied to the local dev DB only; products, prices and the row count unchanged.
  - Files: `alembic/versions/0087_order_quantity_limit.py`, `app/models/pricing.py`, `app/models/product.py`, `app/models/cart.py`, `app/models/order.py`, `app/schemas/pricing.py`, `app/schemas/product.py`, `app/schemas/cart.py`, `app/schemas/order.py`, `app/services/pricing_service.py`, `app/services/variant_service.py`, `app/services/cart_service.py`, `app/services/order_service.py`, `app/services/product_service.py`, `tests/test_pricing.py`, `tests/test_variants.py`, `tests/test_product_create_errors.py`, `tests/integration/test_stock.py`, `tests/integration/test_variants.py`.
  - Note: because the exposed maximum is min(limit, stock), a product whose stock is below the limit reveals that stock count through `max_per_order` / `max_quantity`.
  - Frontend (same day): Admin › Discounts field, product form "store-wide / custom" limit, quantity selectors and messages up to the new limit.
- **Dynamic discounts: regular price, base %, quantity tiers, order price snapshot.**
  - One pricing function (`app/services/pricing_service.py`) prices the product page block, cart lines, the quote and the order. The browser never sends a price (`unit_price` in a cart/order body is still a 422).
  - Rule: `total % = min(base % + extra % of the highest tier reached, max %, 99.99 %)`. Unit price = quantity-1 price − round(regular × (total − base) / 100), Decimal, half up, whole taka. So 28 % + 2 % at 8 pieces = 30 %; ৳1,000 → ৳700.
  - Default tiers: 2 → +0.25, 3 → +0.5, 4 → +0.75, 5 → +1, 6 → +1.25, 7 → +1.5, 8+ → +2. Default max 90 %.
  - New table `pricing_settings` (singleton: `tiers_enabled`, `max_discount` in hundredths, `tiers` JSON), seeded with the defaults. `GET` (staff) / `PUT` (editor+) `/api/v1/admin/pricing`, `Cache-Control: no-store`.
  - `products`: `base_discount` (hundredths, NULL = derived from price/compare_at), `tier_mode` (`global`/`custom`), `tiers` (JSON). Admin create/update accept `regular_price`, `base_discount_percent`, `tier_mode`, `tiers`; the API then stores `price` = quantity-1 selling price and `compare_at_price` = regular price (None without a discount). Re-sending the same price/compare_at keeps a saved base %; changing them clears it (derived again).
  - `order_items`: `regular_price`, `base_discount`, `quantity_discount`, `total_discount` snapshot (nullable; older orders stay NULL). Order lines are priced from the locked product row.
  - Responses: `AdminProductRead` + `regular_price`, `base_discount_percent`, `tier_mode`, `tiers`; `PublicProductDetail.pricing`; cart lines + `regular_price`, `base/quantity/total_discount_percent`, `pricing`; quote lines + `regular_price` and the % fields; `OrderRead` items + snapshot fields. Public order lookup unchanged.
  - Migration `0086_dynamic_discounts` (additive; existing prices untouched — verified on the dev DB: same row count, price sums and checksum before/after).
  - Existing tests that buy 2+ pieces now expect the default tier discount (`tests/test_cart.py`, `tests/test_orders.py`, `tests/test_variants.py`); `tests/integration/test_stock.py` follows the new `_claim` signature; `tests/test_catalog_categories.py` ignores the `pricing` block's `min_quantity` when checking that stock is never exposed.
  - Files: `alembic/versions/0086_dynamic_discounts.py`, `app/models/pricing.py`, `app/models/product.py`, `app/models/order.py`, `app/models/__init__.py`, `app/schemas/pricing.py`, `app/schemas/product.py`, `app/schemas/cart.py`, `app/schemas/order.py`, `app/services/pricing_service.py`, `app/services/product_service.py`, `app/services/cart_service.py`, `app/services/order_service.py`, `app/api/v1/endpoints/admin_pricing.py`, `app/api/v1/endpoints/admin_products.py`, `app/api/v1/router.py`, `tests/test_pricing.py` and the tests above.
  - Frontend (same day): admin product form (regular price, base %, live selling price, global/custom tiers), `/admin/pricing` settings page, product page and cart show the total % for the quantity, admin order shows the snapshot.
  - Limitation: one cart line is capped at 5 pieces (`MAX_QTY`), so the 6/7/8+ tiers cannot be reached yet. (Fixed by the max-quantity entry above.)
## 2026-11-02 (summary of today's work)

- **Showcase:** test that a pinned product drops out of `GET /home/showcase` once it is hidden (admin view still lists it). No API change. File: `tests/test_home_showcase.py`.
- **Custom thumbnails for gallery videos and YouTube items.**
  - `GalleryImage.thumbnail` (admin and public gallery items); always empty for photos.
  - New multipart parts on `POST` / `PATCH /admin/products`: `thumbnails` (image files, same checks as gallery photos: JPEG/PNG/WEBP/GIF, 5 MB) and `thumbnail_targets` (JSON list, one per file: a gallery item id, or `video:<n>` for the n-th video uploaded in the same request).
  - A replaced or removed thumbnail file is deleted from disk (it is one of the product's owned media refs); thumbnails are also deleted with the product.
  - Error "Thumbnail does not match a video" (create: Bengali `{errors}` on field `images`).
  - Files: `app/schemas/product.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_product_media.py`.
  - Frontend: admin gallery "Add / Change / Remove thumbnail" and the storefront poster with a play button (frontend repo, same day).
- **Docs**: added `docs/AI_INSTRUCTIONS.md`, `PROJECT_OVERVIEW.md`, `BUSINESS_LOGIC.md`, `API.md`, `CHANGELOG.md`, `TODO.md`; added root `AGENTS.md`; README now points to `docs/AI_INSTRUCTIONS.md`.
- **Bulk product delete** (`8d3800c`): `DELETE /api/v1/admin/products/bulk` with `{"ids": [...]}`, editor+, max 100, partial success with `deleted` / `skipped` / `failed`. Files: `app/schemas/product.py`, `app/services/product_service.py`, `app/api/v1/endpoints/admin_products.py`, `tests/test_product_bulk_delete.py`.
  - Frontend: `/admin/products` row checkboxes, select-all and "Delete selected" use this endpoint (frontend commit `d724296`).
- **Gallery videos and YouTube** (`0728d82`): MP4/WEBM upload up to 50 MB, YouTube links stored as ids.
- **Drafts** (`f7f964c`): products save as drafts with only a name; publishing needs price, category and main image.
- **Frontend-only fix, no API change**: the Image/Video options in the admin Gallery "+ Add" menu did not open the file picker, and YouTube items were dropped on save (frontend commit `179fea3`).

# History from git log

## 2026-11-02

- Add admin bulk product delete endpoint (`8d3800c`)
- feat(products): gallery videos (MP4/WEBM upload, 50 MB) and YouTube links (`0728d82`)
- feat(products): save products as drafts with only a name (`f7f964c`)

## 2026-11-01

- feat(products): field-level Bengali errors on admin product create (`ebb1fdc`)
- feat(badges): admin-managed custom product badges (`1862f58`)

## 2026-10-27

- Blog posts: name every invalid field in 422/409 errors (`b1461ca`)
- feat(contact): central dynamic site contact settings (`fbe177c`)

## 2026-10-26

- feat(site): admin-managed storefront header menu (`43f84c9`)
- test(catalog): cover inline category creation then product assignment (`6027726`)
- fix(qa): script-scheme guard for admin href fields, FK indexes (migration 0081), hardening tests (`9d44102`)
- feat(footer): admin-managed site footer config (migration 0080, public + admin API, tests) (`b3cb29e`)
- feat(home): content-managed promo banner API, upload and migration 0079 (`1e4eadb`)
- feat(blogs): validated cover upload, cover/SEO fields, legacy-safe reads, migration 0078 (`411af2b`)
- feat(search): global search API, catalog q filter and trigram index migration 0077 (`f88ca31`)

## 2026-10-25

- feat(api): public order items expose product_id; tests for id-based product addressing (`8f26f1f`)
- test(catalog): type annotations for variant tests (no new mypy errors) (`2effdeb`)
- docs: fix README table gap (`142a0cd`)
- docs: place the variants note after the endpoint table (`6f77fd2`)
- docs: keep the README endpoint table intact (`c17745a`)
- test(catalog): variant unit and PostgreSQL integration tests; docs for variant_id (`6579150`)
- feat(catalog): product variants with per-variant price and stock (`a88b321`)
- test(catalog): category tree, visibility, deletion, product assignment and legacy-compat tests (`d26919f`)
- feat(catalog): attach cycle trigger to the model and add Postgres integration tests for tree, FKs and stock races (`c3d47b1`)
- fix(stock): stock refusals use a generic message that never names the remaining count (`6b3d822`)
- fix(catalog): migration 0075 uses convention-aware check names and legacy tile labels (`facfb26`)
- feat(catalog): public category tree and admin category endpoints (`b9419da`)
- feat(catalog): category-aware product schemas, services and legacy adapters (`6dd30ac`)
- feat(catalog): add categories table, products.category_id and migration 0075 (`33f10df`)

## 2026-10-17

- feat(categories): nest home categories with validated parent links (`88dfbcb`)
- fix(deploy): persist uploaded media on a named volume in production compose (`b122430`)
- feat(inquiries): store storefront inquiries with admin API (`8790670`)

## 2026-10-15

- chore(bruno): send single optional image in sustainability requests (`1ae60d0`)
- test(sustainability): cover optional single image for every section (`df73f15`)
- feat(sustainability): make section photos optional and single with legacy-compatible API (`64dfc59`)
- test(about): cover single-image write, validation and upload (`593b20b`)
- feat(db): migration 0071 archives extra about images, keeps first (`5c6b503`)
- feat(about): single image for hero, story and dress sections (`66e3576`)

## 2026-10-14

- QA remediation phase 1+2 (backend.patch) (`4b8e2ee`)

## 2026-10-07

- Keep new products hidden and public order lookup free of a delivery address. (`1bf0f36`)

## 2026-10-06

- Point the public Mart API at the VPS hostname. (`17cd1af`)
- Dial the VPS by hostname so Cloudflare can reach the Mart API. (`dacc033`)
- Point the mart API hostname at the VPS instead of Render. (`3a9891f`)
- Skip TLS for private database hostnames. (`77e6516`)

## 2026-10-05

- Point the Production Bruno environment at the mart API. (`5238d4a`)

## 2026-10-04

- Give the API user a writable media directory so production can boot. (`41a9fc1`)
- more professional, modern, performance improve and security improve done (`4b16f24`)
- Pin Python dependencies in uv.lock so image builds stay reproducible. (`30b45be`)
- Add FAQ, shipping, and privacy page CMS APIs. (`d7dfb08`)
- more api created done (`ba26a0f`)

## 2026-10-03

- more modified (`8c7b454`)
- about page more api create done (`dbaee1c`)
- home page all section api create and integration done (`66efb66`)
- home page all section all api create done (`620cfad`)
- dashboad overview api created done (`d1b424d`)
- quantity, color added (`0df573c`)
- delivary status change (`62cdd47`)
- modified (`3fd1690`)
- Allow the mart storefront origin in production CORS. (`cb0fed1`)
- order system api modified (`29d6035`)
- order system complete (`f4eaedf`)

## 2026-10-02

- cart api crate done (`d9c318f`)
- products api created done (`74e6055`)

## 2026-09-28

- bruno file updated (`90604f4`)
- bruno file updated (`0df58a3`)
- project setup (`085d465`)
