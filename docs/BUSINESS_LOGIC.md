# Business logic

Rules enforced by the API, per feature. Code locations are given so the rule can be checked. Update this file whenever a rule changes.

## Roles and access

- Staff roles: `superadmin` > `editor` > `viewer` (`app/api/deps.py`, `require_role`). The `roles` table also keeps the legacy slugs `super_admin`, `admin`, and `staff` so an old `users.role` value satisfies `fk_users_role_roles`. Those three do not grant admin access and are not system roles. Migration `0108` inserts them, plus any other value already stored on `users.role`, with `ON CONFLICT DO NOTHING`. Existing role rows and user rows are not updated.
- Admin writes need `editor` or higher, or a dynamic grant of `read_write` or `full` on that module. A built-in `viewer` with only `read_only` gets 403 on writes.
- These modules were editor-only on every method, including GET: dashboard, products (including cost price), inquiries, CMS, carts, and the order desk. A built-in `viewer` with only `read_only` still gets 403 there. `read_write` or `full` opens the module. `editor` and above still pass with `read`. `GET /admin/orders/new` stays open to a viewer who can read orders.
- A viewer may read reports, inventory, coupons, delivery rates, pricing settings, and reviews.
- Users and audit events need `superadmin`.
- Shoppers may browse and check out as guests (guest carts use the `X-Cart-Token` header) or sign in with a `customer` role account (`Authorization: Bearer …`) for persistent account carts, order history, notifications, and verified product reviews.

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
- **Turnstile (public checkout only).** `POST /api/v1/orders` reads `turnstile_token` from the JSON body (optional in the schema, blank becomes missing, longer than 2048 characters is 422). The `X-Turnstile-Token` header is not read. When `TURNSTILE_SECRET_KEY` is set, a new order is placed only after `https://challenges.cloudflare.com/turnstile/v0/siteverify` returns `success: true`. The request sends the secret, the token, and `remoteip` from `CF-Connecting-IP` when that header is an IP. The timeout is 5 seconds. A missing token, a rejected token, or a siteverify failure is 400 `turnstile_failed` with message `নিরাপত্তা যাচাই ব্যর্থ হয়েছে, আবার চেষ্টা করুন`. The secret and the token are not logged. A replay of an idempotency key that already has an order returns that order and does not call siteverify. Quote, lookup, and every admin order route, including offline create, do not check a token. When the secret is empty and `ENVIRONMENT` is not `production`, the check is skipped and a debug line is logged. When `ENVIRONMENT` is `production` and the secret is empty, public checkout is refused with the same 400 and an error log that names `TURNSTILE_SECRET_KEY`. Set the secret before a production deploy.
- Order and lookup phone: Bangladesh mobile `01[3-9]XXXXXXXX`, also written as `880…` or `+880…`, with spaces, dashes, dots, brackets or Bengali digits; always stored and compared as `01XXXXXXXXX`.
- **Meta Purchase (done, not live).** A newly committed online order schedules one Conversions API `Purchase` after the commit. An offline order does not. Replaying the idempotency key, or changing status, does not send it again. The call runs in the background with a 5 second timeout and up to 3 attempts (network errors, HTTP 429, and HTTP 5xx, with a short backoff). Any failure is logged with the order number only and the shopper still gets the successful order.
- The event id is `purchase_` plus the order number (`IM-…`), returned as `analytics_event_id`. `order_number` in the response is that same number (`number` is unchanged). The browser Pixel must use this id.
- Optional request `tracking` (`fbp`, `fbc`, `event_source_url`) is not stored. A missing object, a non-object, a non-string, or a string longer than 500 characters is ignored. Unknown keys inside `tracking` are ignored.
- The payload value is the order grand total (items plus delivery, after any coupon), currency `BDT`. When the order has `coupon_code`, `custom_data.coupon` is that code. `content_ids` and `contents` use the product id. `contents[].item_price` is the line's quantity-1 selling price. `num_items` is the sum of those quantities. A line with no product id is left out (new orders always have one).
- User data sent to Meta: SHA-256 of the phone as `8801XXXXXXXXX` (spaces, dashes and `+` removed; `01XXXXXXXXX` gains `88`; anything else omits `ph`); SHA-256 of the trimmed lower-case email when there is one; SHA-256 of the first name (`fn`) and, when the name has more than one word, the last name (`ln`), lowercased with punctuation removed; SHA-256 of the district (`ct`) after trim, lowercase, and removal of punctuation and spaces; SHA-256 of country `bd`; SHA-256 of the customer id when the order has one, otherwise SHA-256 of that normalized phone (`external_id`). `client_ip_address` is not hashed: `CF-Connecting-IP`, else the first `X-Forwarded-For` entry, else the socket client host. `client_user_agent` is the `User-Agent` header, not hashed. `fbp` and `fbc` are the cookie values, not hashed. Street address, area, and notes are not sent. The access token, raw phone, email, name, IP, and user agent are not logged.
- Sending is off when `META_PIXEL_ID` or `META_CAPI_TOKEN` is empty. `META_TEST_EVENT_CODE`, when set, is included so the event shows under Meta Test events. The Graph API version is `v21.0` in code, not an environment variable.
- **Telegram (done, not live).** A newly committed order can notify every chat in `TELEGRAM_CHAT_IDS` after the commit. Replaying the idempotency key does not send again: the sender is queued only after `UPDATE orders SET telegram_notified_at = now() WHERE id = ? AND telegram_notified_at IS NULL` changes a row. That update is the claim. It runs in the request, before the HTTP task, so two workers cannot both send. The HTTP call has a 5 second timeout and up to 3 attempts (network errors, HTTP 429, and HTTP 5xx). On 429 the wait is Telegram's `retry_after` (capped at 30 seconds). Any failure is logged with the order number only. The bot token is not logged. The shopper still gets the order.
- The message is Telegram HTML. Text is escaped (`&`, `<`, `>`). It includes the order number, customer name, phone, area (not the street address), each product title with its quantity, the total, and the payment line. COD shows the amount still due (`due_amount`, or the total when that column is NULL). Bangla QR shows advance paid (`advance_amount`) and remaining (`due_amount`). When `ADMIN_BASE_URL` is set, the message links to `{ADMIN_BASE_URL}/admin/orders/{id}` — the same UUID path the admin order list uses. An empty base URL omits the link.
- Empty `TELEGRAM_BOT_TOKEN` or an empty chat list sends nothing and leaves `telegram_notified_at` NULL. Checkout is unchanged.
- **Cancel alerts** (`TELEGRAM_NOTIFY_ORDER_CANCELLED`, default off) send only when an online order's status change actually becomes `cancelled`. An offline order does not send one. The status compare-and-set already allows that once. **Low stock** (`TELEGRAM_NOTIFY_LOW_STOCK`, default off) sends when a product's on-hand `quantity` goes from above `LOW_STOCK_THRESHOLD` (5, the same cutoff as the stock report; there is no per-product reorder column) to 5 or below. A later sale that stays at or below 5 does not send again. NULL quantity (made to order) does not. The check runs on an order claim and on an inventory purchase, adjustment, or import that changes the product's quantity. Editing quantity on the product form does not. Stock put back by cancel or return does not. The alert is queued only after that transaction commits.
- Delivery fees come from the delivery zones (district/area).
- Public order lookup does not expose the delivery address.
- **Status (orders desk, done, not live).** Stored values stay `new`, `confirmed`, `packed`, `shipped`, `delivered`, `cancelled`, `returned`. Rows from before `packed` existed are not rewritten. `confirmed` is the ready-to-pack queue. Allowed moves, enforced on every single and bulk change: `new` to `confirmed` or `cancelled`; `confirmed` to `packed` or `cancelled`; `packed` to `shipped` or `cancelled`; `shipped` to `delivered` or `returned`; `delivered` to `returned`. `cancelled` and `returned` are final. An illegal move is 409 `conflict` and names the allowed targets. A compare-and-set miss is 409 "This order was changed by someone else. Reload and try again."
- Cancel and return put the held stock back once. Cancel also marks the coupon redemption cancelled, so the use comes back. Return keeps the redemption. Both paths are `order_service.change_status`, including bulk.
- `delivered_at` is set the first time the status becomes `delivered`, and `returned_at` the first time it becomes `returned`. The clock is timezone-aware UTC. A later transition does not replace either value. Going to `returned` after `delivered` keeps `delivered_at` and sets `returned_at`. Admin order reads return both; public lookup does not.
- **Origin.** `orders.origin` is `online` or `offline`. It is not `orders.source` (`cart` or `direct`) and not `orders.channel`. Existing rows and checkout stay `online`. An offline order is entered by staff, stores `source = direct` and `channel = offline`, and sets `ordered_at` to the start of `order_date` in Asia/Dhaka (or now when the date is omitted). Online checkout leaves `ordered_at` NULL, so it still counts on `created_at`.
- **Offline money.** The server prices every line. An omitted `unit_price` uses the current selling price, including quantity tiers. A set `unit_price` charges that whole-taka price times quantity and still snapshots the catalog regular price and percents. `manual_discount` and `delivery_charge` are the only other client money fields, and both are validated. `total = subtotal − coupon_discount − manual_discount + shipping`, never negative, and the discount cannot exceed the merchandise. `paid_amount` is 0 through `total`. `due_amount = total − paid_amount`. Offline orders do not take a coupon. Online checkout stores `manual_discount = 0`.
- **Payments.** Checkout stays `cod` or `bangla_qr`. Offline adds `cash`, `bkash`, `nagad`, `card`, `due`. `payment_status` is `unpaid` when the collected amount is 0, `paid` when it covers the total, otherwise `partial`. Older Bangla QR rows keep `paid_amount` 0 and are read as paid `advance_amount`. Older COD stays unpaid. The migration does not write `paid_amount`.
- **Offline tracking.** Creating an offline order does not schedule Meta Purchase, the Telegram new-order message, or a cancel Telegram. There is no server GA event. A low-stock Telegram can still fire from the stock claim; that is an inventory alert. The admin client must not fire a browser Purchase or GA event when `origin` is `offline`. `analytics_event_id` stays on `OrderRead` because the field is required.
- **Call status and duplicates.** `call_status` is `not_called`, `confirmed`, `no_answer`, or `fake`. Customer history on an order is every order with the same phone: `total_orders` (including this one), `delivered`, and `returned_cancelled` (returned plus cancelled). `duplicate_warning` is true when another order with that phone has `created_at` within 24 hours of this order's `created_at`. Backdating `ordered_at` does not hide that.
- **Edits.** While status is `new` and stock is still held, `PUT /admin/orders/{id}/items` replaces the lines. The server adjusts stock by the quantity delta, recomputes totals, and keeps `coupon_discount`. A discount larger than the new merchandise, or a collected amount larger than the new total, is 422. After confirm, item edits are 422. Courier, tracking, notes, and call status can change on `PATCH` and each change is logged.
- **Activity.** `order_activities` records who did what: created, status change, call status, item edit, courier edit, print, note, and the customer-message result. Rows are inserted, never updated. `audit_events` still records `ORDER_STATUS_CHANGED`.
- **Print.** `printed_at` is the latest print. Reprint is allowed and each print is logged. Print data is a read and does not set `printed_at`.
- **Invoice id.** There is no invoice sequence and no invoice column. Print data derives `invoice_id` as `INV-` plus the eight hex characters of the order number (`IM-AB12CD34` → `INV-AB12CD34`). The same number always yields the same id. `order_number` on that payload is the order number.
- **Estimated delivery.** Print data computes a date and does not store it. The order date is `ordered_at` in Asia/Dhaka when set, otherwise `created_at` in Asia/Dhaka. Inside Dhaka and Dhaka-suburban add `DELIVERY_DAYS_INSIDE_DHAKA` (default 2). Outside Dhaka adds `DELIVERY_DAYS_OUTSIDE_DHAKA` (default 5). Both are 0–60. Changing them changes the next print, including for old orders, and does not change stored dates or totals.
- **Public tracking.** `POST /orders/lookup` is the only status lookup. The caller sends the order number or the courier tracking id, and the phone. Both pieces are required. One without the other, or both identifiers together, is 422. A wrong phone and an unknown id return the same 404. Tracking match is exact and case-insensitive. Several orders with the same tracking id and phone return the newest. The body has status, a timeline of known status times (no actor), courier, tracking, an items summary (`variant_label` plus the existing line fields), totals, and `due_amount` as the cash still due. It still has no street address. The route keeps `RATE_LIMIT_ORDER_LOOKUP` (default 30/minute) per client address.
- **Customer messages.** A real move to `confirmed` or `shipped`, on one order or in a bulk update, can queue a short Bengali message for that phone. Online and offline are both included. The status response does not wait on it and does not fail when the send fails. The same status is claimed once (`customer_sms_confirmed_at` or `customer_sms_shipped_at`, nullable, left NULL when the flag is off). A later edit does not send that status again. The result is an inserted `order_activities` row, action `customer_message`, with status, result (`logged`, `skipped`, or `failed`), and provider. No phone, message body, or token is stored there. Confirmed text has the order number, total, amount still due, and `{ADMIN_BASE_URL}/order-status?number={number}` when the base URL is set. Shipped text has the courier, the tracking id, and that link. Empty courier, tracking, or base URL drops that piece. The phone is not in the text. `CUSTOMER_SMS_ENABLED` defaults off. `CUSTOMER_SMS_ON_CONFIRMED` and `CUSTOMER_SMS_ON_SHIPPED` default on and do nothing until the master flag is on. `CUSTOMER_SMS_PROVIDER` is `log` or `noop` only. Nothing is delivered to a handset. The SSL Wireless token and sender id are not read.
- New checkout orders store `orders.channel = "website"`. Orders placed before migration 0094 stay NULL. There is no database default, so a read of an old row is NULL. `orders.source` is still `cart` or `direct` and is not the channel.
- Each new line stores `order_items.unit_cost`, a copy of `products.cost_price` at order time (NULL when the product has no cost). A later change to the product cost does not change the line. Lines placed before migration 0094 stay NULL. The value is not estimated from the current cost. It is not on any public order or product response.
- Migration 0092 fills those columns only from the earliest `audit_events` row (`ORDER_STATUS_CHANGED`, `metadata.to`) for orders that are currently delivered or returned. There is no separate status-history table. No recorded event means NULL. `orders.created_at` and `orders.updated_at` are never used as a substitute.

