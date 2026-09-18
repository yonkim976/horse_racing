# Supabase migration runbook

## Target architecture

- Cloud Run runs FastAPI, HTML rendering, collection jobs, and model inference.
- Supabase PostgreSQL is the single operational database.
- Browsers do not connect to Supabase directly.
- All application tables have RLS enabled and no `anon` or `authenticated` policy.
- The database password is stored in Google Secret Manager, never in Git or a browser bundle.

## Prepared source

The initial copy uses the frozen, verified snapshot:

```text
data/backups/after_historical_backfill_20260918.sqlite3
SHA-256 79708446f6aea3840c01589906c0c3e4d9ec744d94fc22b82c9edc83ce3dc322
```

Do not collect new data into this snapshot. New collection continues against the operational
SQLite database until the final cutover window.

## Project setup

1. Create a separate Supabase project in Seoul (`ap-northeast-2`). Do not reuse `fintor`.
2. Use a paid project and provision enough disk for the PostgreSQL tables, indexes, and WAL.
3. Apply `supabase/migrations/*_create_horse_racing_schema.sql`.
4. In **Connect**, select **Session pooler**, port `5432`, and copy the PostgreSQL URI.
5. Add `?sslmode=require` and percent-encode special characters in the password.

Store the URI only in the current terminal:

```bash
read -s SUPABASE_DB_URL
export SUPABASE_DB_URL
```

The variable must contain the full Session pooler URI. Do not paste it into chat, a tracked file,
shell history, or Cloud Run's plain-text environment variables.

## Initial copy

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv sync
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run \
  python scripts/migrate_sqlite_to_postgres.py
```

The importer:

- checks the SQLite snapshot before copying;
- rejects string-width, integer-range, and dynamic SQLite numeric-type mismatches before copying;
- streams tables in foreign-key order with PostgreSQL `COPY`;
- commits every 100,000 rows in primary-key order;
- proves that a partial target is an exact source-ID prefix before resuming it;
- skips tables whose source and target counts already match;
- resets all identity sequences;
- compares every source and target row count before succeeding.

## Completed initial load

- Project: `horse-racing-prod` (`xkykmhhkjtosptoibduo`), Seoul, Micro compute
- Source rows: `20,507,660` across 30 application tables
- Target rows: `20,507,660` across the same 30 tables
- PostgreSQL database size after indexes: about 3.8 GB
- Disk: auto-expanded from 8 GB to 12 GB during the load; Spend Cap remains enabled, so the
  organization Usage page currently reports that overages are not billed
- If Spend Cap is later disabled while 12 GB stays provisioned, the 4 GB above the included 8 GB
  is billed at $0.125/GB-month (up to $0.50/month, prorated hourly)
- PostgreSQL override: `max_wal_size=1GB`; `checkpoint_timeout` is back at its 5-minute default

The initial bulk load temporarily removed the four largest secondary indexes, restored their exact
definitions afterward, added covering indexes for the eight remaining foreign keys, and ran
`ANALYZE` after loading.

## Cutover

1. Stop collection jobs and writes to SQLite.
2. Run the final freshness audit.
3. If SQLite changed after the frozen snapshot, take a new immutable snapshot and import into a
   fresh empty Supabase project/database before switching traffic.
4. Put the Session pooler URI in Google Secret Manager and expose it to Cloud Run as
   `HORSE_RACING_DATABASE_URL`, using the SQLAlchemy scheme `postgresql+psycopg://`.
5. Deploy a Cloud Run revision with no traffic, run `horse-racing db-info`, `/health`, and dashboard
   smoke tests, then move traffic.
6. Keep SQLite read-only as rollback evidence until Supabase backups and restore have been tested.

## Security verification

After loading, verify that all application tables have RLS enabled, `anon` and `authenticated`
have no table/sequence grants, and Supabase Security Advisor has no exposed-table findings. The
prediction ledger's PostgreSQL triggers reject `UPDATE` and `DELETE`.

The initial verification found all 30 application tables with RLS enabled and zero client-role
table grants. `rls_enabled_no_policy` is expected while browsers are intentionally denied direct
database access; add narrowly scoped policies only when an authenticated browser feature is
designed.
