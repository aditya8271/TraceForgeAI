import sqlite3
from contextlib import nullcontext

from scripts.migrate_sqlite_to_postgres import copy_sqlite_data


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakePostgres:
    def __init__(self):
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))
        if statement.startswith("SELECT case_key,"):
            return Cursor(None)
        if "SELECT payload, refresh_status" in statement:
            return Cursor(None)
        return Cursor(None)


def test_sqlite_copy_skips_absent_optional_tables_and_keeps_source_read_only(tmp_path):
    source = tmp_path / "cases.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE investigations (case_key TEXT PRIMARY KEY, case_type TEXT NOT NULL, account_id TEXT, transaction_id TEXT, status TEXT NOT NULL, notes TEXT NOT NULL, updated_at TEXT NOT NULL)")
        db.execute("INSERT INTO investigations VALUES ('CASE-1', 'transaction', 'A-1', 'T-1', 'New', 'keep', '2026-01-01')")
    target = FakePostgres()

    counts = copy_sqlite_data(target, source, tmp_path / "no-public-cache")

    assert counts["investigations"] == 1
    assert counts["auth_users"] == 0
    assert counts["firebase_roles"] == 0
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT case_key, notes FROM investigations").fetchone() == ("CASE-1", "keep")
    assert any(statement.startswith("INSERT INTO investigations") for statement, _ in target.statements)
