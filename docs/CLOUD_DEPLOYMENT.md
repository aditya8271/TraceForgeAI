# Google Cloud Run deployment readiness

No cloud resources are created or deployed by this repository workflow. This guide describes the existing architecture and the explicit steps an owner must complete.

## Runtime architecture

- The [Dockerfile](../Dockerfile) builds the **FastAPI API only**. It does not run Next.js, Streamlit, model training, transaction replay, or database migration at startup.
- The Next.js application uses `output: "export"` and is a static client application. Build it with the production API URL in `NEXT_PUBLIC_API_URL` and host the generated `frontend/out/` separately (the existing Hosting setup uses Firebase Hosting).
- API and browser assets are separate origins. Set `TRACEFORGE_CORS_ORIGINS` to the exact HTTPS Hosting origin(s). CORS is not authentication.
- Cloud Run's container filesystem is ephemeral. PostgreSQL is required for durable cases, analyst decisions, audit history, and public-data cache. The API never automatically migrates a schema or copies the local SQLite database.
- Historical and synthetic data, feature exports, local SQLite databases, and joblib models are ignored by Git. They are not included in the API image. Most API routes can start without them; routes that need absent datasets return HTTP 503 with a setup diagnostic.
- Joblib models and feature files are consumed by the separate local Streamlit/research workflow. The FastAPI deployment currently has no model-serving route and does not require those files.

## Exact local prerequisites

