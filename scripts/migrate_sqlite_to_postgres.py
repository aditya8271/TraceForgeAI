"""Apply versioned PostgreSQL schema and safely copy the local SQLite data.

The SQLite source is opened read-only. PostgreSQL writes are transactional and
existing rows are never replaced; conflicting primary keys abort the copy.
"""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

import psycopg
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "investigations": ("case_key", (
        "case_key", "case_type", "account_id", "transaction_id", "status", "notes", "updated_at",
    )),
    "auth_users": ("username", (
        "username", "password_hash", "salt", "role", "created_at",
    )),
    "firebase_roles": ("uid", (
        "uid", "email", "role", "created_at",
    )),
    "case_audit_log": ("id", (
        "id", "case_key", "action", "field_name", "old_value", "new_value", "actor", "created_at",
    )),
    "case_reviews": ("id", (
        "id", "case_key", "decision", "reason", "actor", "evidence_snapshot", "created_at",
    )),
}


class MigrationConflict(RuntimeError):
    pass


def apply_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        )
    """)
    migration_dir = ROOT / "migrations"
    for path in sorted(migration_dir.glob("*.sql")):
        version = path.name.split("_", 1)[0]
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
        ).fetchone():
            continue
        statements = [item.strip() for item in path.read_text(encoding="utf-8").split(";") if item.strip()]
        with connection.transaction():
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
            )


def _read_local_public_state(public_data_dir: Path):
    result = {"payload": None, "refresh_status": None}
    for key, filename in (
        ("payload", "public_payment_stats.json"),
        ("refresh_status", "public_payment_stats_status.json"),
    ):
        path = public_data_dir / filename
        if path.exists():
            result[key] = json.loads(path.read_text(encoding="utf-8"))
    return result


def copy_sqlite_data(connection, source_db: Path, public_data_dir: Path) -> dict[str, int]:
    source_uri = source_db.resolve().as_uri() + "?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    source.row_factory = sqlite3.Row
    counts = {}
    try:
        with connection.transaction():
            for table, (primary_key, columns) in TABLES.items():
                source_rows = source.execute(
                    f"SELECT {', '.join(columns)} FROM {table} ORDER BY {primary_key}"
                ).fetchall()
                for source_row in source_rows:
                    row = dict(source_row)
                    existing = connection.execute(
                        f"SELECT {', '.join(columns)} FROM {table} WHERE {primary_key} = %s",
                        (row[primary_key],),
                    ).fetchone()
                    if existing:
                        if any(existing[column] != row[column] for column in columns):
                            raise MigrationConflict(
                                f"Conflicting existing row in {table}; transaction rolled back."
                            )
                        continue
                    placeholders = ", ".join("%s" for _ in columns)
                    connection.execute(
                        f"INSERT INTO {table} ({', '.join(columns)}) "
                        f"VALUES ({placeholders})",
                        tuple(row[column] for column in columns),
                    )
                counts[table] = len(source_rows)

            for table in ("case_audit_log", "case_reviews"):
                connection.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"
                )

            local_state = _read_local_public_state(public_data_dir)
            existing = connection.execute(
                "SELECT payload, refresh_status FROM public_data_cache WHERE id = 1"
            ).fetchone()
            existing_state = existing or {"payload": None, "refresh_status": None}
            for key in ("payload", "refresh_status"):
                if (
                    local_state[key] is not None
                    and existing_state[key] is not None
                    and local_state[key] != existing_state[key]
                ):
                    raise MigrationConflict(
                        "Conflicting public-data cache exists; transaction rolled back."
                    )
            payload = existing_state["payload"] or local_state["payload"]
            status = existing_state["refresh_status"] or local_state["refresh_status"]
            if payload is not None or status is not None:
                connection.execute("""
                    INSERT INTO public_data_cache (id, payload, refresh_status)
                    VALUES (1, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        payload = COALESCE(public_data_cache.payload, EXCLUDED.payload),
                        refresh_status = COALESCE(
                            public_data_cache.refresh_status, EXCLUDED.refresh_status
                        )
                """, (
                    Jsonb(payload) if payload is not None else None,
                    Jsonb(status) if status is not None else None,
                ))
    finally:
        source.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-db",
        type=Path,
        default=ROOT / "data" / "replay" / "investigations.db",
        help="Existing SQLite source database; opened read-only.",
    )
    parser.add_argument(
        "--public-data-dir",
        type=Path,
        default=ROOT / "data" / "intelligence",
        help="Directory containing existing public-data JSON cache/status files.",
    )
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url.startswith(("postgresql://", "postgres://")):
        print("Migration stopped: DATABASE_URL must point to PostgreSQL.", file=sys.stderr)
        return 2
    if not args.source_db.is_file():
        print("Migration stopped: source SQLite database was not found.", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            apply_schema(connection)
            counts = copy_sqlite_data(connection, args.source_db, args.public_data_dir)
        for table, count in counts.items():
            print(f"Verified {count} source rows in {table} (existing target rows were retained).")
        print("PostgreSQL schema and local data migration completed.")
        return 0
    except MigrationConflict as exc:
        print(f"Migration stopped: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"Migration failed ({type(exc).__name__}); no connection details were printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
