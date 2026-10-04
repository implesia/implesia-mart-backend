# Production database backup and restore

The catalog, accounts, and orders live in Render Postgres (`implesia-mart-db`, database `implesia_mart`, region Singapore). Redis holds rate-limit counters only. Restoring Postgres is the recovery. Restoring Redis is not required.

Render's current behavior is documented at <https://render.com/docs/postgresql-backups> and <https://render.com/docs/free>.

## Before go-live

`render.yaml` still requests `plan: free`. A Free Render Postgres database has no backups and expires 30 days after creation. After that, Render keeps it for a 14-day grace period and then deletes it.

Production uses a paid Render Postgres instance. Paid instances get continuous point-in-time recovery with no extra job to turn on. Upgrade the database in the Render Dashboard before real orders exist. Moving from Hobby to Pro later does not fill in the older recovery window; the longer window starts from the upgrade.

Local `docker compose` data is disposable development data. It is not a copy of production.

## Automated backup

Paid Render Postgres is backed up continuously for point-in-time recovery.

| Workspace plan | How far back a restore can go |
| -------------- | ----------------------------- |
| Hobby          | 3 days                        |
| Pro or higher  | 7 days                        |

The newest restorable moment is about ten minutes behind the present. Render creates a new database for the recovery. The original instance stays up until you switch the API over.

## Retention

| Copy                     | Where it lives                   | How long it is kept                      |
| ------------------------ | -------------------------------- | ---------------------------------------- |
| Point-in-time recovery   | Render, on the paid database     | 3 days on Hobby, 7 days on Pro or higher |
| Logical export           | Render Recovery page             | 7 days after you create it               |
| Weekly off-platform copy | Encrypted storage outside Render | 30 days                                  |

Once a week, open the database Recovery page, choose **Create export**, download the `.dir.tar.gz`, and store it outside Render. Delete off-platform copies older than 30 days. Render deletes its own export after 7 days, so the weekly download is what covers a bad week that outlasts the recovery window.

A dump contains customers, orders, and password hashes. Keep it out of git, chat, and the application image.

## Restore

Restore into a new database. Leave the live `implesia-mart-db` in place until the new one has been checked.

### Recent loss: point-in-time recovery

Use this for a dropped table or bad write inside the recovery window.

1. In the Render Dashboard, open `implesia-mart-db` and its Recovery page.
2. Choose **Restore Database**.
3. Name the new instance `implesia-mart-db-recovery`.
4. Pick a time inside the window, at least ten minutes ago, from before the bad change.
5. Copy the existing settings so the plan and network rules match.
6. Start recovery. Wait until the new instance is Available.
7. Connect with the **PSQL Command** on the new instance's Info page and run the checks below.
8. On the `implesia-mart-api` service, set `DATABASE_URL` to the new instance's internal connection string.
9. Redeploy the API. `scripts/start.sh` applies migrations. If the admin user is already in the restored data, startup promotes that user and does not change the password. The home banner is seeded only when the table is empty.
10. Confirm `GET /health/ready` returns `database: ok`. Place no orders until that check passes.
11. After the API is serving the recovered data, suspend or delete the old instance.

### Older loss: logical export

Use this when the recovery window has already moved past the data you need. The export is older than point-in-time recovery, so prefer point-in-time recovery when the time you need is still inside the window.

1. Download the export from the Recovery page, or use the weekly off-platform copy.
2. Create a new empty paid Render Postgres instance. Do not load the file into `implesia-mart-db` or into the local Compose database.
3. Install PostgreSQL client tools that match the server major version.
4. Extract and restore with the new instance's **external** URL:

```bash
tar -zxvf 2026-01-15T00_00Z.dir.tar.gz
pg_restore \
  --dbname="$EXTERNAL_DATABASE_URL" \
  --verbose \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --format=directory \
  2026-01-15T00:00Z/implesia_mart
```

A plain `pg_dump` SQL file is loaded with `psql --dbname="$EXTERNAL_DATABASE_URL" -f implesia_mart.sql` into that same empty database.

5. Point `implesia-mart-api` at the new internal URL, redeploy, and run the same checks as a point-in-time recovery.

A one-off local export, if the dashboard export is unavailable:

```bash
pg_dump \
  --dbname="$EXTERNAL_DATABASE_URL" \
  -n public \
  --no-owner \
  --format=directory \
  --jobs=4 \
  -f implesia_mart.dump
```

## Checks after every restore

Run these on the new database before the API switch, and again after `/health/ready` is ok.

```sql
SELECT version_num FROM alembic_version;
SELECT count(*) FROM users;
SELECT count(*) FROM products;
SELECT count(*) FROM orders;
```

`alembic_version` must match the migration head of the release that is about to boot. Counts must be in the range you expect for that backup time. Open one known product and one known order in the admin after the switch.

## Monthly restore test

Once a month, prove that a backup can be read. This uses a throwaway instance, never the live database and never the local Compose volume.

1. Start a point-in-time recovery to `implesia-mart-db-restore-test`, or restore the latest off-platform export into a new empty instance.
2. Run the checks above. Confirm the API is still pointed at the live database.
3. Record the date, which backup you used, the three counts, and pass or fail. Keep that note outside the git repo. Do not include a connection string.
4. Delete `implesia-mart-db-restore-test` the same day.

A failed test means production does not have a usable backup until a fresh export restores cleanly.
