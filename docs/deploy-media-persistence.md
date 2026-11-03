# Media storage (Cloudflare R2)

Product photos, gallery videos, and CMS images are stored in Cloudflare R2
when the API has the five settings below. The bucket is `implesia-mart-media`.
Browsers load files from the public custom domain `https://media.implesia.com`.

The database and the storefront keep the old paths, `/media/<folder>/<name>`
(for example `/media/products/abc.jpg`). The object key in the bucket is the
same path without the `/media/` prefix: `products/abc.jpg`. `GET /media/...`
on the API answers `307` to `https://media.implesia.com/<folder>/<name>`.

New uploads set `Content-Type` from the file signature (`image/jpeg`,
`image/png`, `image/gif`, `image/webp`, `video/mp4`, `video/webm`). Replacing
a file always uses a new name, so those objects can be cached for a long time.

When all five settings are empty, the API writes the container directory
`/srv/media` (`media_root`) and serves it directly. That is the path tests
and local Compose use. A partial set (some of the five filled in) refuses to
start, so a deploy cannot quietly fall back to the container disk.

## Settings

Names only. Put the values in `.env.production` on the VPS (the compose file
already loads that file) or in the Render dashboard. Do not commit them.

| Variable | Example | What it is |
| --- | --- | --- |
| `S3_ENDPOINT_URL` | `https://<accountid>.r2.cloudflarestorage.com` | R2 S3 endpoint for the account. No path, no key in the URL. |
| `S3_BUCKET` | `implesia-mart-media` | Bucket name. |
| `S3_ACCESS_KEY_ID` | | R2 API token access key id. Object read and write on this bucket only. |
| `S3_SECRET_ACCESS_KEY` | | The matching secret. |
| `MEDIA_PUBLIC_BASE_URL` | `https://media.implesia.com` | Public origin. No path. `https` in production. |

The API uses path-style S3 requests and region `auto`, which is what R2 expects.

The custom domain must serve the bucket publicly. The API redirects to it and
does not proxy the file bytes. An `<img>` or `<video>` tag does not need a
CORS rule. Add a bucket CORS rule for GET only if some page reads the pixels
in JavaScript (for example drawing a video onto a canvas).

## Deploy on the VPS

Production is Docker Compose behind Caddy (`docker-compose.prod.yml`), on
72.60.199.155. The named volume `implesia-mart-media` is still mounted at
`/srv/media`. It is the fallback when the five settings are empty, and it is
the source of the one-time copy below. Leave it mounted until the checks pass.

1. In the Cloudflare dashboard, create an R2 API token that can read and write
   objects in `implesia-mart-media` and nothing else. Confirm
   `https://media.implesia.com` is attached to that bucket and is public.

2. Copy the files that are already on disk into the bucket **before** turning
   the settings on. The steps are in the next section. Do this while the
   running API is still serving `/srv/media`, so the site does not 404 during
   the copy.

3. Add the five variables to `.env.production` in the backend checkout. Keep
   that file out of git.

4. Deploy:

   ```sh
   git pull
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```

   `--env-file` is what Compose uses while reading the file. The container
   also receives `.env.production` through `env_file`. Do not also set the
   five names to empty values in the `environment:` block; an empty value
   there would override the file and turn storage back to local disk.

5. Run the copy once more after the new container is up. Anything uploaded
   between step 2 and the restart is still only on the volume.

6. Run the checks at the bottom of this file. After they pass, the volume is
   only a fallback and a backup of the old files. Do not delete it in the
   same change as the switch.

## Copy the old `/srv/media` into the bucket

Object keys must equal the directory names inside `/srv/media`:

```text
banners/<file>
products/<file>
categories/<file>
reviews/<file>
about/<file>
sustainability/<file>
blogs/<file>
promo/<file>
home-media/<file>
footer/<file>
```

Sync the **contents** of `/srv/media`, not a parent folder. A copy that adds
an extra `media/` or `srv/` prefix stores `media/banners/...`, and the API
will look for `banners/...`. Those are not the same key.