## Bangla QR payment

- One Bangla QR image for the whole store, in `payment_settings` (slug `main`, `bangla_qr_src`). Admin uploads, replaces (old file deleted) or deletes it at `admin/site/payment`. The public `GET /site/payment` is `no-store`, so a change shows at once.
- No QR set → `bangla_qr_enabled: false`, the quote has no `bangla_qr_options`, and a `bangla_qr` order is refused with 422 "Bangla QR পেমেন্ট এখন চালু নেই। ক্যাশ অন ডেলিভারি বেছে নিন।".
- Split (server only, from the order total incl. delivery, after any coupon and after free delivery has set shipping to 0): `advance = ceil(total × percent / 100)` in whole taka, `due = total − advance` (cash on delivery). Percent must be 25, 50, 75 or 100. Example: total 1001 → 25% = 251 + 750 due. A ৳1000 order with ৳100 off and ৳70 delivery is total 970 → 25% = 243 + 727 due.
- `bangla_qr` needs a transaction ID / sender number (`payment_reference`); COD must not send a percent or reference. COD orders store advance 0, due = total. Orders placed before migration 0091 have `due_amount` NULL and read as due = total.
- The payment is not verified automatically: staff check the reference against the received payment before confirming the order.

## Prices and discounts

- Each product has a **regular price** and a **base discount %**. The quantity-1 selling price is `round(regular × (1 − base/100))`, whole taka, half up.
- **Cost price** (`products.cost_price`, numeric, null or `>= 0`) is what the shop paid. It is read and written only by the admin product API (create, update, get, list), editor or above. Public product list, detail, search, category lists, and home product cards omit it. A change is stored on the product price audit row with the old and new value.
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

