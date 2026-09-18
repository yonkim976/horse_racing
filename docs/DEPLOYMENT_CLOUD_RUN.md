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

## Operational separation

The public web service is deployed first. Long-running collection commands
such as `sync-latest` belong in separate Cloud Run Jobs. Raw source artifacts
must be copied to durable object storage before collection jobs are scheduled;
Cloud Run's local filesystem is ephemeral.
