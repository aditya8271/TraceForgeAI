# TraceForge AI cloud deployment handoff

Deployment is not authorized or performed. Cloud SQL is the smallest reliable change for the existing SQLite-backed case, decision, review, and audit workflows: use the existing FastAPI service with PostgreSQL through `DATABASE_URL`; leave the local SQLite file intact as the migration source. Cloud Run's writable filesystem is temporary, so SQLite must not be used there. The service deliberately returns an unavailable health response if Cloud Run starts without PostgreSQL.

## Before provisioning anything

1. Resolve the API access perimeter with the project owner. Firebase Hosting static assets and a browser-callable Cloud Run API do not make a secret API key safe to ship to browsers. The current application has no authenticated user identity; actor labels are analyst-entered, not verified. Do not enable unauthenticated Cloud Run access for case decisions. If adding Firebase Auth is prohibited, choose and configure a supported perimeter such as an external HTTPS load balancer with Cloud Armor IP restrictions for a known analyst network, or another approved identity-aware gateway. CORS restricts browser origins but is not authentication and does not stop direct HTTP clients. Do not expose the API until this decision is made.
2. Confirm the Google Cloud project, region, approved analyst access method, expected traffic, retention, backup/PITR requirements, and spending budget. No project/region is configured in this repository.
3. Install and authenticate the Cloud SDK, Docker, and Firebase CLI on the deployment workstation. This workspace had no Firebase CLI or Docker CLI; `gcloud` was available but had no selected project. No resource, API, billing setting, or deployment was changed.
4. Make a protected backup of `data/replay/investigations.db` and `data/intelligence/` before migration. Keep SQLite unchanged until migration has been verified. The migration script is additive and idempotent for identical rows; it aborts on conflicting primary keys rather than overwriting target data.

## Local variables

Copy `.env.example` to a private local `.env` only for local work. Never commit it. Keep `DATABASE_URL` blank for SQLite. Configure production values from Cloud Run environment settings and Secret Manager references; never pass key values on a command line or print them.

Required production settings:

- `DATABASE_URL`: PostgreSQL connection string. Prefer Cloud SQL attachment/socket or private IP; store credentials in Secret Manager. Do not use a public database address.
- `GEMINI_API_KEY`: Secret Manager value. Backup Gemini keys are optional and should not be used to bypass quota enforcement.
- `TRACEFORGE_CORS_ORIGINS`: exact Firebase Hosting origin(s), comma-separated. Remove localhost origins in production.
- `TRACEFORGE_NPCI_AUTO_REFRESH=false`: preserve the current cache and avoid uncontrolled source polling; refresh manually after confirming permitted source access.
- Optional bounded controls: `TRACEFORGE_MAX_REQUEST_BYTES` (default 2,200,000; hard max 10,000,000), `TRACEFORGE_GEMINI_MAX_REQUESTS_PER_MINUTE` (default 10 across service instances), `TRACEFORGE_GEMINI_TIMEOUT_SECONDS` (default 30, max 120), `DB_CONNECT_TIMEOUT_SECONDS` (default 5, max 30).
- `PORT` is supplied by Cloud Run. The Docker command binds to `0.0.0.0:${PORT:-8080}` and runs as non-root.

The request cap bounds body memory, and the database-backed Gemini counter bounds aggregate calls per service per minute. These controls reduce accidental usage; without an identity perimeter they do not impose per-analyst quotas or prevent all abuse. PostgreSQL connectivity and Gemini outages return service errors; case writes are transactional. No retries are added to the blocked NPCI source.

## Build and migrate

1. Create Cloud SQL PostgreSQL with backups/PITR and private connectivity approved by the owner. Attach it to Cloud Run. Create a least-privilege runtime database role and a separate migration role.
2. Start the Cloud SQL Auth Proxy locally (or use an approved private connection), then set `DATABASE_URL` in the current PowerShell session without echoing it. Example shape only: `postgresql://USER:PASSWORD@127.0.0.1:5432/traceforge`.
3. From the repository root, run `python -m scripts.migrate_sqlite_to_postgres --source-db data/replay/investigations.db --public-data-dir data/intelligence`. It applies numbered SQL files in `migrations/`, copies the five existing SQLite tables and public aggregate cache/status, and prints counts without row contents or credentials. Repeat only against the same target or after resolving a reported conflict. Verify counts and a sampled case/audit history using a protected database client.
4. Build and deploy the API only after the API access perimeter is ready. Example sequence (replace placeholders; never add `--allow-unauthenticated`): `gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT/REPOSITORY/traceforge-api:VERSION` then deploy the image to Cloud Run with the Cloud SQL instance attachment, Secret Manager references for `DATABASE_URL` and `GEMINI_API_KEY`, exact CORS origin, bounded request settings, and ingress/IAM policy selected in step 1. Set concurrency and instance limits based on expected load and budget.
5. Verify `/api/health` reports `status: ok` and `storage: postgresql`; create a test case, decision and audit event, read them back, then remove only the explicitly identified test record using the application's supported case operation. Check Cloud Run logs for errors without logging request bodies or secrets.
6. Build the existing static Next.js app with the backend URL baked in: `$env:NEXT_PUBLIC_API_URL='https://APPROVED_API_HOST'; npm --prefix frontend ci; npm --prefix frontend run build`. Confirm `frontend/out` was generated, then configure Firebase Hosting for the correct project and deploy Hosting only with `firebase deploy --only hosting`. This app uses `output: 'export'` and is compatible with static Firebase Hosting; it does not use server-side Next.js routes/functions.
7. Run browser checks from the actual Hosting origin for health, alerts, case create/update, review, audit, and public-data states. Verify CORS and gateway policy independently; do not treat a successful static deployment as evidence the API is protected.

## Rollback and data safety

For an application rollback, redeploy the previous immutable Cloud Run image while keeping Cloud SQL and its records. Schema changes are additive and have no destructive down migration. Do not point a rolled-back service at the old SQLite copy after PostgreSQL has accepted writes; doing so would hide newer cases and audit records. Pause writes, take a Cloud SQL backup, then plan a separately reviewed reconciliation/export before any storage rollback. Firebase Hosting can be rolled back to its prior release in the Firebase console/CLI. Keep the source SQLite and original public-data files as protected backup until the owner confirms migration and retention.

## Costs and limitations

Expected services are Cloud Run, Artifact Registry/Cloud Build, Cloud SQL for PostgreSQL, Secret Manager, Firebase Hosting, Cloud Logging/Monitoring, and potentially a load balancer/Cloud Armor or identity-aware gateway. Cloud SQL has ongoing instance/storage/backup charges; Cloud Run, registry/build, networking, logging, secrets, Firebase usage, and Gemini API usage depend on region and volume. Exact cost is NOT TESTED / not estimable until region, instance size, traffic, retention, and access perimeter are chosen. Review current [Cloud SQL pricing](https://cloud.google.com/sql/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), [Firebase Hosting quotas and pricing](https://firebase.google.com/docs/hosting/usage-quotas-pricing), and [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) before provisioning.

The Firebase app is a static client-rendered export today. It can call the Cloud Run API directly only after the access perimeter is decided. No authentication was added. Existing `auth_users` and `firebase_roles` tables are retained by migration but are not enabled as authentication. PostgreSQL migration behavior has automated SQLite and static schema coverage, but no live PostgreSQL service was available here; a target-database migration rehearsal remains required.
