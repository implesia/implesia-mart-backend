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
| GET | `/api/v1/admin/orders` | admin (editor, superadmin) | — | `AdminOrderList` |
| GET | `/api/v1/admin/orders/{order_id}` | admin (editor, superadmin) | — | `OrderRead` |
| PATCH | `/api/v1/admin/orders/{order_id}` | admin (editor, superadmin) | `OrderUpdate` | `OrderRead` |

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
