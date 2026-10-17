"""Read-only Cloud Run deployment preflight; never prints secret values."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def _https_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return (parsed.scheme == "https" and bool(parsed.netloc)
            and parsed.hostname not in {"localhost", "127.0.0.1"}
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)


def collect_checks(env=None, which=None, run=None):
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    checks = []

    def add(status, name, detail):
        checks.append((status, name, detail))

    required_files = [
        "Dockerfile", ".dockerignore", "requirements-api.txt", "requirements-api.lock",
        "frontend/package.json", "frontend/package-lock.json",
        "app/api.py", "app/persistence.py", "migrations/001_core.sql",
        "migrations/002_public_data_cache.sql", "scripts/migrate_sqlite_to_postgres.py",
    ]
    missing = [name for name in required_files if not (ROOT / name).is_file()]
    add("BLOCK" if missing else "PASS", "Repository build inputs", "Missing: " + ", ".join(missing) if missing else "Required source, lockfile, and migration files exist.")

    database_url = env.get("DATABASE_URL", "").strip()
    add("PASS" if database_url.startswith(("postgresql://", "postgres://")) else "BLOCK", "PostgreSQL configuration", "DATABASE_URL is configured with a PostgreSQL scheme." if database_url.startswith(("postgresql://", "postgres://")) else "Set DATABASE_URL through a secret manager; its value was not displayed.")

    api_url = env.get("NEXT_PUBLIC_API_URL", "").strip()
    add("PASS" if _https_url(api_url) else "BLOCK", "Static frontend API URL", "A production HTTPS backend URL is configured." if _https_url(api_url) else "Set NEXT_PUBLIC_API_URL to the deployed HTTPS API origin before building the frontend.")

    origins = [item.strip() for item in env.get("TRACEFORGE_CORS_ORIGINS", "").split(",") if item.strip()]
    valid_origins = bool(origins) and all(_https_url(item) and item != "*" for item in origins)
    add("PASS" if valid_origins else "BLOCK", "CORS origins", "Exact HTTPS frontend origins are configured." if valid_origins else "Set TRACEFORGE_CORS_ORIGINS to comma-separated exact HTTPS frontend origins; no wildcard or localhost.")

    project = env.get("GOOGLE_CLOUD_PROJECT", "").strip() or env.get("GCLOUD_PROJECT", "").strip()
    region = env.get("CLOUD_RUN_REGION", "").strip()
    add("PASS" if project else "BLOCK", "Google Cloud project", "Project ID is configured." if project else "Set GOOGLE_CLOUD_PROJECT after selecting the intended project.")
    add("PASS" if region else "BLOCK", "Cloud Run region", "Region is configured." if region else "Set CLOUD_RUN_REGION after confirming location and cost requirements.")

    docker = which("docker")
    docker_ready = False
    if docker:
        try:
            docker_ready = run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=10, check=False).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            docker_ready = False
    add("PASS" if docker_ready else "BLOCK", "Docker engine", "Docker is available and responding." if docker_ready else "Install and start Docker to build and smoke-test the API image.")

    gcloud = which("gcloud")
    gcloud_ready = False
    if gcloud and project:
        try:
            active_project = run([gcloud, "config", "get-value", "project"], capture_output=True, text=True, timeout=10, check=False)
            active_accounts = run([gcloud, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], capture_output=True, text=True, timeout=10, check=False)
            gcloud_ready = active_project.returncode == 0 and active_project.stdout.strip() == project and active_accounts.returncode == 0 and bool(active_accounts.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            gcloud_ready = False
    add("PASS" if gcloud_ready else "BLOCK", "Google Cloud CLI context", "gcloud is authenticated and its selected project matches GOOGLE_CLOUD_PROJECT." if gcloud_ready else "Install/authenticate gcloud and select the same project as GOOGLE_CLOUD_PROJECT; output values are not displayed.")
    add("PASS" if which("firebase") else "BLOCK", "Firebase CLI", "Firebase CLI is available for the existing static Hosting target." if which("firebase") else "Install Firebase CLI and select the approved Hosting project before publishing the static frontend.")

    try:
        timeout = int(env.get("DB_CONNECT_TIMEOUT_SECONDS", "5"))
        valid_timeout = 1 <= timeout <= 30
    except ValueError:
        valid_timeout = False
    add("PASS" if valid_timeout else "BLOCK", "Database timeout", "Database connection timeout is within 1 to 30 seconds." if valid_timeout else "Set DB_CONNECT_TIMEOUT_SECONDS to an integer from 1 through 30.")

    if not env.get("GEMINI_API_KEY", "").strip():
        add("WARN", "Gemini key", "Not configured; basic startup is supported, but investigation requests will return a safe configuration error.")
    else:
        add("PASS", "Gemini key", "A Gemini key is present in the environment; its value was not displayed.")

    data_dir = Path(env.get("TRACEFORGE_DATA_DIR", str(ROOT / "data"))).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    missing_assets = [
        str(data_dir / "replay" / name)
        for name in ("replay_alerts.csv", "replay_summary.json")
        if not (data_dir / "replay" / name).is_file()
    ]
    if missing_assets:
        add("WARN", "Historical replay assets", "Not present locally; alert, replay-summary, investigation, and historical money-trail routes need these assets supplied through TRACEFORGE_DATA_DIR at runtime.")
    else:
        add("PASS", "Historical replay assets", "Replay routes have their required local assets.")

    add("WARN", "Optional research artifacts", "Generated CSVs and joblib models are intentionally excluded from the API image; synthetic research routes and the separate Streamlit dashboard need their own runtime artifacts.")
    return checks


def main() -> int:
    checks = collect_checks()
    for status, name, detail in checks:
        print(f"{status:5} {name}: {detail}")
    blocking = any(status == "BLOCK" for status, _, _ in checks)
    warnings = any(status == "WARN" for status, _, _ in checks)
    label = "NOT READY" if blocking else "PARTIALLY READY" if warnings else "READY"
    print(f"\n{label}: no cloud actions were performed.")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
