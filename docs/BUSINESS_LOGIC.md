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
- Admin product update (`PATCH`) still uses the default envelope with English messages (status 422). See TODO.md.

## Products: drafts and published

- `published` defaults to `false`. A draft needs only a `name`.
- Publishing (create or update with `published: true`) requires:
  - a price, unless the product has variants,
  - a category,
  - a main image (an uploaded image or a gallery photo).
- Every storefront query filters `published = true`. Drafts never appear in public lists, search, detail, home sections or carts/orders.
- Limits: price 0–10,000,000; quantity 0–1,000,000; at most 100 variants; at most 8 badges.
- The main image falls back to the first gallery photo, never a video.

## Product media (gallery, video, YouTube)

Code: `app/services/image_storage.py`, `app/services/product_service.py`, `app/schemas/product.py`.

- Gallery holds at most 12 items. At most 12 uploaded images per request.
- Gallery item kinds: `image`, `video` (uploaded file), `youtube` (stored as an 11-character video id).
- Images: JPEG, PNG, WEBP or GIF, checked by file signature (magic bytes), max 5 MB.
- Videos: MP4 or WEBM, checked by extension and signature, max 50 MB each.
- YouTube: accepts a bare id or a `youtube.com` / `youtu.be` / `youtube-nocookie.com` link (`watch`, `shorts`, `embed`, `live`, `v`); anything else is rejected.
- Files are stored under the media root in folder `products` with a random UUID filename and served from `/media/products/<file>`. A replaced file always gets a new URL.
- New uploads are appended after the gallery items already in the payload, so after save the order is: existing items first, then new uploads.
- Videos and YouTube items may carry a custom `thumbnail` image (stored like a gallery photo, same type and size checks). Photos never keep one. Without it the storefront uses the YouTube still or the video's first frame.
- Thumbnail uploads use the `thumbnails` parts with `thumbnail_targets` (gallery item id, or `video:<n>` for a video uploaded in the same request). A target that is not a video/YouTube item is refused.
- Every media URL is unique (UUID filename), so a changed video, thumbnail or photo always gets a new URL and no cache can serve the old one.
- Media files owned by a product are deleted from disk when the product is deleted or when the file is no longer referenced after an update.

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
3. Delete the owned media files from disk.

- Past orders are kept: order items lose the product link (`ON DELETE SET NULL`) but keep their saved name and price.
- Cart lines, featured/showcase entries, badge links and variants are removed with the product (cascade).

## Bulk delete products

`DELETE /admin/products/bulk` (editor+), body `{"ids": [...]}`:

- Ids are de-duplicated. 1 to 100 ids per request.
- 422 errors: "Choose at least one product to delete" (empty), "Some product ids are not valid" (`details.invalid_ids`), "Delete at most 100 products at a time".
- Each product is deleted with the same steps as single delete and commits on its own. One failure does not stop the rest (partial success).
- Response: `requested`, `deleted`, `deleted_ids`, `skipped` (`reason: "not_found"`), `failed` (`reason: "error"`).

## Cart and orders

- At most 5 of one product in a cart line (`MAX_QTY`); variant/product minimum and maximum order limits apply.
- A product with options needs an option chosen before ordering.
- Stock refusals use a generic message that never reveals the remaining count.
- Order creation accepts an `Idempotency-Key` (8–80 letters, numbers, `_` or `-`).
- Delivery fees come from the delivery zones (district/area).
- Public order lookup does not expose the delivery address.

## Prices and discounts

- Each product has a **regular price** and a **base discount %**. The quantity-1 selling price is `round(regular × (1 − base/100))`, whole taka, half up.
- **Quantity tiers** add an extra % (on the regular price) for buying more pieces in one line: the highest tier with `min_quantity ≤ quantity` counts. Defaults: 2 → 0.25, 3 → 0.5, 4 → 0.75, 5 → 1, 6 → 1.25, 7 → 1.5, 8+ → 2.
- `total % = min(base + extra, max %, 99.99 %)`; a discount never reaches 100 %. Unit price = quantity-1 price − round(regular × (total − base)/100), so the quantity-1 price is always exactly the stored `price`. If the max % is below a product's base, the unit price is the regular price at the max %.
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
- Saving a product with `regular_price` (+ `base_discount_percent`) sets `price` and `compare_at_price`. Saving only `price`/`compare_at_price` keeps the saved base % when they are unchanged and clears it (derived) when they change. A base % above the max % is refused.

## Categories

- Categories form a tree with a maximum depth (`MAX_DEPTH`) and a database cycle guard.
- At most 1000 categories.
- A listing filtered by a hidden or missing category returns an empty list instead of leaking hidden products.

## CMS content

- Home sections (hero, categories, featured, showcase, promo, …), about, sustainability, shipping, privacy, FAQs, contact, blogs, site header/footer/contact are admin-edited and read publicly.
- Admin href fields reject script schemes (`javascript:` and similar).
- Blog and CMS writes name every invalid field in 422/409 errors.
