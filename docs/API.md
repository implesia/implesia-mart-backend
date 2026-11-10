# API

Generated from the FastAPI routers (`app/api/v1/router.py` and `app/api/v1/endpoints/`). Routes are under `/api/v1` unless noted. Regenerate this list when a router changes.

## Access levels

- **public**: no token. Storefront and shopper calls. Carts identify a guest by the `X-Cart-Token` header.
- **any signed-in staff**: a valid staff access token (`Authorization: Bearer …`), any role (`viewer`, `editor`, `superadmin`).
- **admin (editor, superadmin)**: `require_editor`. A `viewer` gets 403.
- **admin (superadmin only)**: `require_superadmin`.
- There are no customer accounts. Staff are the only signed-in users.
- A protected route without a token answers 401. A role that is too low answers 403.

## Errors

- Default envelope: `{"error": {"code", "message", "details"}}` (422 validation, 404 not found, 409 conflict, 401/403 auth).
- `POST /admin/products` only: `{"errors": [{"field", "message", "fix"}]}` with Bengali text, status 400 / 409 / 500. See BUSINESS_LOGIC.md.
- Admin routers mounted with `audit_admin_write` record successful writes in the audit log.

## Product endpoints in brief

- `POST /admin/products` (multipart): `payload` = JSON product (`ProductCreate`), `images` files with `image_alts` JSON list, optional `quality_image` + `quality_image_alt`, `videos` files with `video_alts` JSON list, `thumbnails` files with `thumbnail_targets` JSON list (gallery item id or `video:<n>`). New files are appended after the `content.gallery` items in the payload. Returns `AdminProductRead` (201).
- `PATCH /admin/products/{id}` (multipart): same parts, `payload` = partial `ProductUpdate`. Errors use the default envelope (422, English); a taken `slug` returns 409 `{"errors": [{"field": "slug", "message", "fix"}]}`.
- SEO: create/update take `seo_title` (≤120), `seo_description` (≤320), `seo_keywords` (≤500); update also takes `slug`. `AdminProductRead` and `PublicProductDetail` return the three SEO fields (`""` when unset).
- `cost_price` (number, two decimal places, `>= 0`, or `null`) is accepted on `POST` and `PATCH /admin/products` and returned on admin product list, get, create, and update (`AdminProductCard` / `AdminProductRead`). Omitted on PATCH keeps the stored value; `null` clears it. A negative value is 400 on create (`errors[].field` = `costPrice`) and 422 on update. Editor or above only; a viewer gets 403. Public product responses never include `cost_price`.
- `DELETE /admin/products/{id}`: 204.
- `DELETE /admin/products/bulk`: body `{"ids": ["<uuid>", ...]}` (1–100 after de-duplication). Returns `{"requested", "deleted", "deleted_ids", "skipped": [{"id", "reason": "not_found", "message"}], "failed": [{"id", "reason": "error", "message"}]}`.
- `GET /products/by-slug/{slug}` and `GET /products/{id}`: `PublicProductDetail`, published products only. `by-slug` also resolves a product's old slugs (`product_slug_redirects`). `gallery` items carry `kind` (`image`/`video`/`youtube`), `src`, `youtube_id`, `alt`, `thumbnail` (custom thumbnail or empty).
- Public product cards (`GET /products`, category product lists) and `PublicProductDetail` include `updated_at` (ISO datetime). New products without an explicit `slug` get a transliterated slug for Bengali titles (`smart-ghori`).

## Outside `/api/v1`

| Method | Path | Access | Notes |
| --- | --- | --- | --- |
| GET | `/` | public | service info |
| GET | `/health/live` | public | liveness probe |
| GET | `/health/ready` | public | checks the database and Redis |
| GET | `/metrics` | metrics token (setting `METRICS_TOKEN`) | Prometheus metrics |
| GET, HEAD | `/media/{folder}/{name}` | public | With R2 configured, `307` to `MEDIA_PUBLIC_BASE_URL/{folder}/{name}`. Otherwise the file on disk. Stored values stay `/media/...`. |

## `admin/audit-events`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/audit-events` | admin (superadmin only) | — | `Page[AuditEventRead]` |

## `admin/badges`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/badges` | admin (editor, superadmin) | — | `BadgeAdminList` |
| POST | `/api/v1/admin/badges` | admin (editor, superadmin) | `BadgeWrite` | `BadgeAdminRead` |
| DELETE | `/api/v1/admin/badges/{badge_id}` | admin (editor, superadmin) | — | `Message` |
| GET | `/api/v1/admin/badges/{badge_id}` | admin (editor, superadmin) | — | `BadgeAdminRead` |
| PATCH | `/api/v1/admin/badges/{badge_id}` | admin (editor, superadmin) | `BadgeUpdate` | `BadgeAdminRead` |

## `admin/carts`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/carts` | admin (editor, superadmin) | — | `AdminCartList` |
| GET | `/api/v1/admin/carts/{cart_id}` | admin (editor, superadmin) | — | `AdminCartRead` |

## `admin/categories`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/categories` | admin (editor, superadmin) | — | `CategoryAdminList` |
| POST | `/api/v1/admin/categories` | admin (editor, superadmin) | multipart form | `CategoryAdminRead` |
| PUT | `/api/v1/admin/categories/order` | admin (editor, superadmin) | `CategoryOrder` | `CategoryAdminList` |
| DELETE | `/api/v1/admin/categories/{category_id}` | admin (editor, superadmin) | — | `Message` |
| GET | `/api/v1/admin/categories/{category_id}` | admin (editor, superadmin) | — | `CategoryAdminRead` |
| PATCH | `/api/v1/admin/categories/{category_id}` | admin (editor, superadmin) | multipart form | `CategoryAdminRead` |

## `admin/dashboard`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/dashboard` | admin (editor, superadmin) | — | `DashboardOverview` |

Query: `range` is `today`, `yesterday`, `7d` (default), `30d`, `this-month`, `last-month`, or `custom`. Custom also needs `from` and `to` (`YYYY-MM-DD`, Asia/Dhaka). Longer than 366 days is 422. Revenue, orders, customers, pending, statuses, best sellers, areas, categories, and the chart follow `created_at` and leave cancelled and returned orders out of revenue. `delivered.value` counts orders whose `delivered_at` is in the window, including an order that was later returned. The figures are SQL aggregates. `Cache-Control: no-store`. Viewer is 403.

## `admin/reports`

Read-only sales and stock reports. Any signed-in staff, including `viewer`. There is no write route. Anonymous is 401. Every route is `Cache-Control: no-store`. Dates are inclusive Asia/Dhaka days. How each number is defined is in BUSINESS_LOGIC.md (Sales reports).