## Coupons

Code: `app/services/coupon_service.py`. Done, not live until migration 0096 is applied.

The shopper sends only a code. The server ignores any client discount, total, or `coupon_discount` (those fields are unknown and the request is 422). A blank code is no coupon.

- **Order of money.** Line totals already include the quantity discount. The coupon is applied after that. `subtotal` stays the sum of line totals. `coupon_discount` and `manual_discount` are taken off that subtotal, then shipping is added. `total = subtotal − coupon_discount − manual_discount + shipping`, and it is never negative. Online checkout has `manual_discount` 0, so an online total is unchanged. The discount never exceeds the eligible merchandise.
- **Percent.** Same round-up-the-payable rule as a quantity discount (`pricing_service.discounted_total`), then `max_discount` if it is set, then the eligible cap. Example: 10% of ৳1000 is ৳100. 10.5% of ৳1000 keeps ৳895 (the payable is rounded up) so the discount is ৳105. 50% of ৳1000 with `max_discount` 120 is ৳120.
- **Fixed.** Whole taka, capped by the eligible merchandise. ৳5000 off a ৳1000 line is ৳1000, and the total is the delivery charge only.
- **Free delivery.** Sets `shipping` to 0. A coupon can be free delivery only (`value` 0). Then `coupon_discount` is 0, not NULL. NULL means no coupon was used, including every order from before 0096.
- **Minimum.** `min_order_amount` is the merchandise after the quantity discount and before the coupon and before shipping. The Bangla message names that minimum in ৳ with Bengali digits.
- **Window.** `starts_at` and `ends_at` are inclusive. A clock with no timezone is Asia/Dhaka. The row stores the UTC instant. NULL start means already started. NULL end means it does not expire. Status for the admin list: inactive if `is_active` is false; otherwise scheduled if the start is in the future; otherwise expired if the end is in the past; otherwise active.
- **Limits.** `usage_limit_total` and `usage_limit_per_phone` count redemptions whose `cancelled_at` is NULL. The phone is stored as `01XXXXXXXXX`, the same normalisation as an order. On order create the coupon row is locked (`SELECT … FOR UPDATE` on PostgreSQL) and the count is taken in that transaction, so concurrent orders cannot pass the limit. SQLite tests do not take that lock.
- **First order.** The phone must have no earlier order whose status is not `cancelled`. Delivered, returned, and still-open orders all block it. A cancelled order does not, so the phone can use the coupon after a cancellation. On PostgreSQL the check also takes `pg_advisory_xact_lock(hashtext(phone))`. A coupon order and a non-coupon order for the same phone can still both commit if they race; two uses of the same coupon cannot.
- **Restrictions.** Empty product and category lists mean the whole cart. Otherwise the discount covers only lines whose product is listed or whose category is listed or is a descendant of a listed category. No such line is `coupon_not_eligible`.
- **Quote.** Optional `coupon_code`. Optional `phone`: when it normalises, the per-phone limit and the first-order rule are checked. When it is omitted, those two are checked only at order create. An invalid code does not fail the quote. `coupon` is null when no code was sent, or `{ code, valid, discount, free_delivery, error_code, message }`.
- **Create.** The code is re-checked after stock is claimed and before the order row is inserted. A failure raises 422 and the stock claim rolls back. The order stores `coupon_code` and `coupon_discount`. The redemption is inserted in the same transaction.
- **Cancel and return.** Cancel (the status change in `order_service.change_status`, including a bulk move) sets the redemption `status` to `cancelled` and sets `cancelled_at`. The use comes back. A return does not. The discount was already given, `delivered_at` stays, and the sale stays on the delivery day, so the redemption stays counted. There is no delete of a coupon that has ever been redeemed; turn `is_active` off. This API does not offer delete at all.

