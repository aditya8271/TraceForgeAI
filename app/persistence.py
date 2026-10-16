"""SQLite-local and PostgreSQL production storage adapters."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
from typing import Iterator


class DatabaseConfigurationError(RuntimeError):
    """Raised when a runtime would otherwise use non-durable storage."""


class HybridRow(dict):
    """Mapping rows that preserve sqlite3.Row's integer indexing too."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        self._cursor.close()
        return HybridRow(row) if row is not None else None

    def fetchall(self):
        rows = self._cursor.fetchall()
        self._cursor.close()
        return [HybridRow(row) for row in rows]


class PostgresConnection:
    """Small DB-API adapter for the existing qmark SQL and row access."""

    _placeholder = re.compile(r"\?")

    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement, parameters=()):
        cursor = self._connection.cursor()
        try:
            cursor.execute(self._placeholder.sub("%s", statement), tuple(parameters))
        except Exception:
            cursor.close()
            raise
        if cursor.description is None:
            cursor.close()
            return None
        return _PostgresCursor(cursor)


def get_database_url() -> str | None:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        return None
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if not value.startswith("postgresql://"):
        raise DatabaseConfigurationError(
            "DATABASE_URL must use the PostgreSQL scheme postgresql://."
        )
    return value


def using_postgres() -> bool:
    return get_database_url() is not None


def ensure_sqlite_schema(db_file: Path) -> None:
    """Create missing local tables/indexes without altering existing rows."""
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file, timeout=10) as connection:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS investigations (
                case_key TEXT PRIMARY KEY,
                case_type TEXT NOT NULL,
                account_id TEXT,
                transaction_id TEXT,
                status TEXT NOT NULL DEFAULT 'New',
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS case_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_key TEXT NOT NULL,
                action TEXT NOT NULL,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                actor TEXT NOT NULL DEFAULT 'Local analyst session',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS case_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_key TEXT NOT NULL,
                decision TEXT NOT NULL
                    CHECK (decision IN ('Approve', 'Reject', 'Escalate')),
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                evidence_snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_key) REFERENCES investigations(case_key)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS api_usage_counters (
                counter_key TEXT PRIMARY KEY,
                window_start TEXT NOT NULL,
                request_count INTEGER NOT NULL
            )
        """)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_case_audit_case_id "
            "ON case_audit_log(case_key, id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_case_reviews_case_id "
            "ON case_reviews(case_key, id DESC)"
        )


@contextmanager
def connect(db_file: Path) -> Iterator[object]:
    """Open one transaction and always close its connection."""
    database_url = get_database_url()
    if os.getenv("K_SERVICE") and not database_url:
        raise DatabaseConfigurationError(
            "Cloud Run requires DATABASE_URL for durable PostgreSQL storage; "
            "refusing to write cases to the ephemeral container filesystem."
        )

    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        connection = psycopg.connect(
            database_url,
            connect_timeout=max(1, min(int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5")), 30)),
            row_factory=dict_row,
        )
        adapter = PostgresConnection(connection)
    else:
        ensure_sqlite_schema(db_file)
        connection = sqlite3.connect(db_file, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        adapter = connection

    try:
        yield adapter
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