Shared query: `preset` (`this_week`, `this_month`, `last_month`) or both `from` and `to` (`YYYY-MM-DD`). Sending both a preset and dates, sending neither, sending `from` after `to`, or a range longer than 366 days is 422. Optional `product_id`, `category_id` (that category and its descendants), and `channel` (at most 32 characters). An unknown product or category is 422. A channel does not match orders whose `channel` is NULL. `grain` (`day`, `week`, `month`) applies to the trend only.

`cost_price` and `unit_cost` appear on the profit, product, and stock reports. They are not added to public product or order responses.

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/reports/sales` | any signed-in staff | — | `SalesSummary` |
| GET | `/api/v1/admin/reports/sales/export` | any signed-in staff | — | `.xlsx` |
| GET | `/api/v1/admin/reports/profit` | any signed-in staff | — | `ProfitReport` |
| GET | `/api/v1/admin/reports/profit/export` | any signed-in staff | — | `.xlsx` |
| GET | `/api/v1/admin/reports/products` | any signed-in staff | — | `ProductReport` |
| GET | `/api/v1/admin/reports/products/export` | any signed-in staff | — | `.xlsx` |
| GET | `/api/v1/admin/reports/stock` | any signed-in staff | — | `StockReport` |
| GET | `/api/v1/admin/reports/stock/export` | any signed-in staff | — | `.xlsx` |
| GET | `/api/v1/admin/reports/movements` | any signed-in staff | — | `MovementReport` |
| GET | `/api/v1/admin/reports/movements/export` | any signed-in staff | — | `.xlsx` |
| GET | `/api/v1/admin/reports/delivery` | any signed-in staff | — | `DeliveryReport` |
| GET | `/api/v1/admin/reports/delivery/export` | any signed-in staff | — | `.xlsx` |
| GET | `/api/v1/admin/reports/trend` | any signed-in staff | — | `TrendReport` |
| GET | `/api/v1/admin/reports/trend/export` | any signed-in staff | — | `.xlsx` |

- Products and stock also take `page` (1–10000, default 1) and `page_size` (1–100, default 20). Export ignores the page and stops at 20,000 rows.
- Stock on hand ignores the date window (`period_applies: false`) and the channel (`channel_applies: false`). Movements ignore the channel the same way.
- The workbook states the report name, timezone, from, to, preset, product, category, and whether the channel filter applied. Money columns are numeric cells.
- `MovementReport` uses the JSON key `return` for the return total. A sale quantity is negative.

## `admin/delivery`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/delivery` | any signed-in staff | — | `DeliveryRatesRead` |
| PATCH | `/api/v1/admin/delivery` | admin (editor, superadmin) | `DeliveryRatesUpdate` | `DeliveryRatesRead` |

## `admin/pricing`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pricing` | any signed-in staff | — | `PricingSettingsRead` |
| PUT | `/api/v1/admin/pricing` | admin (editor, superadmin) | `PricingSettingsUpdate` | `PricingSettingsRead` |

Body/response: `{"tiers_enabled": true, "max_discount_percent": 90, "max_quantity_per_order": 10, "tiers": [{"min_quantity": 2, "extra_percent": 0.25}, ...]}`. `max_quantity_per_order` is 1–1000 (422 otherwise); omitted on `PUT` = keep the stored value. Percents 0–99.99 (two decimals), `min_quantity` 2–1000, at most 20 tiers, no duplicate quantities (422). `Cache-Control: no-store`.

Product admin create/update also take `regular_price`, `base_discount_percent`, `tier_mode` (`global`/`custom`) and `tiers`; `AdminProductRead` returns them. `GET /products/by-slug/{slug}` and `/products/{id}` return `pricing` (`regular_price`, `selling_price`, `base_discount_percent`, `max_discount_percent`, `tiers` in force). `max_order_quantity` on a product: `null` = store-wide limit, 1–1000 = custom limit. Public detail `max_per_order`, each `variants[].max_quantity` and each cart line's `max_quantity` = min(effective limit, stock). Cart add/update and order create return 422 "এই পণ্যটি এক অর্ডারে সর্বোচ্চ Nটি নেওয়া যাবে।" above the limit. Cart and quote lines return `regular_price`, `base_discount_percent`, `quantity_discount_percent`, `total_discount_percent`; admin order items return the stored snapshot.

## `admin/inventory`

