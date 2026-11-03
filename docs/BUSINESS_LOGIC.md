# Business logic

Rules enforced by the API, per feature. Code locations are given so the rule can be checked. Update this file whenever a rule changes.

## Roles and access

- Staff roles: `superadmin` > `editor` > `viewer` (`app/api/deps.py`, `require_role`).
- Admin writes need `editor` or higher. `viewer` can sign in but gets 403 on admin routers guarded by `require_editor`.
- Users and audit events need `superadmin`.
- Shoppers are anonymous. Guest carts use the `X-Cart-Token` header.

## Errors contract

- Default error body: `{"error": {"code", "message", "details"}}`.
- **Admin product create (`POST /admin/products`)** returns `{"errors": [{"field", "message", "fix"}]}` with Bengali text:
  - 400 for invalid fields (every invalid field is listed),
  - 409 for conflicts (for example a duplicate slug),
  - 500 for an unexpected failure (generic message, no internals).
- Admin product update (`PATCH`) still uses the default envelope with English messages (status 422), except a taken `slug`, which returns 409 `{"errors": [{"field": "slug", ...}]}`. See TODO.md.

## Products: drafts and published

- `published` defaults to `false`. A draft needs only a `name`.
- Publishing (create or update with `published: true`) requires:
  - a price, unless the product has variants,
  - a category,
  - a main image (an uploaded image or a gallery photo).
- Every storefront query filters `published = true`. Drafts never appear in public lists, search, detail, home sections or carts/orders.
- Limits: price 0–10,000,000; quantity 0–1,000,000; at most 100 variants; at most 8 badges.
- The main image falls back to the first gallery photo, never a video.

## Product SEO and slugs

