from pathlib import Path

from scripts.preflight import collect_checks


def test_fresh_checkout_without_local_assets_is_not_a_build_blocker(tmp_path):
    env = {
        "DATABASE_URL": "postgresql://opaque:opaque@db.invalid/traceforge",
        "NEXT_PUBLIC_API_URL": "https://api.example.test",
        "TRACEFORGE_CORS_ORIGINS": "https://app.example.test",
        "GOOGLE_CLOUD_PROJECT": "sample-project",
        "CLOUD_RUN_REGION": "us-central1",
        "DB_CONNECT_TIMEOUT_SECONDS": "5",
        "TRACEFORGE_DATA_DIR": str(tmp_path / "no-local-assets"),
        "GEMINI_API_KEY": "never-print-this-secret",
    }
    checks = collect_checks(env, which=lambda _name: None, run=lambda *_args, **_kwargs: None)
    by_name = {name: (status, detail) for status, name, detail in checks}
    assert by_name["PostgreSQL configuration"][0] == "PASS"
    assert by_name["Static frontend API URL"][0] == "PASS"
    assert by_name["CORS origins"][0] == "PASS"
    assert by_name["Historical replay assets"][0] == "WARN"
    assert all("never-print-this-secret" not in detail for _, _, detail in checks)


def test_api_image_excludes_ignored_datasets_models_and_local_databases():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
    assert "COPY data/replay/" not in dockerfile
    assert "replay_alerts.csv" not in dockerfile
    assert "replay_summary.json" not in dockerfile
    assert "investigations.db" not in dockerfile
    assert "investigations.backup.db" not in dockerfile
    assert "COPY models/" not in dockerfile
    assert "--host 0.0.0.0 --port ${PORT:-8080}" in dockerfile
    assert "migrations/ ./migrations/" in dockerfile
    assert "requirements-api.lock" in dockerfile
    assert "**" in dockerignore.splitlines()
    assert "!models/" not in dockerignore
    assert "!data/replay/" not in dockerignore