Customer-facing codes and messages:

| `error.code` | Message |
| --- | --- |
| `coupon_not_found` | এই কুপন কোডটি পাওয়া যায়নি। বানানটা আবার দেখুন। |
| `coupon_inactive` | এই কুপনটি এখন বন্ধ আছে। |
| `coupon_not_started` | এই কুপনটি এখনো চালু হয়নি। |
| `coupon_expired` | এই কুপনের মেয়াদ শেষ হয়ে গেছে। |
| `coupon_min_amount` | এই কুপনটি কমপক্ষে ৳{minimum}-এর অর্ডারে ব্যবহার করা যাবে। |
| `coupon_usage_limit` | এই কুপনটি ব্যবহারের সর্বোচ্চ সীমায় পৌঁছে গেছে। |
| `coupon_phone_limit` | এই মোবাইল নম্বরে এই কুপনটি আর ব্যবহার করা যাবে না। |
| `coupon_first_order_only` | এই কুপনটি শুধু আপনার প্রথম অর্ডারে ব্যবহার করা যাবে। |
| `coupon_not_eligible` | আপনার কার্টে এই কুপনের জন্য কোনো পণ্য নেই। |

On a quote those fields are `coupon.error_code` and `coupon.message`. On order create they are `error.code` and `error.message` in the usual envelope, status 422.