- `seo_title` (≤120), `seo_description` (≤320), `seo_keywords` (≤500, comma separated, de-duplicated) are optional; empty means the storefront falls back to the title and description.
- The slug is generated on create; on update it may be changed (format `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤160, unique across products → 409 on field `slug`).
- A replaced slug is kept in `product_slug_redirects`, so `GET /products/by-slug/{old}` still returns the product (published only). A product taking a slug that is a redirect removes that redirect. Uniqueness is checked in the service; there is no DB constraint between `products.slug` and redirect slugs.
- Slug generation (new products only): Bengali letters are transliterated phonetically (`app/services/transliteration.py`; consonants carry an inherent "o" unless a vowel sign, hasanta or word end follows; Bengali digits → 0–9), then `python-slugify`. A title with nothing usable gives `product`; collisions get `-2`…`-99`, then `product-<random>`. Existing slugs are never regenerated.
- `updated_at` on public product cards and category tree nodes is the row's last change; the storefront uses it as sitemap `lastmod`.

## Uploaded media

Code: `app/services/image_storage.py`, `app/core/media_files.py`, `app/core/config.py`.

- Images are JPEG, PNG, WEBP, or GIF, checked by file signature, max 5 MB. Videos are MP4 or WEBM, checked by signature, max 50 MB. SVG, HTML, and any other type are rejected and nothing is stored.
- The stored name is a random id. The database value is always `/media/<folder>/<name>` (`products`, `banners`, `categories`, `reviews`, `about`, `sustainability`, `blogs`, `promo`, `home-media`, `footer`).
- When `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `MEDIA_PUBLIC_BASE_URL` are all set, the object key is `<folder>/<name>` in the bucket and `GET /media/<folder>/<name>` redirects to the public media URL. The object is stored with the matching image or video content type.
- When those five are empty, the file is written under the media root and served from disk. A partial set refuses to start.
- Deleting an owned `/media/<folder>/<name>` reference deletes that object in the bucket, or the file on disk when object storage is off. A reference outside that folder is left alone.

## Product media (gallery, video, YouTube)

Code: `app/services/image_storage.py`, `app/services/product_service.py`, `app/schemas/product.py`.

- Gallery holds at most 12 items. At most 12 uploaded images per request.
- Gallery item kinds: `image`, `video` (uploaded file), `youtube` (stored as an 11-character video id).
- Images: JPEG, PNG, WEBP or GIF, checked by file signature (magic bytes), max 5 MB.
- Videos: MP4 or WEBM, checked by extension and signature, max 50 MB each.
- YouTube: accepts a bare id or a `youtube.com` / `youtu.be` / `youtube-nocookie.com` link (`watch`, `shorts`, `embed`, `live`, `v`); anything else is rejected.
- Files use a random UUID filename under the `products` folder and are stored as in "Uploaded media" above. The saved path is `/media/products/<file>`. A replaced file always gets a new URL.
- New uploads are appended after the gallery items already in the payload, so after save the order is: existing items first, then new uploads.
- Videos and YouTube items may carry a custom `thumbnail` image (stored like a gallery photo, same type and size checks). Photos never keep one. Without it the storefront uses the YouTube still or the video's first frame.
- Thumbnail uploads use the `thumbnails` parts with `thumbnail_targets` (gallery item id, or `video:<n>` for a video uploaded in the same request). A target that is not a video/YouTube item is refused.
- Every media URL is unique (UUID filename), so a changed video, thumbnail or photo always gets a new URL and no cache can serve the old one.
- Media files owned by a product are deleted (bucket object, or disk file when object storage is off) when the product is deleted or when the file is no longer referenced after an update.

## Product badges

Code: `app/services/badge_service.py`, `app/schemas/badge.py`, `app/models/badge.py`.

- Admin-managed badges with a name (max 32 characters, unique), a slug (generated), a tone and an on/off switch (`is_active`).
- Tones: `primary`, `gold`, `dark`, `alert`, `soft`, `soft-gold`.
- A product can carry at most 8 badges, in the order chosen.
- Built-in system badges (Best Seller, New, Limited) cannot be deleted; switch them off instead.
- A badge that is on any product cannot be deleted (409); switch it off instead.
- The storefront shows only active badges.
- The legacy single `badge` field is kept in sync with the system badges for older clients.

## Delete a product

`DELETE /admin/products/{id}` (editor+):

1. Collect the product's media references.
2. Unlink its badges, delete the product and commit.
3. Delete the owned media files (from the bucket, or from disk when object storage is off).

- Past orders are kept: order items lose the product link (`ON DELETE SET NULL`) but keep their saved name and price.
- Cart lines, featured/showcase entries, badge links and variants are removed with the product (cascade).

## Bulk delete products

`DELETE /admin/products/bulk` (editor+), body `{"ids": [...]}`:

- Ids are de-duplicated. 1 to 100 ids per request.
- 422 errors: "Choose at least one product to delete" (empty), "Some product ids are not valid" (`details.invalid_ids`), "Delete at most 100 products at a time".
- Each product is deleted with the same steps as single delete and commits on its own. One failure does not stop the rest (partial success).
- Response: `requested`, `deleted`, `deleted_ids`, `skipped` (`reason: "not_found"`), `failed` (`reason: "error"`).

## Cart and orders

- Max pieces of one product (or one option) per order: the store-wide limit (Admin › Discounts, `pricing_settings.max_quantity`, default 10) or the product's custom `max_order_quantity`, which replaces it. Stock caps it further: the allowed maximum is min(limit, stock). Hard ceiling 1000 (`QUANTITY_CEILING`). The product minimum order quantity still applies.
- Over the limit, cart and order return "এই পণ্যটি এক অর্ডারে সর্বোচ্চ Nটি নেওয়া যাবে।"; the quote marks the line unavailable.
- A product with options needs an option chosen before ordering.
- Stock refusals use a generic message that never reveals the remaining count. The exposed maximum (`max_per_order`, variant/cart `max_quantity`) is min(limit, stock), so stock below the limit can be inferred from it.
- Order creation accepts an `Idempotency-Key` (8–80 letters, numbers, `_` or `-`).
- Delivery fees come from the delivery zones (district/area).
- Public order lookup does not expose the delivery address.

## Prices and discounts

- Each product has a **regular price** and a **base discount %**. The quantity-1 selling price is `round(regular × (1 − base/100))`, whole taka, half up.
- **Quantity tiers** give a discount % on the line total for buying more pieces in one line: the tier with the highest `min_quantity ≤ quantity` counts (a quantity with no tier of its own uses the nearest lower tier; below the first tier, or with no tiers, there is no quantity discount). Defaults: 2 → 0.25, 3 → 0.5, 4 → 0.75, 5 → 1, 6 → 1.25, 7 → 1.5, 8+ → 2.
- Line price (since 2026-11-02): `total = selling price × quantity`; `final = ceil(total − total × tier % / 100)`, always rounded **up** to whole taka; `discount = total − final`. Example: ৳700 × 2 at 0.25 % = 1396.5 → ৳1,397; × 3 at 0.75 % = 2084.25 → ৳2,085; × 4 at 1 % = ৳2,772 exactly. Worked out in integers (percent in hundredths), so an exact result is never bumped up by float error (`pricing_service.discounted_total`).
- The tier % is capped so `base + tier ≤ min(max %, 99.99 %)`; a discount never reaches 100 %. `total_discount_percent` = base + tier (capped) is a summary only. If the max % is below a product's base, the selling price is the regular price at the max % and no tier applies.
- API fields: `unit_price` = quantity-1 selling price (no longer reduced by the tier); `line_total` = the rounded-up final; `subtotal` = sum of line totals. Each line is rounded on its own (no order-level rounding).
- Store settings (`pricing_settings`, Admin › Discounts): tiers on/off, max %, tier list. Turning tiers off affects products on store-wide tiers only; products with custom tiers keep them. The max % applies to every product. No settings row = defaults (on, 90 %, default tiers).
- Per product: `tier_mode = global` (store tiers) or `custom` (its own `tiers`).
- Field mapping:

  | Concept | Column / field |
  | --- | --- |
  | Regular price | `compare_at_price` when it is above `price`, else `price` (API: `regular_price`) |
  | Quantity-1 selling price | `price` |
  | Base % | `base_discount` (hundredths, 2800 = 28 %); NULL = derived from price/compare_at (older rows). API: `base_discount_percent` |
  | Variants | always derived from the variant's price/compare_at; product tiers apply |
  | Order snapshot | `order_items.regular_price`, `base_discount`, `quantity_discount`, `total_discount` (hundredths) + `unit_price`, `line_total` |

- One function prices everything (`pricing_service.price_product`): product page block, cart, quote and order. Orders store the snapshot, so later rule or price changes never change a placed order.
- Product cards (list endpoints) show the discount from `price` and `compare_at_price`: struck-through regular price and `-X%` only when `compare_at_price > price`. Quantity tiers are never shown on cards.
- Variant products: `products.price` / `products.compare_at_price` always equal the cheapest active variant's (lowest `sort_order` on a tie; all variants when none is active). Every save re-syncs them from the variants, so `price` / `compare_at_price` sent for a variant product are ignored (the dashboard sends `compare_at_price: null` for them). Migration 0090 repaired rows saved before this rule (2026-11-03).
- Saving a product with `regular_price` (+ `base_discount_percent`) sets `price` and `compare_at_price`. Saving only `price`/`compare_at_price` keeps the saved base % when they are unchanged and clears it (derived) when they change. A base % above the max % is refused.

## Categories

- Categories form a tree with a maximum depth (`MAX_DEPTH`) and a database cycle guard.
- At most 1000 categories.
- A listing filtered by a hidden or missing category returns an empty list instead of leaking hidden products.

## CMS content

- Home sections (hero, categories, featured, showcase, promo, …), about, sustainability, shipping, privacy, FAQs, contact, blogs, site header/footer/contact are admin-edited and read publicly.
- Admin href fields reject script schemes (`javascript:` and similar).
- Home showcase rows (`gadgets` = Trending, `fashion`) are curated lists: admin `choices` and added/edited items must be published products from any category (422 "Choose a published product"; an edit may keep its current product if it was hidden later). At most 12 per row, no duplicates. Public `GET /home/showcase` returns only published pinned products.
- Home media section (`home_media`, one row, `app/services/home/media_service.py`): `media_type` is `image`, `video` or `youtube`. Public `GET /home/media` returns null unless active with a heading and usable media (image needs `image_src` + `media_alt`, video needs an MP4/WEBM `video_src`, YouTube needs the id). `youtube_url` accepts watch / youtu.be / shorts / embed links or an id (same `youtube_id()` check as products) and is stored as the id. The button is shown only when `cta_enabled` with a label and a link that is a site path (`/…`, no `//` or `..`) or `https://`. On save only the chosen type's fields are kept (image: no video/YouTube/thumbnail; video: no image/YouTube; YouTube: no image/video) and replaced or dropped files under `/media/home-media/` are deleted. Uploads: images 5 MB (JPEG/PNG/WEBP/GIF by content), videos 50 MB (MP4/WEBM by content). Public and admin responses are `Cache-Control: no-store`.
- Blog and CMS writes name every invalid field in 422/409 errors.
