# Mapilog Cloud Run deployment

## Production resources

- Google Cloud project: `mapilog-509017`
- Cloud Run service: `mapilog`
- Region: `asia-northeast1` (Tokyo)
- Artifact Registry repository: `mapilog`
- Canonical domain: `mapilog.xyz`
- Alias domain: `www.mapilog.xyz`
- Database: Supabase PostgreSQL through a pooled SSL connection

## Runtime contract

The container runs `horse_racing.web.app:app` with Uvicorn, listens on
`0.0.0.0`, and uses Cloud Run's `PORT` variable. The production database URL
is supplied from Secret Manager as `HORSE_RACING_DATABASE_URL`; it must never
be committed or stored as a plain Cloud Run environment variable.

The web process now uses its own engine: PostgreSQL transactions are READ ONLY,
with a 15-second **per-statement** timeout, a 3-second lock timeout and a
20-second idle-in-transaction timeout. SQLite web connections use `query_only`.
Collectors and migrations retain their existing writable engine and settings.
These guards do not impose a total HTTP deadline or a billing cap.

Prefer a dedicated SELECT-only login supplied as the Secret Manager binding
`HORSE_RACING_WEB_DATABASE_URL`. When absent, the web process uses
`HORSE_RACING_DATABASE_URL` with the transaction guards above. This fallback
does **not** remove privileges from an existing `postgres` credential. A separate
login requires explicit table grants and an RLS policy compatible with backend
reads; do not grant `BYPASSRLS` or loosen `anon`/`authenticated` as a shortcut.

The web image is digest-pinned (same base as the jobs image) and runs as UID/GID
10001, with `/app/data` writable for local SQLite fallback. Source and
dependencies remain root-owned. Rebuild and smoke-test the image before release.

The packaged `src/horse_racing/web/data/horse_evaluation_v1.json` is required by
horse detail pages. Both upload/build ignore files must preserve this directory:
exclude root `/data/`, not every directory named `data`. The Docker build fails
if this reference file is absent. Include a real horse detail request in the
private container smoke test before routing any production traffic.

Keep Uvicorn `--no-proxy-headers`. Do not enable wildcard forwarded-header trust
to solve shared-IP rate limiting. Verify real client identity from two separate
networks against a protected candidate revision before configuring precise
trusted proxy CIDRs or an authenticated origin proxy. Neither has been verified
by local request tests. Never expose a public diagnostics route containing IPs,
headers, credentials or configuration values.

## First deployment

1. Build and push the image with Cloud Build.
2. Deploy a no-traffic Cloud Run revision with the database secret attached.
3. Verify `/health`, the dashboard, and a representative race page.
4. Move traffic to the verified revision and allow public invocation.
5. Create direct Cloud Run domain mappings for `mapilog.xyz` and
   `www.mapilog.xyz`.
6. Add exactly the DNS records returned by Cloud Run at the authoritative DNS
   provider, then wait for domain routing and the managed certificates to be
   ready.

## Continuous deployment

`cloudbuild.yaml` builds, pushes, and deploys the service. A repository trigger
must target the protected `main` branch. Secret bindings and service-level
settings persist when the trigger updates only the container image.

## Feedback writes

The floating feedback form posts JSON to `/api/feedback`; `/api/feedback/token`
provides a signed one-hour CSRF token and an HttpOnly, SameSite=Lax anonymous
cookie scoped to the feedback API (seven-day lifetime). Neither endpoint is
cached. Email is optional. No feedback or email is exposed by a public read API.

Production requires these **independent** Secret Manager bindings:

- `HORSE_RACING_FEEDBACK_DATABASE_URL`: `mapilog-feedback-database-url`
- `HORSE_RACING_FEEDBACK_SECRET`: `mapilog-feedback-signing-key`

The dedicated `mapilog_feedback_writer` login can INSERT only into
`mapilog_feedback.entries`, and SELECT only request IDs, timestamps and hashes
for deduplication and quotas. It cannot read messages/emails, UPDATE/DELETE
feedback, or write racing tables. Both RLS and private schema grants apply.
The existing racing read-only engine and collector credentials are unchanged.
The feedback engine reserves at most one connection per instance.

The submitter's cookie is hashed with a secret; IP addresses are not stored in
feedback. Limits are five submissions per browser per hour, twenty per day,
and one thousand total per rolling day, serialized with a transaction advisory
lock. A UUID request ID makes retries idempotent. Input/body limits, origin
validation, signed tokens, a honeypot and bounded in-memory request limits run
before insertion. Browser drafts remain in memory only.

Operators read submitted opinions through the Supabase SQL editor, using their
existing administrative account, for example:

```sql
select request_id, created_at, category, message, email, page_path
from mapilog_feedback.entries
order by created_at desc
limit 100;
```

`pg_cron` job `mapilog-feedback-retention` deletes entries older than seven days
hourly. Database backups follow the database provider's retention settings.
Local development uses a separate `data/feedback.sqlite3` when no feedback URL
is supplied. A Cloud Run process never silently falls back to local storage.

## Collection jobs

The public web service is deployed first. Long-running collection commands
such as `sync-latest` belong in separate Cloud Run Jobs. Raw source artifacts
must be copied to durable object storage before collection jobs are scheduled;
Cloud Run's local filesystem is ephemeral.