## Inventory ledger

Code: `app/services/inventory_service.py`, `app/services/inventory_excel.py`, `app/models/inventory.py`.

On-hand stock stays on `products.quantity` or, when the product has options, on `product_variants.quantity`. The ledger records every change. It does not replace those columns.

- **Suppliers** have a name, phone, address, and note. Phone is stored as typed (it is not forced into the shopper `01…` format).
- **Purchases** are insert-only. One purchase has a supplier, a date, and an invoice number. Each line is a product, or a variant when that product tracks stock per option, plus a quantity and a unit cost. Saving a purchase adds the quantity to that stock bucket and writes a `purchase` movement in the same transaction.
- **Weighted average cost** updates `products.cost_price` (and `product_variants.cost_price` when `variant_id` is set) when a purchase is saved. The previous count is the bucket being received: the product quantity, or that variant's quantity. Other variants are not part of the average. `cost_price` on the product and on the variant are each updated independently using the same weighted-average formula:
  - No previous `cost_price`, or previous stock is NULL or `<= 0`: the new cost is the incoming unit cost.
  - Otherwise `(old stock × old cost + incoming qty × incoming unit cost) ÷ (old stock + incoming qty)`.
  - Both costs are rounded half up to 2 decimal places before the division, and the result is rounded half up to 2 decimal places. Example: 1 on hand at 1.00 plus 1 at 1.01 → 1.005 → 1.01.
  - A NULL quantity (made to order) is not turned into a number. The purchase is still recorded and the cost becomes the incoming unit cost.
  - The product row is locked (`SELECT … FOR UPDATE`) before the count and the cost are read, so a second purchase waits and then weighs against the updated figures.
- **Stock movements** are insert-only. There is no update or delete endpoint. The service refuses an ORM update or delete. On PostgreSQL a trigger rejects DELETE and any change to the quantity, type, cost, note, or time. Deleting a product, variant, order, purchase, import batch, or user may only null that foreign key; the movement row stays. A correction is a new movement. `quantity` is signed: sale is negative; purchase, opening, cancel, and return are positive; an adjustment is the difference. A cost-only import uses 0 and does not change the count.
- **Orders.** When `_claim` actually decreases a count, it stages a `sale` movement. The row is inserted in that same transaction after the order id exists, before commit. A failed order rolls the stock change and the movement back together. `_restore` writes `cancel` when the new status is `cancelled` and `return` when it is `returned`, and only when the count was a number (the same rows the stock update touches). Delivered does not put stock back. A second cancel does not write a second movement. Unlimited stock (quantity NULL) does not write a sale or a reversal, because the count does not change.
- **Adjustments** (damaged, lost, count correction) need a reason. Editor or above. The count cannot go below zero. A product or variant with no count (NULL) is refused.
- **Opening stock** (`POST /admin/inventory/opening-stock` or `python -m scripts.opening_stock`) writes one `opening` movement per product, or per variant when stock is per option, using the current count. It does not change the count. Made-to-order rows are skipped. Running it again adds nothing. A partial unique index blocks a second opening for the same product or variant.
- **Excel (.xlsx).** Exports: products and stock, purchases, movements, each filterable by date. Imports: purchases, opening stock, stock count, and cost price. Each import type has a blank template. Import is two steps: a preview lists every row as valid or names what is wrong; confirm then saves the valid rows in one transaction. Invalid rows are not saved. Products are matched by `product_id`, `variant_id`, or `sku` only, never by name. Imports add movements or purchases; they do not overwrite old ones. A stock count becomes an adjustment for the difference between the counted quantity and the current count (zero difference saves nothing). An opening-stock row must equal the current count. The same file (SHA-256 of the bytes) imported again is refused until `confirm_duplicate` is sent. Files must be `.xlsx`, at most 2 MB and 2,000 data rows. Exports stop at 20,000 rows.
- Cost and unit cost are admin-only. They are not on any public or storefront response.

## Sales reports

Code: `app/services/report_service.py`, `app/services/shop_sql.py`. The dashboard overview (`dashboard_service.overview`) uses the same SQL style.

Dates are inclusive Asia/Dhaka calendar days. The window is half-open: from 00:00 on `from` through 00:00 on the day after `to`. Presets: `today`, `7d` (last 7 inclusive days ending today), `this_week` (Monday through today), `this_month` (the 1st through today), `last_month` (the whole previous calendar month), `this_year` (Jan 1 through today). A preset and a from/to pair cannot be used together. `from` after `to` is refused. The longest range is 366 days. Optional `product_id`, `category_id` (that category and its descendants), `supplier_id`, `channel`, `origin` (`online` / `offline`), and `profit_filter` (`all` / `profit` / `loss` / `unknown_cost`) narrow reports. A channel filter does not match an order whose channel is NULL, including old orders and `channel=website`.

