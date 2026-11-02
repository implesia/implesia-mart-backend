# TODO

Open items found in the code and in recent work. Remove an item when it is done.

## Open

- **PATCH product errors**: `PATCH /api/v1/admin/products/{id}` still returns the default 422 envelope with English messages. Create (`POST`) already returns the Bengali `{"errors": [{"field","message","fix"}]}` contract. Bring update in line and tell the frontend.
- **Browser verification**: the admin bulk-delete UI has passed lint, type check, build and curl checks but has not had a full manual browser walkthrough.
- **Upload size behind the production proxy**: videos are capped at 50 MB each by the API, and the frontend BFF allows request bodies up to 110 MB. Confirm the production reverse proxy / Cloudflare limit accepts a full gallery request of that size.
- **Gallery order after save**: newly uploaded files are appended after existing gallery items, so the order the admin arranged can change after save.
- **Bulk delete and orders**: deleting products that appear in past orders is allowed (order lines keep name and price, lose the product link). Decide whether that should need extra confirmation.

- **Max quantity exposes low stock**: `max_per_order` / `max_quantity` are min(limit, stock), so a stock count below the limit is visible to shoppers. Decide whether that is acceptable or whether to expose only the limit and refuse at cart time.
- **Product cards**: list/card discount badges still come from `compare_at_price` (= base %); they do not show quantity tiers.

## Code comments

- No `TODO` / `FIXME` comments in `app/`, `tests/` or `scripts/` as of 2026-11-02.