Staff inventory. `viewer` can read. Writes need `editor` or `superadmin`. Every route is `Cache-Control: no-store`. `unit_cost` and `cost_price` appear only here and on the admin product API, never on a public route. Lists use `page` and `page_size` and return `{items, total, page, page_size, pages}`.

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/inventory/suppliers` | any signed-in staff | — | `Page[SupplierRead]` |
| POST | `/api/v1/admin/inventory/suppliers` | admin (editor, superadmin) | `SupplierCreate` | `SupplierRead` |
| GET | `/api/v1/admin/inventory/suppliers/{supplier_id}` | any signed-in staff | — | `SupplierRead` |
| PATCH | `/api/v1/admin/inventory/suppliers/{supplier_id}` | admin (editor, superadmin) | `SupplierUpdate` | `SupplierRead` |
| GET | `/api/v1/admin/inventory/purchases` | any signed-in staff | — | `Page[PurchaseRead]` |
| POST | `/api/v1/admin/inventory/purchases` | admin (editor, superadmin) | `PurchaseCreate` | `PurchaseRead` |
| GET | `/api/v1/admin/inventory/purchases/{purchase_id}` | any signed-in staff | — | `PurchaseRead` |
| GET | `/api/v1/admin/inventory/movements` | any signed-in staff | — | `Page[MovementRead]` |
| POST | `/api/v1/admin/inventory/adjustments` | admin (editor, superadmin) | `AdjustmentCreate` | `MovementRead` |
| POST | `/api/v1/admin/inventory/opening-stock` | admin (editor, superadmin) | — | `OpeningStockResult` |
| GET | `/api/v1/admin/inventory/exports/{kind}` | any signed-in staff | — | `.xlsx` file |
| GET | `/api/v1/admin/inventory/imports/templates/{kind}` | any signed-in staff | — | `.xlsx` template |
| POST | `/api/v1/admin/inventory/imports/preview` | any signed-in staff | multipart | `ImportPreview` |
| POST | `/api/v1/admin/inventory/imports/confirm` | admin (editor, superadmin) | multipart | `ImportResult` |

- Supplier queries: `q` (name contains), `page`, `page_size`.
- Purchase queries: `supplier_id`, `date_from`, `date_to` (inclusive dates), `page`, `page_size`.
- Movement queries: `product_id`, `movement_type` (`opening`, `purchase`, `sale`, `return`, `cancel`, `adjustment`), `date_from`, `date_to`, `page`, `page_size`. `date_from` after `date_to` is 422.
- `SupplierCreate`: `name` (required), `phone`, `address`, `note`.
- `PurchaseCreate`: `supplier_id`, `purchased_on` (`YYYY-MM-DD`), `invoice_no`, `note`, `items` (1–100 of `product_id`, optional `variant_id`, `quantity` ≥ 1, `unit_cost` ≥ 0). Saving increases stock and sets `cost_price` to the weighted average. See BUSINESS_LOGIC.md.
- `AdjustmentCreate`: `product_id`, optional `variant_id`, `quantity` (non-zero signed difference), `reason` (required). Editor or above.
- `OpeningStockResult`: `created`, `already_recorded`, `untracked`. Does not change stock. The same action from the shell is `python -m scripts.opening_stock`.
- Export `kind`: `products`, `purchases`, `movements`. Optional `date_from` and `date_to`. The body is an `.xlsx` download.
- Import `kind` for the template path, and form field `import_type` for preview and confirm: `purchases`, `opening`, `stock_count`, `cost_price`.
- Preview and confirm send multipart `file` plus `import_type`. Confirm also accepts `confirm_duplicate` (`true` / `false`, default false). Preview writes nothing. Confirm saves every valid row in one transaction and skips invalid rows. A file whose every row is invalid is 422 and saves nothing. The same file bytes imported again are 409 until `confirm_duplicate` is true. Non-`.xlsx` files, files over 2 MB, and sheets over 2,000 data rows are 422.
- Preview `rows[]`: `row` (sheet row number), `valid`, `action`, `errors` (what is wrong, empty when valid), `summary`.
- There is no route to update or delete a movement, a purchase, or a purchase line.

## `admin/home/banner`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/banner` | admin (editor, superadmin) | — | `HomeBannerRead` |
| PATCH | `/api/v1/admin/home/banner` | admin (editor, superadmin) | `HomeBannerUpdate` | `HomeBannerRead` |
| GET | `/api/v1/admin/home/banner/slides` | admin (editor, superadmin) | — | `Page[BannerSlideAdmin]` |
| POST | `/api/v1/admin/home/banner/slides` | admin (editor, superadmin) | multipart form | `BannerSlideAdmin` |
| DELETE | `/api/v1/admin/home/banner/slides/{slide_id}` | admin (editor, superadmin) | — | `Message` |
| GET | `/api/v1/admin/home/banner/slides/{slide_id}` | admin (editor, superadmin) | — | `BannerSlideAdmin` |
| PATCH | `/api/v1/admin/home/banner/slides/{slide_id}` | admin (editor, superadmin) | multipart form | `BannerSlideAdmin` |
| POST | `/api/v1/admin/home/banner/slides/{slide_id}/move` | admin (editor, superadmin) | `BannerSlideMove` | `BannerSlideAdmin` |

## `admin/home/categories`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/categories` | admin (editor, superadmin) | — | `CategoryAdmin` |
| PATCH | `/api/v1/admin/home/categories` | admin (editor, superadmin) | `CategoryHeadingUpdate` | `CategoryAdmin` |
| POST | `/api/v1/admin/home/categories/tiles` | admin (editor, superadmin) | multipart form | `CategoryTileRead` |
| PUT | `/api/v1/admin/home/categories/tiles/order` | admin (editor, superadmin) | `CategoryReorder` | `CategoryAdmin` |
| DELETE | `/api/v1/admin/home/categories/tiles/{tile_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/categories/tiles/{tile_id}` | admin (editor, superadmin) | multipart form | `CategoryTileRead` |

## `admin/home/faq`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/faq` | admin (editor, superadmin) | — | `FaqAdmin` |
| PATCH | `/api/v1/admin/home/faq` | admin (editor, superadmin) | `FaqCopyUpdate` | `FaqAdmin` |
| POST | `/api/v1/admin/home/faq/items` | admin (editor, superadmin) | `FaqItemWrite` | `FaqItemRead` |
| PUT | `/api/v1/admin/home/faq/items/order` | admin (editor, superadmin) | `FaqReorder` | `FaqAdmin` |
| DELETE | `/api/v1/admin/home/faq/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/faq/items/{item_id}` | admin (editor, superadmin) | `FaqItemUpdate` | `FaqItemRead` |

## `admin/home/featured`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/featured` | admin (editor, superadmin) | — | `FeaturedAdmin` |
| PATCH | `/api/v1/admin/home/featured` | admin (editor, superadmin) | `FeaturedCopyUpdate` | `FeaturedAdmin` |
| POST | `/api/v1/admin/home/featured/items` | admin (editor, superadmin) | `FeaturedItemWrite` | `FeaturedItemRead` |
| PUT | `/api/v1/admin/home/featured/items/order` | admin (editor, superadmin) | `FeaturedReorder` | `FeaturedAdmin` |
| DELETE | `/api/v1/admin/home/featured/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/featured/items/{item_id}` | admin (editor, superadmin) | `FeaturedItemWrite` | `FeaturedItemRead` |

## `admin/home/newsletter`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/newsletter` | admin (editor, superadmin) | — | `NewsletterAdmin` |
| PATCH | `/api/v1/admin/home/newsletter` | admin (editor, superadmin) | `NewsletterCopyUpdate` | `NewsletterAdmin` |
| POST | `/api/v1/admin/home/newsletter/perks` | admin (editor, superadmin) | `NewsletterPerkWrite` | `NewsletterPerkRead` |
| PUT | `/api/v1/admin/home/newsletter/perks/order` | admin (editor, superadmin) | `NewsletterReorder` | `NewsletterAdmin` |
| DELETE | `/api/v1/admin/home/newsletter/perks/{perk_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/newsletter/perks/{perk_id}` | admin (editor, superadmin) | `NewsletterPerkUpdate` | `NewsletterPerkRead` |

## `admin/home/media`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/media` | admin (editor, superadmin) | — | `MediaAdmin` |
| PUT | `/api/v1/admin/home/media` | admin (editor, superadmin) | `MediaWrite` | `MediaAdmin` |
| POST | `/api/v1/admin/home/media/image` | admin (editor, superadmin) | multipart form (`image`) | `MediaUploaded` |
| POST | `/api/v1/admin/home/media/video` | admin (editor, superadmin) | multipart form (`video`) | `MediaUploaded` |