Every total is a SQL aggregate. Python only turns those totals into a ratio (margin, return rate, net sales) and fills empty chart days. Order rows are not loaded.

- **Sales** count an order on `delivered_at`, not on `created_at`. Returned orders (`status = 'returned'`) are excluded from realized sales, units sold, shipping, COGS, profit, product sales, trend, and 30-day no-sale checks, while `delivery_report` and `product_report` continue reporting returned counts and return value separately.
  - Order count: realized delivered orders (`status != 'returned'`) in the window.
  - Units sold: sum of line quantities on those orders.
  - Gross sales: sum of `coalesce(regular_price, unit_price) × quantity`.
  - Discount: gross minus the sum of `line_total` (the list-price discount and the quantity discount), plus the coupon share and the staff `manual_discount` share. When `regular_price` is NULL, only the quantity discount and those order discounts remain. `coupon_discount` on the response is the coupon share only and `manual_discount` is the staff manual-discount share only (both are included inside `discount`). A NULL `orders.coupon_discount` counts as 0. `manual_discount` is 0 on every order from before the orders desk, so those reports do not move.
  - Delivery charge: sum of `orders.shipping`, once per realized delivered order. A product or category filter still counts the whole order's delivery charge, not a share of it. Free delivery is already shipping 0; it is not added again as a discount.
  - Net sales: merchandise (`line_total`) plus delivery minus the coupon share and the `manual_discount` share, which is gross minus discount plus delivery. With no product, category, or channel filter this equals the sum of `orders.total` across realized delivered orders.
  - A product or category filter keeps that filter's share of the coupon and of `manual_discount`: `round(discount × matching line_total ÷ order merchandise)`, half up, per order. The product report rounds per line instead, so a filtered product total can differ from the sales total by a taka.