Export the volume, then upload. From the backend checkout on the server:

```sh
docker compose -f docker-compose.prod.yml cp api:/srv/media /tmp/media-export
```

`/tmp/media-export` then contains `banners/`, `products/`, and the other
folders. The Docker volume path
`/var/lib/docker/volumes/implesia-mart-media/_data` is the same tree if you
would rather read it in place.

Either tool below keeps those relative paths as the object keys.

### rclone

Configure an S3 remote named `r2` with provider Cloudflare, the endpoint from
`S3_ENDPOINT_URL`, and the token's key id and secret. Prefer `rclone config`
or the `RCLONE_S3_*` environment variables over pasting the secret into the
shell history.

```sh
rclone sync /tmp/media-export r2:implesia-mart-media --progress
```

`sync` uploads files that are missing or changed. It also deletes bucket
objects that are not in the export. Use `rclone copy` instead of `sync` if
the bucket already holds newer uploads you must keep.

### aws s3 sync

The AWS CLI reads `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` from the
environment. Point those at the R2 token for this command only.

```sh
aws s3 sync /tmp/media-export s3://implesia-mart-media \
  --endpoint-url "$S3_ENDPOINT_URL" \
  --region auto
```

`aws s3 sync` does not delete objects that exist only in the bucket.

### Content type of the copied files

New uploads set `Content-Type` in the API. A copied file gets whatever the
sync tool guesses from the extension. After the copy, check a photo and a
video:

```sh
curl -sI "https://media.implesia.com/banners/<file>.png" | head -n 20
curl -sI "https://media.implesia.com/products/<file>.mp4" | head -n 20
```

You want `content-type: image/png` (or jpeg, gif, webp) and `video/mp4` or
`video/webm`. `application/octet-stream` makes browsers download the file
instead of showing it. Re-copy that object with an explicit type, for example:

```sh
aws s3 cp "/tmp/media-export/products/<file>.jpg" \
  "s3://implesia-mart-media/products/<file>.jpg" \
  --endpoint-url "$S3_ENDPOINT_URL" \
  --region auto \
  --content-type image/jpeg
```

## Files recovered on 17 Oct 2026

Those six files were recovered into `banners/` and `products/` with their
original names. If they are already in the volume, the copy above includes
them. If they are only on the developer PC:

```sh
rclone copy ~/Downloads/implesia-qa/recovered-media r2:implesia-mart-media --progress
```

The folder layout on the PC is already `banners/` and `products/`, which is
the same key layout.

## Render

`render.yaml` lists the same five variables. `S3_BUCKET` and
`MEDIA_PUBLIC_BASE_URL` are filled in. `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`,
and `S3_SECRET_ACCESS_KEY` are `sync: false`: enter them in the service
dashboard, not in git. Set all five, or leave the endpoint and both keys
empty and clear the other two as well. A mix prevents startup.

## Check

After the new container is running and the second copy has finished:

```sh
# The API redirects. The public host has the object.
curl -sI "https://mart-api.implesia.com/media/banners/2a57e386d747472c8dfb61d019e6805e.png" | head -n 15
curl -sI "https://media.implesia.com/banners/2a57e386d747472c8dfb61d019e6805e.png" | head -n 15
```

The first response is `307` and its `location` is the second URL. The second
response is `200` with an image content type. Repeat for one product image
and, if you have one, an `.mp4` under `products/` or `home-media/`.

Upload a new image in the admin, reload the page, then recreate the container
without touching the bucket:

```sh
docker compose -f docker-compose.prod.yml up -d --force-recreate api
```

The new file still loads. That is the check that a deploy no longer deletes
uploads.

Cloudflare may still be holding an old `404` for
`https://mart-api.implesia.com/media/*`. Purge that prefix if a file you just
copied still 404s on the API host while the public media URL returns 200.

Deleting a product, or replacing its photo, deletes the matching object in
the bucket. The database row never stored the R2 URL, only `/media/...`.