## `admin/home/promo`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/promo` | admin (editor, superadmin) | — | `PromoAdmin` |
| PUT | `/api/v1/admin/home/promo` | admin (editor, superadmin) | `PromoWrite` | `PromoAdmin` |
| POST | `/api/v1/admin/home/promo/image` | admin (editor, superadmin) | multipart form | `ImageUploaded` |

## `admin/home/reviews`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/reviews` | admin (editor, superadmin) | — | `ReviewAdmin` |
| PATCH | `/api/v1/admin/home/reviews` | admin (editor, superadmin) | `ReviewCopyUpdate` | `ReviewAdmin` |
| POST | `/api/v1/admin/home/reviews/items` | admin (editor, superadmin) | multipart form | `ReviewItemRead` |
| PUT | `/api/v1/admin/home/reviews/items/order` | admin (editor, superadmin) | `ReviewReorder` | `ReviewAdmin` |
| DELETE | `/api/v1/admin/home/reviews/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/reviews/items/{item_id}` | admin (editor, superadmin) | multipart form | `ReviewItemRead` |

## `admin/home/showcase`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/showcase` | admin (editor, superadmin) | — | `ShowcaseAdmin` |
| PATCH | `/api/v1/admin/home/showcase/rows/{key}` | admin (editor, superadmin) | `ShowcaseRowUpdate` | `ShowcaseAdmin` |
| POST | `/api/v1/admin/home/showcase/rows/{key}/items` | admin (editor, superadmin) | `ShowcaseItemWrite` | `ShowcaseItemRead` |
| PUT | `/api/v1/admin/home/showcase/rows/{key}/items/order` | admin (editor, superadmin) | `ShowcaseReorder` | `ShowcaseAdmin` |
| DELETE | `/api/v1/admin/home/showcase/rows/{key}/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/showcase/rows/{key}/items/{item_id}` | admin (editor, superadmin) | `ShowcaseItemWrite` | `ShowcaseItemRead` |

`ShowcaseRowAdmin.choices` is every published product (any category). Item writes reject a hidden product with 422 "Choose a published product".

## `admin/home/trust`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/home/trust` | admin (editor, superadmin) | — | `list` |
| POST | `/api/v1/admin/home/trust` | admin (editor, superadmin) | `TrustItemWrite` | `TrustItemRead` |
| PUT | `/api/v1/admin/home/trust/order` | admin (editor, superadmin) | `TrustReorder` | `list` |
| DELETE | `/api/v1/admin/home/trust/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/home/trust/{item_id}` | admin (editor, superadmin) | `TrustItemUpdate` | `TrustItemRead` |

## `admin/inquiries`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/inquiries` | admin (editor, superadmin) | — | `InquiryList` |
| GET | `/api/v1/admin/inquiries/counts` | admin (editor, superadmin) | — | `InquiryCounts` |
| DELETE | `/api/v1/admin/inquiries/{inquiry_id}` | admin (editor, superadmin) | — | 204 No Content |
| GET | `/api/v1/admin/inquiries/{inquiry_id}` | admin (editor, superadmin) | — | `InquiryAdmin` |
| PATCH | `/api/v1/admin/inquiries/{inquiry_id}` | admin (editor, superadmin) | `InquiryUpdate` | `InquiryAdmin` |

## `admin/orders`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/orders/new` | any signed-in staff | — | `NewOrderFeed` |
| GET | `/api/v1/admin/orders` | admin (editor, superadmin) | — | `AdminOrderList` |
| GET | `/api/v1/admin/orders/{order_id}` | admin (editor, superadmin) | — | `OrderRead` |
| PATCH | `/api/v1/admin/orders/{order_id}` | admin (editor, superadmin) | `OrderUpdate` | `OrderRead` |

`GET /api/v1/admin/orders/new` is a cursor feed for polling, not a page. `Cache-Control: no-store`. Anonymous, or a bearer token that is not a live staff session, is 401. A viewer is allowed here and is still 403 on the editor list.

Query: `since` (optional ISO-8601; a value with no timezone is UTC) and `limit` (integer 1–50, default 20). `limit` outside that range is 422.

The server reads `now` (UTC) first. Rows are `created_at > since` and `created_at <= now`, newest first (`created_at`, then `id`). With no `since`, `since` is `now` minus 24 hours. The next poll should send this response's `now` as `since`, so a row is not returned twice and a row created after `now` shows up on the next poll.

```json
{
  "now": "2026-11-10T12:00:00+00:00",
  "items": [
    {
      "id": "00000000-0000-4000-8000-000000000001",
      "number": "IM-AB12CD34",
      "customer_name": "Rina Akter",
      "total": 1570,
      "payment_method": "cod",
      "created_at": "2026-11-10T11:55:00+00:00"
    }
  ]
}
```

`payment_method` is the stored value: `cod` or `bangla_qr`. `total` is the order total in whole taka. The select list is only these columns. `ix_orders_created_at` (migration 0005) supports the filter.

`OrderRead` includes `delivered_at` and `returned_at` (ISO datetime or `null`). They are set the first time the status becomes `delivered` or `returned` and are not replaced later. `PublicOrderRead` (order lookup) does not include them. `POST /orders` returns them as `null` on a new order. `OrderRead` also includes `order_number` (the same value as `number`) and `analytics_event_id` (`purchase_` plus that number). Those two fields are derived. They do not cause a Meta call on admin reads or status updates.

