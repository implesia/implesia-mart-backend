# Changelog

Newest first. Every task adds an entry: date, what changed, files touched, and anything the frontend repo (`implesia-mart`) must change.

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
