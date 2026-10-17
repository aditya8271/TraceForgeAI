import sqlite3

import pytest

from app.persistence import DatabaseConfigurationError, ensure_sqlite_schema


def test_sqlite_schema_upgrade_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "nested" / "cases.db"
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE investigations (case_key TEXT PRIMARY KEY, case_type TEXT NOT NULL, "
            "account_id TEXT, transaction_id TEXT, status TEXT NOT NULL, notes TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO investigations VALUES ('CASE-1', 'alert', 'A-1', 'T-1', 'Under Review', 'keep', '2026-01-01')"
        )

    ensure_sqlite_schema(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT * FROM investigations").fetchone() == (
            "CASE-1", "alert", "A-1", "T-1", "Under Review", "keep", "2026-01-01"
        )
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"case_audit_log", "case_reviews", "api_usage_counters"} <= tables


def test_cloud_run_refuses_ephemeral_sqlite_when_database_url_missing(tmp_path, monkeypatch):
    from app.persistence import connect

    monkeypatch.setenv("K_SERVICE", "traceforge")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigurationError, match="requires DATABASE_URL"):
        with connect(tmp_path / "must-not-exist.db"):
            pass
    assert not (tmp_path / "must-not-exist.db").exists()


def test_invalid_database_timeout_is_rejected_without_secret_output(monkeypatch):
    from app.persistence import get_db_connect_timeout

    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "31")
    with pytest.raises(DatabaseConfigurationError, match="between 1 and 30"):
        get_db_connect_timeout()


def test_schema_only_migration_never_opens_local_sqlite(monkeypatch, tmp_path, capsys):
    import sys
    from scripts import migrate_sqlite_to_postgres as migration

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.invalid/test")
    missing_source = tmp_path / "must-not-be-read.db"
    monkeypatch.setattr(sys, "argv", ["migrate_sqlite_to_postgres", "--schema-only", "--source-db", str(missing_source)])
    monkeypatch.setattr(migration.psycopg, "connect", lambda *args, **kwargs: FakeConnection())
    monkeypatch.setattr(migration, "apply_schema", lambda _connection: None)
    assert migration.main() == 0
    assert not missing_source.exists()
    output = capsys.readouterr().out
    assert "schema migrations completed" in output
    assert "secret" not in output
