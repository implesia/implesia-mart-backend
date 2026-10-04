# Deployment rollback

`implesia-mart-api` is the Render web service built from this repo's Dockerfile. A bad deploy goes back to the previous successful deploy's image. The database moves only when you downgrade it on purpose.

Render's rollback steps are documented at <https://render.com/docs/rollbacks>. If the schema itself must be recovered from a backup, use [`backup-restore.md`](backup-restore.md).

## Previous image

This service builds its image on Render. A rollback reuses that earlier build artifact. It does not pull a floating tag from a registry, so the image is the one from that deploy.

1. In the Render Dashboard, open `implesia-mart-api` and its Deploys page.
2. On the last healthy deploy, choose **Rollback**, then confirm.
3. A dashboard rollback turns automatic deploys off. Leave them off until the bad commit is no longer what the linked branch will ship. Turning them back on before that deploys the bad commit again.
4. Wait until the rollback is live. `GET /health/ready` must report the database and Redis as ok.
5. Render only keeps a limited number of recent build artifacts for the workspace plan. A deploy whose artifact is already gone cannot be selected.

The rollback uses the target deploy's start command, Docker command, health check path, instance count, and environment variables. It does not change the database.

If the new build fails, or the new instance never passes `/health/live`, Render leaves the previous instance in service. You do not need this manual rollback for that case. Check the database anyway: `scripts/start.sh` runs `alembic upgrade head` before the process listens, so a failed boot may already have migrated the shared database.

## Database migrations

`scripts/start.sh` runs `alembic upgrade head` and then Gunicorn. Boot never runs a downgrade.

Each file in `alembic/versions/` has a `downgrade()` that removes what that revision added. That removal deletes rows that existed only in the new tables or columns. Downgrading `0068` drops `audit_events`. Downgrading `0067` drops `refresh_tokens` and ends every refresh session.

### Choose the path

On the database the API is using, from the Render Shell of the deploy that contains the new revisions:

```bash
alembic current
```

Compare that revision with the head of the image you are returning to.

- The revisions match. Roll back the image only.
- The database is ahead by revisions from the bad deploy. Downgrade those revisions from the new image, then roll back the image. The old image does not contain the newer revision files. `alembic upgrade head` on that image fails while `alembic_version` still names a revision it cannot see.
- A downgrade would drop orders or other rows you still need. Restore from point-in-time recovery in [`backup-restore.md`](backup-restore.md) instead of downgrading.

### Downgrade one revision

Run this in the Shell of the image that introduced the revision, before the service rollback:

```bash
alembic current
alembic downgrade -1
alembic current
```

Repeat `-1` only for revisions that belong to the bad deploy. Stop when `alembic current` is the previous release's head. Then roll back the service. The old image's `alembic upgrade head` sees that revision and leaves the schema there.

Do this on production when a point-in-time recovery is already available. When the revision drops tables, run the same downgrade first on a restore-test database from [`backup-restore.md`](backup-restore.md).

## After the rollback

Confirm `/health/ready`, a staff login, and one catalog read. Turn automatic deploys back on only after the linked branch will deploy the fix.