- Python 3.14.7 (the image uses `python:3.14.7-slim`), with project dependencies installed in an isolated environment.
- Node.js 24.21.0 (`.nvmrc`) and npm, using the committed `frontend/package-lock.json`.
- Docker Engine running, for local container build and smoke test.
- Google Cloud CLI, authenticated to the intended project, and Firebase CLI for the existing Hosting target, only when the owner is ready to deploy.
- An approved Google Cloud project and region; Cloud SQL for PostgreSQL; Secret Manager; and an approved API access perimeter. No project, region, database instance, or access boundary is configured here.
- If historical API routes are required, an owner-supplied private runtime asset source with the exact files listed under [Runtime data and models](#runtime-data-and-models).

## Local checks and builds

From the repository root, run the Python suite and compile check using the project's interpreter, then install frontend dependencies only from the committed lockfile:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-api.txt -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
npm --prefix frontend ci
$env:NEXT_PUBLIC_API_URL = 'https://YOUR-API-ORIGIN'
npm --prefix frontend run build
```

`requirements-api.txt` pins direct API runtime dependencies; `requirements-api.lock` pins the complete API dependency graph used in the image. `requirements.txt` contains the broader local research/test environment. To intentionally update the API graph, review direct version changes and regenerate the lock with `pip-compile --output-file=requirements-api.lock requirements-api.txt`, then run tests/builds. Do not commit virtual environments or installed package inventories.

Build and run the API container locally (no datasets are copied into the image):

```powershell
docker build -t traceforge-api:local .
docker run --rm -p 8080:8080 -e TRACEFORGE_CORS_ORIGINS=http://localhost:3000 traceforge-api:local
```

In another terminal, check `http://localhost:8080/api/health`. This liveness endpoint does not open a database, call Gemini, scan datasets, or run migrations. `/api/ready` checks persistent storage and the already-applied PostgreSQL schema; it is expected to fail until a database is configured. Local `DATABASE_URL` may be omitted for local SQLite development only.

The frontend build must receive the final HTTPS API URL because `NEXT_PUBLIC_API_URL` is compiled into the static JavaScript. A production build without it does not fall back to localhost and API requests fail with a clear configuration error. The generated frontend is `frontend/out/`; it is not part of the Docker image.

## Runtime environment

Configure the following in the Cloud Run service. Put credentials in Secret Manager and map secrets to environment variables; never put secret values in source, Docker build arguments, shell history, or frontend variables.

| Variable | Requirement | Purpose |
| --- | --- | --- |
| `PORT` | Supplied by Cloud Run | Uvicorn listens on `0.0.0.0:$PORT` (fallback 8080 for local use). |
| `DATABASE_URL` | Required for persistent operations | PostgreSQL connection URL. Cloud Run refuses SQLite writes. |
| `TRACEFORGE_CORS_ORIGINS` | Exact HTTPS origin(s) | Comma-separated browser origins; no `*`, localhost, or path component in Cloud Run. |
| `TRACEFORGE_DATA_DIR` | Optional, defaults to `/var/lib/traceforge/data` in image | Root directory for separately supplied runtime data assets. Relative values resolve from the repository/application root, not the process working directory. |
| `GEMINI_API_KEY` | Optional for basic startup; required for AI investigations | Secret Manager mapped to API runtime only. Missing key returns a safe feature error. |
| `GEMINI_MODEL` | Optional | Defaults to `gemini-2.5-flash`. |
| `TRACEFORGE_NPCI_AUTO_REFRESH` | Optional, default `false` | Keep disabled unless the owner explicitly wants an external source fetch at startup. |
| `TRACEFORGE_MAX_REQUEST_BYTES` | Optional, default 2,200,000; max 10,000,000 | Request body size bound. |
| `TRACEFORGE_GEMINI_MAX_REQUESTS_PER_MINUTE` | Optional, default 10 | Shared Gemini request cap; stored in PostgreSQL in Cloud Run. |
| `TRACEFORGE_GEMINI_TIMEOUT_SECONDS` | Optional, default 30; range 1–120 | Gemini provider timeout. |
| `DB_CONNECT_TIMEOUT_SECONDS` | Optional, default 5; range 1–30 | PostgreSQL connect timeout. |

Startup validates numeric controls, PostgreSQL URL syntax when supplied, Cloud Run port, and exact HTTPS CORS origins. It does not require a Gemini key, connect to PostgreSQL, run migrations, or load optional data. If Cloud Run lacks `DATABASE_URL`, it logs a secret-safe diagnostic: liveness remains available, readiness is 503, and persistent operations return 503. Provider and database errors do not log credential values.

## PostgreSQL setup and explicit schema/data migration

Choose and provision Cloud SQL, backups/PITR, networking, service account, database, and least-privilege runtime/migration roles only after project, region, access policy, retention, and cost are approved.

For a local migration rehearsal, install the Cloud SQL Auth Proxy and authenticate with an identity authorized for the intended instance. For example, run `cloud-sql-proxy --port 5432 PROJECT_ID:REGION:INSTANCE_ID`, then load the secret-backed URL into the environment through a protected secret source; do not paste the credential into a command or print it.

Two supported connection patterns are:

1. **Cloud SQL attachment/socket:** attach the instance to Cloud Run and grant the service identity Cloud SQL Client. Configure the secret-backed connection URL in libpq form, e.g. `postgresql://DB_USER:URL_ENCODED_PASSWORD@/DB_NAME?host=/cloudsql/PROJECT_ID:REGION:INSTANCE_ID`. URL-encode reserved characters in the username/password before storing the secret.
2. **Private IP:** use an approved VPC connection and a private address in the secret-backed URL, e.g. `postgresql://DB_USER:URL_ENCODED_PASSWORD@PRIVATE_IP:5432/DB_NAME`. Do not use a public database address.

Migrations are explicit and separate from API startup. Use the versioned files under `migrations/`:

```powershell
# With DATABASE_URL set from a protected local secret source or Cloud SQL Auth Proxy:
py -3.14 -m scripts.migrate_sqlite_to_postgres --schema-only
```

`--schema-only` applies idempotent versioned schema migrations without opening any local SQLite or public-data files. Use this for a fresh clone or a new database with no local records.

To copy existing local investigation records, first take and verify a protected backup of the source database and public-data directory. The script opens the SQLite source read-only, adds non-conflicting rows transactionally, skips optional source tables absent from that older database, and aborts on conflicting existing rows:

```powershell
py -3.14 -m scripts.migrate_sqlite_to_postgres `
  --source-db data/replay/investigations.db `
  --public-data-dir data/intelligence
```

The migration never modifies or deletes the SQLite source. Do not point it at production without a separately reviewed backup and reconciliation plan. Verify PostgreSQL table counts and representative case/audit history through an approved secure database client. No live PostgreSQL migration was performed or verified in this workspace.

## Runtime data and models

The image intentionally excludes all `data/`, `models/`, `features/`, databases, `.env` files, secrets, caches, and generated artifacts. The `.dockerignore` allowlist admits only the API code, pinned API requirements, migration files, and explicit migration utility.

With the default data-root layout, the routes require:

| API route(s) | Runtime assets | If missing |
| --- | --- | --- |
| `/api/alerts`, `/api/investigate`, `/api/money-trail` | `replay/replay_alerts.csv` | HTTP 503; historical investigation cannot run. |
| `/api/replay-summary` | `replay/replay_summary.json` | HTTP 503. |
| `/api/synthetic/money-trails`, `/api/fraud-ring/evaluate` | `generated/accounts.csv`, `generated/transactions.csv`, `generated/entity_observations.csv`, `generated/ground_truth.csv` | HTTP 503; synthetic routes remain unavailable. |
| Streamlit/research scripts, not in this API image | Feature exports and `models/*.joblib` as identified in the research code | Run only in the separate research environment; no model artifacts are served by Cloud Run. |

Supply only the approved assets needed by enabled routes through an owner-managed private runtime mechanism (for example, a read-only Cloud Storage volume) and set `TRACEFORGE_DATA_DIR` to its mount root. Do not upload the full 550 MB NFPC source dataset unless a specific route demonstrably needs it and the data owner approves. Do not generate, download, or substitute datasets/models at startup. Synthetic data remains separately labelled and is never substituted for historical NFPC data.

Local replay and generated files are ignored by Git. A fresh clone can build and start the API without them, but the routes above remain unavailable until assets are supplied. The API does not scan feature files or load joblib models during startup.

## Preflight and Cloud Run checklist

Set deployment configuration from approved sources without printing secret values, then run the read-only preflight from the repository root:

```powershell
$env:GOOGLE_CLOUD_PROJECT = 'YOUR_APPROVED_PROJECT_ID'
$env:CLOUD_RUN_REGION = 'YOUR_APPROVED_REGION'
$env:NEXT_PUBLIC_API_URL = 'https://YOUR-API-ORIGIN'
$env:TRACEFORGE_CORS_ORIGINS = 'https://YOUR-HOSTING-ORIGIN'
# Set DATABASE_URL from a protected secret source; never paste a credential into a command.
py -3.14 scripts/preflight.py
```

Preflight checks source inputs, pinned lockfiles, project/region, gcloud selected project and active authentication, Docker Engine, PostgreSQL URL shape, frontend URL, CORS, DB timeout, and optional local data availability. It never prints environment values. Missing replay assets are a warning because they can be supplied at runtime; missing Cloud credentials/configuration or build tools block readiness.

Before any deployment, the owner must:

1. Decide the API access perimeter. This app has no verified analyst identity; actor labels are user-entered. Do not expose the API publicly or treat CORS as access control. Do not add Firebase Authentication as part of this task. Select and configure an approved identity-aware gateway or restricted network perimeter first.
2. Approve project, region, budget, Cloud SQL size/connectivity, backup/PITR, Secret Manager access, retention, and runtime service identity.
3. Provide required runtime datasets through the approved mount mechanism if historical routes must operate. Do not include them in the image.
4. Run preflight and all local tests/builds; build the API image and perform a local health smoke test. Inspect the final image/context for secrets and private data.
5. Apply schema migrations explicitly with the migration role. Verify readiness before moving traffic.
6. Deploy the immutable API image to Cloud Run with `--no-allow-unauthenticated`, the approved Cloud SQL attachment/private path, Secret Manager mappings, HTTPS CORS origin, `TRACEFORGE_NPCI_AUTO_REFRESH=false`, suitable resource/concurrency limits, and only the approved asset mount. No deployment command should be run until this checklist is approved.
7. Build the static frontend with the final `NEXT_PUBLIC_API_URL`, then deploy `frontend/out/` to the approved static host. Confirm API health, readiness, CORS, browser alerts, a test case, analyst review, persisted audit, and API access restrictions from the real Hosting origin.

After approvals and after preflight passes, the command templates are:

```powershell
# Build and publish the API image to the selected Artifact Registry repository.
gcloud builds submit --project PROJECT_ID --tag REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY/traceforge-api:VERSION .

# Deploy the API with Cloud SQL and Secret Manager. Keep invocation authenticated;
# configure the already-approved gateway/identity path before expecting browser access.
gcloud run deploy traceforge-api `
  --project PROJECT_ID `
  --region REGION `
  --image REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY/traceforge-api:VERSION `
  --port 8080 `
  --service-account API_SERVICE_ACCOUNT `
  --add-cloudsql-instances PROJECT_ID:REGION:INSTANCE_ID `
  --set-env-vars TRACEFORGE_CORS_ORIGINS=https://HOSTING_ORIGIN,TRACEFORGE_NPCI_AUTO_REFRESH=false `
  --set-secrets DATABASE_URL=traceforge-database-url:VERSION,GEMINI_API_KEY=traceforge-gemini-api-key:VERSION `
  --no-allow-unauthenticated

# Build the static client with the real API URL, then publish only Hosting.
$env:NEXT_PUBLIC_API_URL = 'https://APPROVED_API_ORIGIN'
npm --prefix frontend ci
npm --prefix frontend run build
firebase deploy --only hosting --project PROJECT_ID
```

Replace every uppercase placeholder with owner-approved values; do not put secret values in these commands. Set Cloud Run resource, concurrency, ingress, network, and asset-volume settings according to the approved load/cost and access plan. The command template does not solve the browser identity/gateway question; do not deploy until that path is established and tested.

### Health and observability

- `GET /api/health`: liveness only; no database, Gemini, data, or migration dependency.
- `GET /api/ready`: database/schema readiness for persistent workflows; requires explicit migrations in PostgreSQL.
- Historical/synthetic route availability is data-dependent and surfaced by route-level HTTP 503 diagnostics; it is not a startup dependency.
- Keep request bodies and secrets out of logs. Logs identify database error type only and do not include connection strings.

## Not verified / remaining blockers

- No deployment, Cloud project selection, resources, database, migration, or cost-incurring action was performed.
- This machine has no Docker CLI/engine. The image build and container startup are therefore **NOT VERIFIED** here.
- The current checkout contains ignored local SQLite/data/model artifacts, but they are absent from Git. A fresh clone needs an approved data supply path for historical routes and an explicit database schema setup; existing local case records require a protected source backup and explicit migration if they are to be retained in Cloud SQL.
- No active Cloud project/region, Cloud SQL instance, database secret, Gemini key, Hosting API URL, or approved API perimeter was provided. Cloud deployment is **NOT READY** until the access boundary and configuration are supplied and reviewed.
- PostgreSQL behavior has not been tested against a live Cloud SQL/PostgreSQL instance. The migration script has only local/static verification available here.

## Rollback and cost

For application rollback, use the prior immutable Cloud Run image while keeping PostgreSQL. Do not switch back to SQLite after PostgreSQL accepts new writes. Keep the original SQLite and private data assets as protected backups until migration and retention are confirmed. Costs depend on project, region, Cloud SQL sizing/backup retention, networking, build/registry, Cloud Run traffic, storage, logging, and Gemini usage; review current provider pricing before provisioning.