## `admin/pages/about`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/about/cta` | admin (editor, superadmin) | — | `CtaRead` |
| PATCH | `/api/v1/admin/pages/about/cta` | admin (editor, superadmin) | `CtaWrite` | `CtaRead` |
| GET | `/api/v1/admin/pages/about/dresses` | admin (editor, superadmin) | — | `list` |
| POST | `/api/v1/admin/pages/about/dresses` | admin (editor, superadmin) | multipart form | `DressRead` |
| PUT | `/api/v1/admin/pages/about/dresses/order` | admin (editor, superadmin) | `DressReorder` | `list` |
| DELETE | `/api/v1/admin/pages/about/dresses/{dress_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/about/dresses/{dress_id}` | admin (editor, superadmin) | multipart form | `DressRead` |
| GET | `/api/v1/admin/pages/about/hero` | admin (editor, superadmin) | — | `AboutHeroAdmin` |
| PUT | `/api/v1/admin/pages/about/hero` | admin (editor, superadmin) | multipart form | `AboutHeroAdmin` |
| GET | `/api/v1/admin/pages/about/mission` | admin (editor, superadmin) | — | `list` |
| PATCH | `/api/v1/admin/pages/about/mission/{card_key}` | admin (editor, superadmin) | `MissionCardWrite` | `MissionCardRead` |
| GET | `/api/v1/admin/pages/about/stats` | admin (editor, superadmin) | — | `list` |
| POST | `/api/v1/admin/pages/about/stats` | admin (editor, superadmin) | `StatItemWrite` | `StatItemRead` |
| PUT | `/api/v1/admin/pages/about/stats/order` | admin (editor, superadmin) | `StatReorder` | `list` |
| DELETE | `/api/v1/admin/pages/about/stats/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/about/stats/{item_id}` | admin (editor, superadmin) | `StatItemUpdate` | `StatItemRead` |
| GET | `/api/v1/admin/pages/about/steps` | admin (editor, superadmin) | — | `StepsAdmin` |
| PATCH | `/api/v1/admin/pages/about/steps` | admin (editor, superadmin) | `StepsCopyUpdate` | `StepsAdmin` |
| POST | `/api/v1/admin/pages/about/steps/items` | admin (editor, superadmin) | `StepItemWrite` | `StepItemRead` |
| PUT | `/api/v1/admin/pages/about/steps/items/order` | admin (editor, superadmin) | `StepReorder` | `StepsAdmin` |
| DELETE | `/api/v1/admin/pages/about/steps/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/about/steps/items/{item_id}` | admin (editor, superadmin) | `StepItemWrite` | `StepItemRead` |
| GET | `/api/v1/admin/pages/about/stories` | admin (editor, superadmin) | — | `list` |
| POST | `/api/v1/admin/pages/about/stories` | admin (editor, superadmin) | multipart form | `StoryRead` |
| PUT | `/api/v1/admin/pages/about/stories/order` | admin (editor, superadmin) | `StoryReorder` | `list` |
| DELETE | `/api/v1/admin/pages/about/stories/{story_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/about/stories/{story_id}` | admin (editor, superadmin) | multipart form | `StoryRead` |
| GET | `/api/v1/admin/pages/about/values` | admin (editor, superadmin) | — | `ValuesAdmin` |
| PATCH | `/api/v1/admin/pages/about/values` | admin (editor, superadmin) | `ValuesCopyUpdate` | `ValuesAdmin` |
| POST | `/api/v1/admin/pages/about/values/items` | admin (editor, superadmin) | `ValueItemWrite` | `ValueItemRead` |
| PUT | `/api/v1/admin/pages/about/values/items/order` | admin (editor, superadmin) | `ValueReorder` | `ValuesAdmin` |
| DELETE | `/api/v1/admin/pages/about/values/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/about/values/items/{item_id}` | admin (editor, superadmin) | `ValueItemWrite` | `ValueItemRead` |

## `admin/pages/blogs`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/blogs/categories` | admin (editor, superadmin) | — | `CategoriesAdmin` |
| PATCH | `/api/v1/admin/pages/blogs/categories` | admin (editor, superadmin) | `CategoriesWrite` | `CategoriesAdmin` |
| GET | `/api/v1/admin/pages/blogs/cta` | admin (editor, superadmin) | — | `CtaAdmin` |
| PATCH | `/api/v1/admin/pages/blogs/cta` | admin (editor, superadmin) | `CtaWrite` | `CtaAdmin` |
| GET | `/api/v1/admin/pages/blogs/hero` | admin (editor, superadmin) | — | `HeroAdmin` |
| PATCH | `/api/v1/admin/pages/blogs/hero` | admin (editor, superadmin) | `HeroWrite` | `HeroAdmin` |
| GET | `/api/v1/admin/pages/blogs/listing` | admin (editor, superadmin) | — | `ListingAdmin` |
| PATCH | `/api/v1/admin/pages/blogs/listing` | admin (editor, superadmin) | `ListingWrite` | `ListingAdmin` |
| GET | `/api/v1/admin/pages/blogs/posts` | admin (editor, superadmin) | — | `PostsAdmin` |
| POST | `/api/v1/admin/pages/blogs/posts` | admin (editor, superadmin) | `PostWrite` | `PostAdmin` |
| POST | `/api/v1/admin/pages/blogs/posts/cover` | admin (editor, superadmin) | multipart form | `CoverUploaded` |
| PUT | `/api/v1/admin/pages/blogs/posts/order` | admin (editor, superadmin) | `PostReorder` | `PostsAdmin` |
| DELETE | `/api/v1/admin/pages/blogs/posts/{post_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/blogs/posts/{post_id}` | admin (editor, superadmin) | `PostWrite` | `PostAdmin` |
| GET | `/api/v1/admin/pages/blogs/related` | admin (editor, superadmin) | — | `RelatedAdmin` |
| PATCH | `/api/v1/admin/pages/blogs/related` | admin (editor, superadmin) | `RelatedWrite` | `RelatedAdmin` |

## `admin/pages/contact`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/contact/details` | admin (editor, superadmin) | — | `DetailsAdmin` |
| PATCH | `/api/v1/admin/pages/contact/details` | admin (editor, superadmin) | `DetailsWrite` | `DetailsAdmin` |
| GET | `/api/v1/admin/pages/contact/faq` | admin (editor, superadmin) | — | `FaqAdmin` |
| PATCH | `/api/v1/admin/pages/contact/faq` | admin (editor, superadmin) | `FaqWrite` | `FaqAdmin` |
| GET | `/api/v1/admin/pages/contact/form` | admin (editor, superadmin) | — | `FormAdmin` |
| PATCH | `/api/v1/admin/pages/contact/form` | admin (editor, superadmin) | `FormWrite` | `FormAdmin` |
| GET | `/api/v1/admin/pages/contact/hero` | admin (editor, superadmin) | — | `HeroAdmin` |
| PATCH | `/api/v1/admin/pages/contact/hero` | admin (editor, superadmin) | `HeroWrite` | `HeroAdmin` |
| GET | `/api/v1/admin/pages/contact/support` | admin (editor, superadmin) | — | `SupportAdmin` |
| PATCH | `/api/v1/admin/pages/contact/support` | admin (editor, superadmin) | `SupportWrite` | `SupportAdmin` |

