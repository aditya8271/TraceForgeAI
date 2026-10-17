# TraceForge AI

TraceForge AI is a BFSI-focused financial crime investigation platform designed to support transaction analysis, suspicious activity triage, evidence-linked investigations, money-trail exploration, and analyst case reviews.

## Features

- Transaction replay and alert triage
- Evidence bundles and source-linked claims
- AI-assisted investigation with deterministic review checks
- Money-trail and synthetic fraud-ring analysis
- Case management, analyst decisions, and audit history
- Portfolio analytics and public aggregate financial intelligence

## Technology Stack

- Frontend: Next.js, React, TypeScript
- Backend: Python, FastAPI
- AI: Google Gemini API
- Data analysis: DuckDB, pandas, graph analysis
- Storage: SQLite for local development; PostgreSQL adapter for deployment
- Deployment configuration: Firebase Hosting and Google Cloud Run

## Local Development

See `docs/CLOUD_DEPLOYMENT.md` for the actual API-only Cloud Run / static Next.js architecture, pinned runtime requirements, optional runtime assets, PostgreSQL setup, migration steps, health/readiness probes, and deployment preflight.

Create your local `.env` from `.env.example` and configure the required variables. Never commit API keys, credentials, local databases, or raw transaction datasets.

## Important Limitations

TraceForge AI supports investigation and triage; its alerts are not proof of fraud. Synthetic evaluation results must not be interpreted as real-world performance. Analyst decisions require appropriate human review.

Cloud deployment requires persistent PostgreSQL storage and an approved API access-security boundary.

The API image uses the fully pinned package versions in `requirements-api.lock` and intentionally excludes local databases, private datasets, feature exports, and trained models. Run the read-only deployment check with `py -3.14 scripts/preflight.py`; it does not deploy or print credentials.
