# TODO

Open items found in the code and in recent work. Remove an item when it is done.

## Open

- **Meta Purchase events are not live**: the server sends a Conversions API `Purchase` only when `META_PIXEL_ID` and `META_CAPI_TOKEN` are set on the API host. `META_TEST_EVENT_CODE` is for Events Manager test events. Leave the token out of the repo. Until those are set, checkout still works and the order response still includes `analytics_event_id`.
- **Sales reports after migration 0094**: back up the database, merge PR #8 (migration 0092), then PR #9 (migration 0093), then the reports PR, and run `alembic upgrade head`. 0094 only adds nullable columns and indexes. It does not rewrite old orders. Do not run it against production from a laptop. There is no `cancelled_at`: the delivery report counts a cancellation by `updated_at` while the status is `cancelled`, so a later courier or tracking edit moves that day.
- **Opening stock after migration 0093**: back up the database, merge the cost-price PR (#8) first, then this ledger, run `alembic upgrade head`, then run opening stock once (`POST /api/v1/admin/inventory/opening-stock` or `python -m scripts.opening_stock`). Running it twice does not duplicate rows. Do this while orders are quiet; the command locks each product row.
- **PATCH product errors**: `PATCH /api/v1/admin/products/{id}` still returns the default 422 envelope with English messages. Create (`POST`) already returns the Bengali `{"errors": [{"field","message","fix"}]}` contract. Bring update in line and tell the frontend.
- **Browser verification**: the admin bulk-delete UI has passed lint, type check, build and curl checks but has not had a full manual browser walkthrough.
- **Upload size behind the production proxy**: videos are capped at 50 MB each by the API, and the frontend BFF allows request bodies up to 110 MB. Confirm the production reverse proxy / Cloudflare limit accepts a full gallery request of that size.
- **Gallery order after save**: newly uploaded files are appended after existing gallery items, so the order the admin arranged can change after save.
- **Bulk delete and orders**: deleting products that appear in past orders is allowed (order lines keep name and price, lose the product link). Decide whether that should need extra confirmation.

- **Max quantity exposes low stock**: `max_per_order` / `max_quantity` are min(limit, stock), so a stock count below the limit is visible to shoppers. Decide whether that is acceptable or whether to expose only the limit and refuse at cart time.
- **Product cards**: list/card discount badges come from `compare_at_price` (= base %, or the cheapest variant's compare-at); they do not show quantity tiers (by design). For variant products the badge shows the cheapest variant's %, not the largest.
- **Slug race**: slug uniqueness against other products and redirect rows is checked in the service, not by a DB constraint, so two simultaneous saves could collide (the unique index on `products.slug` still blocks two products with the same current slug).
- **Transliteration is approximate**: Bengali schwa deletion is not modelled fully (e.g. "আয়না" → `ayona`). Admins can edit the slug after create; improve the rules if needed.
- **Category `updated_at`** changes only when the category row changes, not when its products change; the storefront sitemap uses it as is.
- **Home media orphans**: a file uploaded through `POST /admin/home/media/image|video` whose save then fails (validation error, closed tab) stays in the bucket or on disk; nothing sweeps unreferenced files in `home-media/` (same as other CMS uploads).
- **R2 copy**: this change does not upload the files already on the VPS volume. Run the copy in `docs/deploy-media-persistence.md`, then the named volume is only a fallback.

## Code comments

- No `TODO` / `FIXME` comments in `app/`, `tests/` or `scripts/` as of 2026-11-02.