- **Profit** uses only realized delivered lines (`status != 'returned'`) that have `unit_cost`. Revenue is the sum of those lines' `line_total` minus that line's share of the coupon and of `manual_discount`. Delivery is not included. Cost is `quantity × unit_cost` (where `unit_cost` snapshots `variant.cost_price` if set on the variant, else `product.cost_price`). Profit is revenue minus cost. `loss_amount` is the SQL sum of absolute negative margins across realized known-cost lines sold below cost (`net_line_revenue < quantity × unit_cost`). Margin is profit ÷ that revenue × 100, half up to 2 decimals, and NULL when that revenue is 0. A line with no `unit_cost` is counted separately (`unknown_cost_lines`, `unknown_cost_units`, `unknown_cost_revenue`) and is not treated as zero cost. Its revenue is also net of its discount share. Profit and margin are NULL when every line in the window has an unknown cost.
- **Profit & Loss (`GET /admin/reports/profit-loss`)** combines realized sales waterfall (`gross_sales`, `product_discount`, `coupon_discount`, `manual_discount`, `delivery_charge`, `net_realized_sales`), `returned_order_value`, COGS (`total_cost`), `gross_profit`, `loss_amount`, `net_profit`, `margin_percent`, unknown-cost totals, and collections (`collected_amount` + `due_amount` across realized delivered orders). Collected taka uses `paid_amount` when `> 0`, full `total` for settled delivered `cod` orders with `paid_amount = 0`, or `advance_amount` for legacy `bangla_qr` orders with `paid_amount = 0` (capped at `total`), and `due_amount = max(total - collected, 0)`.
- **Products (`GET /admin/reports/products`)** list one row per product: `slug`, `sku`, `category_name`, `supplier_id`, `supplier_name`, `units_sold`, `avg_selling_price`, `unit_cost_avg`, `current_cost_price`, `current_stock`, `stock_value`, `revenue` (`line_total` minus that line's coupon and `manual_discount` share), `cost`, `profit`, `is_loss` (`profit < 0`), `margin_percent`, `return_count`, `returned_units`, `return_value`, and `unknown_cost_units`. Supports SQL-level `profit_filter` (`profit` / `loss` / `unknown_cost`) and `sort` (`revenue`, `profit`, `margin`, `units_sold`, `cost`, `stock_value`). Units, revenue, and cost count only realized delivered orders (`status != 'returned'`) whose `delivered_at` is in the window.
- **Channel & Payment Breakdown (`GET /admin/reports/channels`)** splits realized delivered orders, units, net sales, COGS, profit, margin %, collected, and due by `origin` (`online` vs `offline`) and by `payment_method` (`cod`, `bangla_qr`, `cash`, `bkash`, `nagad`, `card`, `due`).
- **Supplier Performance (`GET /admin/reports/suppliers`)** aggregates per supplier: `linked_products_count`, `purchase_count`, `total_purchased_units`, `total_purchase_spend` (by `Purchase.purchased_on` inside the Dhaka date window), realized `units_sold`, `sales_revenue`, `cogs`, `net_profit`, `margin_percent`, `current_stock_units`, and `current_stock_value`.
- **Single Product Performance Analytics (`GET /admin/products/{product_id}/analytics`)** returns current stock/retail valuation, lifetime and last-30-Dhaka-days sales/COGS/profit/loss/margin/returns aggregates, and the 20 latest `StockMovement` entries for the Admin Product View page.
- **Offline orders business-date alignment, customer linking & payments:** `POST /admin/orders/offline` accepts optional `initial_status` (`new`, `confirmed`, `delivered`) and `mark_delivered: bool`. When created as `delivered`, `delivered_at` is set to `ordered_at` (the chosen business date, or now when omitted); when an offline order with `ordered_at` transitions to `delivered` later, `delivered_at` also defaults to `ordered_at` (when still NULL) so backdated counter sales land on their exact business date in all reports. Offline order creation also links `Order.user_id` automatically when a registered customer matches `phone`. Due/partial payments can be collected incrementally via `POST /admin/orders/{id}/payments` (rejecting cancelled/returned orders or overpayment) or set directly via `PATCH /admin/orders/{id}` (`paid_amount`), always recomputing `due_amount = total - paid_amount` and writing a `payment_updated` activity row.
- **Optional product supplier:** `products.supplier_id` (nullable FK to `suppliers.id ON DELETE SET NULL`) is admin-only (never exposed on public storefront endpoints), validated as non-deleted on create/update, clearable with `null`, and filterable via `GET /admin/products?supplier_id=...`.
- **Admin-Only Safe Deletion & Reconciliation (`RequireSuperadmin`):** Only `superadmin` may inspect delete-impact or delete Orders, Badges, and Suppliers (`editor` and `viewer` receive 403).
  - **Orders (`GET /admin/orders/{id}/delete-impact`, `DELETE /admin/orders/{id}`):** Requires `confirm: true` and `reason` (≥ 3 chars). In one atomic transaction, if `inventory_held` and `reconcile_stock` are both true, locks products/variants, restores on-hand stock, and inserts positive `adjustment` movements (`order_id=NULL`, note referencing `#order_number` and `reason`) so `sum(stock_movements.quantity) == on_hand`; records a complete `ORDER_DELETED` snapshot in `audit_events`; removes order items/activities/idempotency/coupon redemptions; and nulls `order_id` on preserved historical movements, reviews, and notifications.
  - **Badges (`GET /admin/badges/{id}/delete-impact`, `DELETE /admin/badges/{id}`):** Refuses built-in (`is_system=True`) badges with 409. Supports `mode="unlink"` (removes links) or `mode="merge"` (moves links to `target_badge_id`, skipping duplicates on products that already have the target), recomputes legacy `products.badge`, logs `BADGE_DELETED`, and deletes atomically.
  - **Suppliers (`GET /admin/inventory/suppliers/{id}/delete-impact`, `DELETE /admin/inventory/suppliers/{id}`):** Supports `mode="merge"` (moves all purchases & linked products to `target_supplier_id`, logs `SUPPLIER_MERGED`, hard-deletes old row), `mode="archive"` (default; soft-deletes while keeping purchase history intact and optionally clearing `products.supplier_id`), and `mode="hard_delete"` (permitted only when `purchases_count == 0`, else 409; clears `products.supplier_id`, logs `SUPPLIER_DELETED`, deletes row).
- **Stock** is the stock right now. The date filter does not limit it, and channel is ignored. Stock value is `quantity × cost_price` where both are set, `potential_retail_value` is `quantity × price` where `quantity` is set, and `expected_profit_on_hand` is `quantity × (price - cost_price)` where both are set. Units with no cost are `unknown_cost_units` and products missing `cost_price` are counted in `missing_cost_count`. Low stock is `quantity` not NULL and `quantity ≤ 5` (zero counts; a NULL quantity, made to order, does not). "No sale in 30 days" means no line of that product on an order whose `delivered_at` falls in the 30 Dhaka days ending today (today and the 29 days before it).
- **Movements** sum `stock_movements.quantity` (sale is negative). Opening balance is the sum of movements before the window. The period totals are opening, purchase, sale, return, cancel, and adjustment. Closing stock is the sum of every movement before the end of the window, so closing = opening balance + those six totals. Channel is ignored.
- **Delivery and returns.** Delivered counts `delivered_at`. Returned counts `returned_at`. Cancelled counts `updated_at` while `status` is `cancelled`, because there is no `cancelled_at`. A later edit of a cancelled order (courier, tracking) can move `updated_at` and therefore the cancel day. Return rate is returned ÷ delivered × 100, NULL when nothing was delivered. It can be over 100% when more orders were returned in the window than delivered in it. An order delivered and returned in the same window counts in both.
- **Trend** is net sales and profit by day, week, or month. Net sales subtract that day's coupon share. Profit uses known-cost revenue after the same share. Week buckets start on Monday. Month buckets start on the 1st. The first and last bucket can be partial. The default grain is day up to 31 days, week up to 92, otherwise month. An empty day has profit 0. A day whose only sales have no `unit_cost` has profit NULL.
- **Coupons** (`GET /admin/reports/coupons`) count active redemptions whose `created_at` (the order time, not `delivered_at`) is in the window. Cancelled redemptions are omitted. A returned order stays. Per coupon: times used, total discount (sum of `discount_amount`), total sales (sum of `orders.total`, which is after the coupon and includes delivery). The date query is the shared one (preset or from/to, 366 days, Asia/Dhaka). Product, category, and channel are ignored. This report will not match the sales report for orders that are not yet delivered. The Excel export follows the other report workbooks.

The dashboard still counts revenue, orders, customers, pending, statuses, best sellers, areas, categories, and the chart by `created_at`, and it still leaves cancelled and returned orders out of revenue. Its delivered count is the number of orders whose `delivered_at` is in the window, including one that was later returned.

## Categories

- Categories form a tree with a maximum depth (`MAX_DEPTH`) and a database cycle guard.
- At most 1000 categories.
- A listing filtered by a hidden or missing category returns an empty list instead of leaking hidden products.

## Storefront SEO

Code: `app/services/site_settings_service.py`, `app/schemas/site_settings.py`.

- One `site_settings` row (slug `main`) holds the home/default document title, the default meta description, and an optional title template. There is no second settings table for this.
- Lengths, counted in characters: `seo_title` ≤ 70, `seo_description` ≤ 170, `seo_title_template` ≤ 80. A template that is set contains `%s` exactly once and no other `%` (`%s | Implesia Mart`). The storefront replaces `%s` with that page's title.
- Empty is stored and returned as `null`. The storefront then keeps its built-in copy. The API does not invent a fallback title.
- PATCH leaves out a field to keep it. `null` or a blank string clears it. Whitespace collapses to one space.
- Public `GET /api/v1/site/settings` may be cached by the client for 60 seconds (`Cache-Control: public, max-age=60`). The handler still reads the database. Admin GET and PATCH are `Cache-Control: no-store`. Editor or above. A viewer is 403.

## CMS content

- Home sections (hero, categories, featured, showcase, promo, …), about, sustainability, shipping, privacy, FAQs, contact, blogs, site header/footer/contact, and the storefront SEO settings are admin-edited and read publicly.
- Admin href fields reject script schemes (`javascript:` and similar).
- Home showcase rows (`gadgets` = Trending, `fashion`) are curated lists: admin `choices` and added/edited items must be published products from any category (422 "Choose a published product"; an edit may keep its current product if it was hidden later). At most 12 per row, no duplicates. Public `GET /home/showcase` returns only published pinned products.
- Home media section (`home_media`, one row, `app/services/home/media_service.py`): `media_type` is `image`, `video` or `youtube`. Public `GET /home/media` returns null unless active with a heading and usable media (image needs `image_src` + `media_alt`, video needs an MP4/WEBM `video_src`, YouTube needs the id). `youtube_url` accepts watch / youtu.be / shorts / embed links or an id (same `youtube_id()` check as products) and is stored as the id. The button is shown only when `cta_enabled` with a label and a link that is a site path (`/…`, no `//` or `..`) or `https://`. On save only the chosen type's fields are kept (image: no video/YouTube/thumbnail; video: no image/YouTube; YouTube: no image/video) and replaced or dropped files under `/media/home-media/` are deleted. Uploads: images 5 MB (JPEG/PNG/WEBP/GIF by content), videos 50 MB (MP4/WEBM by content). Public and admin responses are `Cache-Control: no-store`.
- Blog and CMS writes name every invalid field in 422/409 errors.

## Customer dashboard, notifications & purchased history

Code: `app/services/customer_auth_service.py`, `app/services/customer_purchased_service.py`, `app/services/notification_service.py`, `app/services/review_service.py`.

- **Profile & avatar:** `PATCH /customer/profile` keeps omitted fields as stored and clears optional `email`, `district`, `area`, and `address` to `NULL` when explicitly sent as `null` or blank string. `POST /customer/profile/avatar` stores under `/media/avatars/` and deletes any replaced owned avatar. `DELETE /customer/profile/avatar` clears `avatar_url` to `NULL` and deletes the owned file.
- **Dashboard summary:** `total_orders` counts all orders owned by the customer; `active_orders` counts `new`, `confirmed`, `packed`, `shipped`; `delivered_orders` counts `delivered`; `cancelled_orders` counts `cancelled`; `total_spent` sums `orders.total` and `total_products_purchased` sums `order_items.quantity` across non-cancelled/non-returned orders; `unread_notifications` counts unread notifications within the last 30 days.
- **In-app notifications & 30-day retention:** Notifications are created automatically when a new online order is placed (for logged-in or phone-matched customers; never duplicated on idempotency replays), when admin changes status via single `PATCH` or `POST /bulk-status` (unless `notify_customer` is false). Rows older than 30 days are physically purged opportunistically on notification list/create (global cleanup throttled per hour plus immediate per-user cleanup on list) and via standalone `notification_service.purge_expired_notifications(db)`. Customers may also delete individual own notifications (`DELETE /customer/notifications/{id}`).
- **Customer order tracking:** Step timestamps come from `order.created_at` (`new`), `order_activities` (`status_changed`), and `order.delivered_at`/`order.returned_at` fallbacks — never fabricated from `order.updated_at`. Terminal statuses `cancelled` and `returned` show the reached forward steps followed by a completed terminal step. `tracking_url` and `live_events` default to `null` and `[]` for future live courier API integration.
- **Purchased products history:** Returns all line items from eligible orders (`confirmed`, `packed`, `shipped`, `delivered`) newest first without deduplicating repeat purchases across orders. Includes `quantity`, `line_total`, `order_status`, `paid_amount`, `due_amount`, and `payment_status` (`paid` when paid ≥ total, `partial` when 0 < paid < total, `cod_due` when unpaid COD, else `unpaid`). `can_review` is true per product until the customer submits one verified review for that product.
