# Persistent media for the production API

The API stores uploads (banners, products, categories, about, sustainability,
reviews) on local disk at `/srv/media` inside the container (`media_root`).
Without a persistent mount, rebuilding or recreating the container deletes every
upload. That happened after 15 Oct 2026: six files uploaded that day returned 404.

The Dockerfile already creates `/srv/media` owned by `appuser` (uid 1000), so a
fresh named volume is writable on first mount.

## Docker Compose (VPS 72.60.199.155, Caddy in front)

1. On the server, in the backend checkout, find the current container and save
   whatever media it still holds before changing anything:

   ```sh
   docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}'
   docker inspect <api-container> --format '{{json .Mounts}}'
   docker cp <api-container>:/srv/media ./media-backup-$(date +%F)
   ```

2. Deploy with the production compose file (named volume `implesia-mart-media`):

   ```sh
   git pull
   cp -r ./media-backup-<date>/. /tmp/media-seed/   # optional, see step 3
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```

   `.env.production` holds the same variables the current container uses
   (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `CORS_ORIGINS`, ...). Keep it out of git.
   If the old container used another host port, set `API_HOST_PORT` so Caddy's
   `reverse_proxy` target is unchanged, or update the Caddyfile.

3. Copy the saved media and the recovered files into the volume:

   ```sh
   docker compose -f docker-compose.prod.yml cp ./media-backup-<date>/. api:/srv/media/
   docker compose -f docker-compose.prod.yml exec -u 0 api chown -R appuser:appuser /srv/media
   ```

## Coolify / Dokploy

Add a persistent storage (volume mount) on the API service with destination
path `/srv/media`, then redeploy. Copy files in with `docker cp` into the new
container as in step 3 (find it with `docker ps`).

## Restoring the six files recovered on 17 Oct 2026

The originals were recovered from a browser cache into
`~/Downloads/implesia-qa/recovered-media/` on the developer PC, laid out as
`banners/` and `products/` with the exact stored filenames.

From the PC:

```sh
scp -r ~/Downloads/implesia-qa/recovered-media <user>@72.60.199.155:/tmp/recovered-media
```

On the server:

```sh
cd <backend checkout>
docker compose -f docker-compose.prod.yml cp /tmp/recovered-media/. api:/srv/media/
docker compose -f docker-compose.prod.yml exec -u 0 api chown -R appuser:appuser /srv/media
```

Check (each should print 200):

```sh
for f in banners/2a57e386d747472c8dfb61d019e6805e.png banners/638665125fff4882b7b1ad2d08ed87ee.png \
         banners/8bfb274495c44ccca2dd0990bc90f9a8.png products/0201bb373dff4d53ab0965ac0391cb92.png \
         products/85b3d660c57244e4b411a26f11a1fdb2.png products/cf765125b8fc41e4a4739f2181e9e69e.png; do
  curl -s -o /dev/null -w "%{http_code} $f\n" "https://mart-api.implesia.com/media/$f?v=restore"
done
```

Cloudflare may still hold the cached 404 for the plain URL for up to 4 hours;
purge `https://mart-api.implesia.com/media/*` in the Cloudflare dashboard if needed.

## Verify persistence

```sh
docker compose -f docker-compose.prod.yml up -d --force-recreate api
curl -s -o /dev/null -w "%{http_code}\n" https://mart-api.implesia.com/media/banners/2a57e386d747472c8dfb61d019e6805e.png?v=recreate
```

Still 200 after a recreate means uploads survive deploys.
