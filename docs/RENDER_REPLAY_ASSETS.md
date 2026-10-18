# Supplying approved replay assets to Render through private Supabase Storage

The API lazily downloads only `replay_alerts.csv` and `replay_summary.json`
from the private `traceforge-replay` bucket when the corresponding local file
is absent. Downloaded bytes are validated and atomically cached beneath
`TRACEFORGE_DATA_DIR/replay/`. Existing local files take precedence. The Docker
image and Git repository continue to exclude historical replay data and all
investigation databases.

## Render environment

Set these values on the existing Render backend web service:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=<Supabase secret key>
TRACEFORGE_DATA_DIR=/var/lib/traceforge/data
```

Enter `SUPABASE_SECRET_KEY` as a secret in Render's environment settings. Do
not add it to frontend variables, source files, build arguments, logs, or
responses. The API sends it only in HTTPS request headers. Supabase secret
keys have broad Storage access and bypass Storage RLS, so restrict access to
the Render service, keep the bucket private, and rotate the key if exposed.

The backend requests only these object paths:

```text
traceforge-replay/replay_alerts.csv
traceforge-replay/replay_summary.json
```

It does not list bucket objects or request any other object. `investigations.db`
and `investigations.backup.db` are never downloaded, copied into the image, or
needed by these replay routes. Production case and review persistence remains
on the existing PostgreSQL configuration.

## Deployment steps

1. Confirm the bucket is private and contains only the owner-approved replay
   objects at the paths above. Do not upload investigation databases.
2. In Render, add `SUPABASE_URL` and the secret `SUPABASE_SECRET_KEY`; retain
   `TRACEFORGE_DATA_DIR=/var/lib/traceforge/data` and existing database/CORS
   settings.
3. Save the environment changes and trigger a backend deploy from the existing
   Render service. No frontend environment change or Firebase deployment is
   needed.
4. Check `GET /api/alerts?limit=1&offset=0` and `GET /api/replay-summary` for
   HTTP 200. Verify only status and response shape in logs; do not log alert
   rows or replay contents. Also check the synthetic money-trail, fraud-ring,
   and portfolio-quality endpoints remain available.

The container filesystem cache may be cleared on restart or deploy; the API
will download the approved object again from Supabase on the next request.
Missing credentials, inaccessible objects, oversized content, and malformed
content produce safe HTTP 503 responses. Synthetic endpoints do not depend on
Supabase.