## `admin/pages/faqs`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/faqs/callout` | admin (editor, superadmin) | — | `CalloutAdmin` |
| PATCH | `/api/v1/admin/pages/faqs/callout` | admin (editor, superadmin) | `CalloutWrite` | `CalloutAdmin` |
| GET | `/api/v1/admin/pages/faqs/categories` | admin (editor, superadmin) | — | `CategoriesAdmin` |
| PATCH | `/api/v1/admin/pages/faqs/categories` | admin (editor, superadmin) | `CategoriesWrite` | `CategoriesAdmin` |
| GET | `/api/v1/admin/pages/faqs/help` | admin (editor, superadmin) | — | `HelpAdmin` |
| PATCH | `/api/v1/admin/pages/faqs/help` | admin (editor, superadmin) | `HelpWrite` | `HelpAdmin` |
| GET | `/api/v1/admin/pages/faqs/hero` | admin (editor, superadmin) | — | `HeroAdmin` |
| PATCH | `/api/v1/admin/pages/faqs/hero` | admin (editor, superadmin) | `HeroWrite` | `HeroAdmin` |
| GET | `/api/v1/admin/pages/faqs/items` | admin (editor, superadmin) | — | `ItemsAdmin` |
| POST | `/api/v1/admin/pages/faqs/items` | admin (editor, superadmin) | `ItemWrite` | `ItemRead` |
| PUT | `/api/v1/admin/pages/faqs/items/order` | admin (editor, superadmin) | `ItemReorder` | `ItemsAdmin` |
| DELETE | `/api/v1/admin/pages/faqs/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/faqs/items/{item_id}` | admin (editor, superadmin) | `ItemWrite` | `ItemRead` |
| GET | `/api/v1/admin/pages/faqs/listing` | admin (editor, superadmin) | — | `ListingAdmin` |
| PATCH | `/api/v1/admin/pages/faqs/listing` | admin (editor, superadmin) | `ListingWrite` | `ListingAdmin` |

## `admin/pages/privacy`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/privacy/collection` | admin (editor, superadmin) | — | `CollectionAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/collection` | admin (editor, superadmin) | `CollectionWrite` | `CollectionAdmin` |
| GET | `/api/v1/admin/pages/privacy/contents` | admin (editor, superadmin) | — | `ContentsAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/contents` | admin (editor, superadmin) | `ContentsWrite` | `ContentsAdmin` |
| GET | `/api/v1/admin/pages/privacy/hero` | admin (editor, superadmin) | — | `HeroAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/hero` | admin (editor, superadmin) | `HeroWrite` | `HeroAdmin` |
| GET | `/api/v1/admin/pages/privacy/introduction` | admin (editor, superadmin) | — | `IntroductionAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/introduction` | admin (editor, superadmin) | `IntroductionWrite` | `IntroductionAdmin` |
| GET | `/api/v1/admin/pages/privacy/rights` | admin (editor, superadmin) | — | `RightsAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/rights` | admin (editor, superadmin) | `RightsWrite` | `RightsAdmin` |
| GET | `/api/v1/admin/pages/privacy/sharing` | admin (editor, superadmin) | — | `SharingAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/sharing` | admin (editor, superadmin) | `SharingWrite` | `SharingAdmin` |
| GET | `/api/v1/admin/pages/privacy/support` | admin (editor, superadmin) | — | `SupportAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/support` | admin (editor, superadmin) | `SupportWrite` | `SupportAdmin` |
| GET | `/api/v1/admin/pages/privacy/usage` | admin (editor, superadmin) | — | `UsageAdmin` |
| PATCH | `/api/v1/admin/pages/privacy/usage` | admin (editor, superadmin) | `UsageWrite` | `UsageAdmin` |

## `admin/pages/shipping`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/shipping/contents` | admin (editor, superadmin) | — | `ContentsAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/contents` | admin (editor, superadmin) | `ContentsWrite` | `ContentsAdmin` |
| GET | `/api/v1/admin/pages/shipping/faq` | admin (editor, superadmin) | — | `FaqAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/faq` | admin (editor, superadmin) | `FaqWrite` | `FaqAdmin` |
| GET | `/api/v1/admin/pages/shipping/hero` | admin (editor, superadmin) | — | `HeroAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/hero` | admin (editor, superadmin) | `HeroWrite` | `HeroAdmin` |
| GET | `/api/v1/admin/pages/shipping/payment` | admin (editor, superadmin) | — | `PaymentAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/payment` | admin (editor, superadmin) | `PaymentWrite` | `PaymentAdmin` |
| GET | `/api/v1/admin/pages/shipping/refund` | admin (editor, superadmin) | — | `RefundAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/refund` | admin (editor, superadmin) | `RefundWrite` | `RefundAdmin` |
| GET | `/api/v1/admin/pages/shipping/returns` | admin (editor, superadmin) | — | `ReturnsAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/returns` | admin (editor, superadmin) | `ReturnsWrite` | `ReturnsAdmin` |
| GET | `/api/v1/admin/pages/shipping/shipping` | admin (editor, superadmin) | — | `BlockAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/shipping` | admin (editor, superadmin) | `BlockWrite` | `BlockAdmin` |
| GET | `/api/v1/admin/pages/shipping/support` | admin (editor, superadmin) | — | `SupportAdmin` |
| PATCH | `/api/v1/admin/pages/shipping/support` | admin (editor, superadmin) | `SupportWrite` | `SupportAdmin` |

## `admin/pages/sustainability`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/pages/sustainability/commitment` | admin (editor, superadmin) | — | `CommitmentAdmin` |
| PATCH | `/api/v1/admin/pages/sustainability/commitment` | admin (editor, superadmin) | `CommitmentCopyUpdate` | `CommitmentAdmin` |
| POST | `/api/v1/admin/pages/sustainability/commitment/items` | admin (editor, superadmin) | `CommitmentItemWrite` | `CommitmentItemRead` |
| PUT | `/api/v1/admin/pages/sustainability/commitment/items/order` | admin (editor, superadmin) | `CommitmentReorder` | `CommitmentAdmin` |
| DELETE | `/api/v1/admin/pages/sustainability/commitment/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/sustainability/commitment/items/{item_id}` | admin (editor, superadmin) | `CommitmentItemWrite` | `CommitmentItemRead` |
| GET | `/api/v1/admin/pages/sustainability/cta` | admin (editor, superadmin) | — | `CtaRead` |
| PATCH | `/api/v1/admin/pages/sustainability/cta` | admin (editor, superadmin) | `CtaWrite` | `CtaRead` |
| GET | `/api/v1/admin/pages/sustainability/durability` | admin (editor, superadmin) | — | `DurabilityAdmin` |
| PUT | `/api/v1/admin/pages/sustainability/durability` | admin (editor, superadmin) | multipart form | `DurabilityAdmin` |
| GET | `/api/v1/admin/pages/sustainability/hero` | admin (editor, superadmin) | — | `SustainabilityHeroAdmin` |
| PUT | `/api/v1/admin/pages/sustainability/hero` | admin (editor, superadmin) | multipart form | `SustainabilityHeroAdmin` |
| GET | `/api/v1/admin/pages/sustainability/impact` | admin (editor, superadmin) | — | `ImpactAdmin` |
| PATCH | `/api/v1/admin/pages/sustainability/impact` | admin (editor, superadmin) | `ImpactCopyUpdate` | `ImpactAdmin` |
| POST | `/api/v1/admin/pages/sustainability/impact/items` | admin (editor, superadmin) | `ImpactItemWrite` | `ImpactItemRead` |
| PUT | `/api/v1/admin/pages/sustainability/impact/items/order` | admin (editor, superadmin) | `ImpactReorder` | `ImpactAdmin` |
| DELETE | `/api/v1/admin/pages/sustainability/impact/items/{item_id}` | admin (editor, superadmin) | — | `Message` |
| PATCH | `/api/v1/admin/pages/sustainability/impact/items/{item_id}` | admin (editor, superadmin) | `ImpactItemWrite` | `ImpactItemRead` |
| GET | `/api/v1/admin/pages/sustainability/origin` | admin (editor, superadmin) | — | `OriginAdmin` |
| PUT | `/api/v1/admin/pages/sustainability/origin` | admin (editor, superadmin) | multipart form | `OriginAdmin` |
| GET | `/api/v1/admin/pages/sustainability/quality` | admin (editor, superadmin) | — | `QualityAdmin` |
| PUT | `/api/v1/admin/pages/sustainability/quality` | admin (editor, superadmin) | multipart form | `QualityAdmin` |

