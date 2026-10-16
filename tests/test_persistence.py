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