## `admin/products`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/products` | admin (editor, superadmin) | — | `AdminProductList` |
| POST | `/api/v1/admin/products` | admin (editor, superadmin) | multipart form | `AdminProductRead` |
| DELETE | `/api/v1/admin/products/bulk` | admin (editor, superadmin) | `ProductBulkDelete` | `ProductBulkDeleteResult` |
| DELETE | `/api/v1/admin/products/{product_id}` | admin (editor, superadmin) | — | 204 No Content |
| GET | `/api/v1/admin/products/{product_id}` | admin (editor, superadmin) | — | `AdminProductRead` |
| PATCH | `/api/v1/admin/products/{product_id}` | admin (editor, superadmin) | multipart form | `AdminProductRead` |

## `admin/site/contact`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/site/contact` | admin (editor, superadmin) | — | `SiteContactAdmin` |
| PUT | `/api/v1/admin/site/contact` | admin (editor, superadmin) | `SiteContactWrite` | `SiteContactAdmin` |

## `admin/site/payment`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/admin/site/payment` | admin (editor, superadmin) | — | `PaymentSettingsAdmin` |
| POST | `/api/v1/admin/site/payment/qr` | admin (editor, superadmin) | multipart `image` (JPEG/PNG/WEBP/GIF, 5 MB) | `PaymentSettingsAdmin` |
| DELETE | `/api/v1/admin/site/payment/qr` | admin (editor, superadmin) | — | `PaymentSettingsAdmin` |

## `admin/site/footer`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| DELETE | `/api/v1/admin/site/footer` | admin (editor, superadmin) | — | `FooterAdmin` |
| GET | `/api/v1/admin/site/footer` | admin (editor, superadmin) | — | `FooterAdmin` |
| PUT | `/api/v1/admin/site/footer` | admin (editor, superadmin) | `FooterWrite` | `FooterAdmin` |
| POST | `/api/v1/admin/site/footer/logo` | admin (editor, superadmin) | multipart form | `ImageUploaded` |

## `admin/site/header`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| DELETE | `/api/v1/admin/site/header` | admin (editor, superadmin) | — | `HeaderAdmin` |
| GET | `/api/v1/admin/site/header` | admin (editor, superadmin) | — | `HeaderAdmin` |
| PUT | `/api/v1/admin/site/header` | admin (editor, superadmin) | `HeaderWrite` | `HeaderAdmin` |

## `auth`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/auth/change-password` | any signed-in staff | `PasswordChangeRequest` | `Message` |
| POST | `/api/v1/auth/login` | public | `LoginRequest` | `TokenPair` |
| POST | `/api/v1/auth/logout` | public | `RefreshRequest` | `Message` |
| GET | `/api/v1/auth/me` | any signed-in staff | — | `UserRead` |
| POST | `/api/v1/auth/refresh` | public | `RefreshRequest` | `TokenPair` |

## `cart`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| DELETE | `/api/v1/cart` | public | — | `CartRead` |
| GET | `/api/v1/cart` | public | — | `CartRead` |
| POST | `/api/v1/cart/items` | public | `CartItemCreate` | `CartRead` |
| DELETE | `/api/v1/cart/items/{item_id}` | public | — | `CartRead` |
| PATCH | `/api/v1/cart/items/{item_id}` | public | `CartItemUpdate` | `CartRead` |

## `categories`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/categories/tree` | public | — | `CategoryTree` |
| GET | `/api/v1/categories/{slug}` | public | — | `CategoryDetail` |
| GET | `/api/v1/categories/{slug}/products` | public | — | `PublicProductList` |

`CategoryTree` nodes include `updated_at` (ISO datetime) for sitemap `lastmod`.

## `delivery`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/delivery` | public | — | `DeliveryRatesRead` |

## `home/banner`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/banner` | public | — | `HomeBannerPublic` |

## `home/categories`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/categories` | public | — | `CategoryPublic` |

## `home/faq`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/faq` | public | — | `FaqPublic` |

## `home/featured`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/featured` | public | — | `FeaturedPublic` |

## `home/newsletter`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/newsletter` | public | — | `NewsletterPublic` |

## `home/media`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/media` | public | — | `MediaPublic or null` |

## `home/promo`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/promo` | public | — | `PromoPublic or null` |

## `home/reviews`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/reviews` | public | — | `ReviewPublic` |

## `home/showcase`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/showcase` | public | — | `ShowcasePublic` |

## `home/trust`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/home/trust` | public | — | `TrustPublic` |

## `inquiries`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/inquiries` | public | `InquiryCreate` | `InquiryReceipt` |

## `orders`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/orders` | public | `OrderCreate` | `OrderRead` |
| POST | `/api/v1/orders/lookup` | public | `OrderLookup` | `PublicOrderRead` |
| POST | `/api/v1/orders/quote` | public | `OrderQuoteRequest` | `QuoteRead` |

`OrderCreate` takes `payment_method` (`cod` default, or `bangla_qr`), `advance_percent` (25/50/75/100, only for `bangla_qr`) and `payment_reference` (transaction ID or sender number, required for `bangla_qr`; spaces removed, then 4–64 letters, digits, `+` or `-`). The amounts are never accepted from the client. `QuoteRead.bangla_qr_options` lists `{percent, advance, due}` for the total (empty when no QR is set). `OrderRead` and `PublicOrderRead` return `payment_method`, `advance_percent`, `advance_amount`, `due_amount`; `OrderRead` (placed order, admin) also returns `payment_reference`, `delivered_at`, and `returned_at`.

`OrderCreate.tracking` is optional: `{ "fbp": string|null, "fbc": string|null, "event_source_url": string|null }`. Each field is optional. A value that is not a string, is blank, or is longer than 500 characters is dropped. Unknown keys inside `tracking` are dropped. A missing `tracking`, or a `tracking` that is not an object, is ignored and the order is still placed. Other unknown fields on the order body are still `422`.

`POST /orders` returns `order_number` (same string as `number`) and `analytics_event_id` (`purchase_<order_number>`). When `META_PIXEL_ID` and `META_CAPI_TOKEN` are both set, a successful create also sends one Meta Conversions API `Purchase` with that event id after the order is committed. The response does not wait on Meta and does not change if Meta fails. A replay of the same `Idempotency-Key` returns the same ids and does not send again. `POST /orders/quote` and `POST /orders/lookup` do not accept `tracking` and do not return `analytics_event_id`.

## `pages/about`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/about/cta` | public | — | `CtaPublic` |
| GET | `/api/v1/pages/about/dresses` | public | — | `DressesPublic` |
| GET | `/api/v1/pages/about/hero` | public | — | `AboutHeroPublic` |
| GET | `/api/v1/pages/about/mission` | public | — | `MissionPublic` |
| GET | `/api/v1/pages/about/stats` | public | — | `StatsPublic` |
| GET | `/api/v1/pages/about/steps` | public | — | `StepsPublic` |
| GET | `/api/v1/pages/about/stories` | public | — | `StoriesPublic` |
| GET | `/api/v1/pages/about/values` | public | — | `ValuesPublic` |

## `pages/blogs`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/blogs/categories` | public | — | `CategoriesPublic` |
| GET | `/api/v1/pages/blogs/cta` | public | — | `CtaPublic` |
| GET | `/api/v1/pages/blogs/hero` | public | — | `HeroPublic` |
| GET | `/api/v1/pages/blogs/listing` | public | — | `ListingPublic` |
| GET | `/api/v1/pages/blogs/posts` | public | — | `PostsPublic` |
| GET | `/api/v1/pages/blogs/posts/{slug}` | public | — | `PostPublic` |
| GET | `/api/v1/pages/blogs/related` | public | — | `RelatedPublic` |

## `pages/contact`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/contact/details` | public | — | `DetailsPublic` |
| GET | `/api/v1/pages/contact/faq` | public | — | `FaqPublic` |
| GET | `/api/v1/pages/contact/form` | public | — | `FormPublic` |
| GET | `/api/v1/pages/contact/hero` | public | — | `HeroPublic` |
| GET | `/api/v1/pages/contact/support` | public | — | `SupportPublic` |

## `pages/faqs`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/faqs/callout` | public | — | `CalloutPublic` |
| GET | `/api/v1/pages/faqs/categories` | public | — | `CategoriesPublic` |
| GET | `/api/v1/pages/faqs/help` | public | — | `HelpPublic` |
| GET | `/api/v1/pages/faqs/hero` | public | — | `HeroPublic` |
| GET | `/api/v1/pages/faqs/items` | public | — | `ItemsPublic` |
| GET | `/api/v1/pages/faqs/listing` | public | — | `ListingPublic` |

## `pages/privacy`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/privacy/collection` | public | — | `CollectionPublic` |
| GET | `/api/v1/pages/privacy/contents` | public | — | `ContentsPublic` |
| GET | `/api/v1/pages/privacy/hero` | public | — | `HeroPublic` |
| GET | `/api/v1/pages/privacy/introduction` | public | — | `IntroductionPublic` |
| GET | `/api/v1/pages/privacy/rights` | public | — | `RightsPublic` |
| GET | `/api/v1/pages/privacy/sharing` | public | — | `SharingPublic` |
| GET | `/api/v1/pages/privacy/support` | public | — | `SupportPublic` |
| GET | `/api/v1/pages/privacy/usage` | public | — | `UsagePublic` |

## `pages/shipping`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/shipping/contents` | public | — | `ContentsPublic` |
| GET | `/api/v1/pages/shipping/faq` | public | — | `FaqPublic` |
| GET | `/api/v1/pages/shipping/hero` | public | — | `HeroPublic` |
| GET | `/api/v1/pages/shipping/payment` | public | — | `PaymentPublic` |
| GET | `/api/v1/pages/shipping/refund` | public | — | `RefundPublic` |
| GET | `/api/v1/pages/shipping/returns` | public | — | `ReturnsPublic` |
| GET | `/api/v1/pages/shipping/shipping` | public | — | `BlockPublic` |
| GET | `/api/v1/pages/shipping/support` | public | — | `SupportPublic` |

## `pages/sustainability`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/pages/sustainability/commitment` | public | — | `CommitmentPublic` |
| GET | `/api/v1/pages/sustainability/cta` | public | — | `CtaRead` |
| GET | `/api/v1/pages/sustainability/durability` | public | — | `DurabilityPublic` |
| GET | `/api/v1/pages/sustainability/hero` | public | — | `SustainabilityHeroPublic` |
| GET | `/api/v1/pages/sustainability/impact` | public | — | `ImpactPublic` |
| GET | `/api/v1/pages/sustainability/origin` | public | — | `OriginPublic` |
| GET | `/api/v1/pages/sustainability/quality` | public | — | `QualityPublic` |

## `products`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/products` | public | — | `PublicProductList` |
| GET | `/api/v1/products/by-slug/{slug}` | public | — | `PublicProductDetail` |
| GET | `/api/v1/products/{product_id}` | public | — | `PublicProductDetail` |

## `search`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/search` | public | — | `SearchResults` |

## `site/contact`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/site/contact` | public | — | `SiteContactPublic` |

## `site/payment`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/site/payment` | public (`Cache-Control: no-store`) | — | `PaymentSettingsPublic` (`bangla_qr_src` or `null`, `bangla_qr_enabled`) |

## `site/footer`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/site/footer` | public | — | `FooterPublic` |

## `site/header`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/site/header` | public | — | `HeaderPublic` |

## `users`

| Method | Path | Access | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/users` | admin (superadmin only) | — | `Page[UserRead]` |
| POST | `/api/v1/users` | admin (superadmin only) | `UserCreate` | `UserRead` |
| DELETE | `/api/v1/users/{user_id}` | admin (superadmin only) | — | 204 No Content |
| GET | `/api/v1/users/{user_id}` | admin (superadmin only) | — | `UserRead` |
| PATCH | `/api/v1/users/{user_id}` | admin (superadmin only) | `UserUpdate` | `UserRead` |
