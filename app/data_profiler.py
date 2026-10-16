
import json
from pathlib import Path

import duckdb


DATA_DIR = (
    Path(__file__).resolve().parents[1]
    / ".."
    / "NFPC-Phase-1"
    / "EDA-Phase-1"
).resolve()

OUTPUT_FILE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "profile_report.json"
)


def main():
    transaction_glob = str(
        DATA_DIR / "transactions_part_*.csv"
    ).replace("\\", "/")

    accounts_file = DATA_DIR / "accounts.csv"
    labels_file = DATA_DIR / "train_labels.csv"
    test_file = DATA_DIR / "test_accounts.csv"

    for path in (accounts_file, labels_file, test_file):
        if not path.exists():
            raise FileNotFoundError(f"Missing dataset file: {path}")

    transaction_files = sorted(
        DATA_DIR.glob("transactions_part_*.csv")
    )

    if not transaction_files:
        raise FileNotFoundError(
            f"No transaction CSV files found in {DATA_DIR}"
        )

    con = duckdb.connect(":memory:")
    con.execute("SET threads = 4")
    con.execute("SET memory_limit = '2GB'")

    # Read CSV files directly; do not concatenate them in pandas.
    con.execute(f"""
        CREATE VIEW transactions AS
        SELECT *
        FROM read_csv_auto(
            '{transaction_glob}',
            header = true,
            union_by_name = true
        )
    """)

    con.execute(f"""
        CREATE VIEW accounts AS
        SELECT *
        FROM read_csv_auto('{str(accounts_file).replace(chr(92), "/")}')
    """)

    con.execute(f"""
        CREATE VIEW labels AS
        SELECT *
        FROM read_csv_auto('{str(labels_file).replace(chr(92), "/")}')
    """)

    con.execute(f"""
        CREATE VIEW test_accounts AS
        SELECT *
        FROM read_csv_auto('{str(test_file).replace(chr(92), "/")}')
    """)

    report = {}

    report["dataset_directory"] = str(DATA_DIR)
    report["transaction_files"] = [
        {"name": f.name, "size_mb": round(f.stat().st_size / 1_000_000, 2)}
        for f in transaction_files
    ]

    report["row_counts"] = {
        "transactions": con.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0],
        "accounts": con.execute(
            "SELECT COUNT(*) FROM accounts"
        ).fetchone()[0],
        "training_labels": con.execute(
            "SELECT COUNT(*) FROM labels"
        ).fetchone()[0],
        "test_accounts": con.execute(
            "SELECT COUNT(*) FROM test_accounts"
        ).fetchone()[0],
    }

    report["transaction_schema"] = con.execute(
        "DESCRIBE transactions"
    ).fetchall()

    report["txn_type_distribution"] = con.execute("""
        SELECT txn_type, COUNT(*) AS row_count
        FROM transactions
        GROUP BY txn_type
        ORDER BY txn_type
    """).fetchall()

    report["channel_distribution"] = con.execute("""
        SELECT channel, COUNT(*) AS row_count
        FROM transactions
        GROUP BY channel
        ORDER BY row_count DESC
        LIMIT 15
    """).fetchall()

    report["amount_summary"] = con.execute("""
        SELECT
            MIN(TRY_CAST(amount AS DOUBLE)),
            MAX(TRY_CAST(amount AS DOUBLE)),
            AVG(TRY_CAST(amount AS DOUBLE)),
            COUNT(*) FILTER (
                WHERE TRY_CAST(amount AS DOUBLE) IS NULL
            ),
            COUNT(*) FILTER (
                WHERE TRY_CAST(amount AS DOUBLE) < 0
            ),
            COUNT(*) FILTER (
                WHERE TRY_CAST(amount AS DOUBLE) = 0
            )
        FROM transactions
    """).fetchone()

    report["timestamp_parse_failures"] = con.execute("""
        SELECT COUNT(*)
        FROM transactions
        WHERE TRY_CAST(transaction_timestamp AS TIMESTAMP) IS NULL
    """).fetchone()[0]

    report["null_checks"] = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE transaction_id IS NULL),
            COUNT(*) FILTER (WHERE account_id IS NULL),
            COUNT(*) FILTER (WHERE counterparty_id IS NULL),
            COUNT(*) FILTER (WHERE txn_type IS NULL)
        FROM transactions
    """).fetchone()

    report["label_distribution"] = con.execute("""
        SELECT is_mule, COUNT(*)
        FROM labels
        GROUP BY is_mule
        ORDER BY is_mule
    """).fetchall()

    report["counterparty_examples"] = con.execute("""
        SELECT counterparty_id, COUNT(*) AS frequency
        FROM transactions
        WHERE counterparty_id IS NOT NULL
        GROUP BY counterparty_id
        ORDER BY frequency DESC
        LIMIT 10
    """).fetchall()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    print("TRACEFORGE AI — DATA PROFILE")
    print("Dataset:", DATA_DIR)
    print("\nRow counts:")
    for key, value in report["row_counts"].items():
        print(f"  {key}: {value}")

    print("\nTransaction type distribution:")
    for row in report["txn_type_distribution"]:
        print(" ", row)

    print("\nAmount summary (min, max, average, invalid, negative, zero):")
    print(" ", report["amount_summary"])

    print("\nTimestamp parse failures:", report["timestamp_parse_failures"])
    print("Null checks (transaction_id, account_id, counterparty_id, txn_type):")
    print(" ", report["null_checks"])

    print("\nLabel distribution:")
    for row in report["label_distribution"]:
        print(" ", row)

    print("\nCounterparty examples:")
    for row in report["counterparty_examples"]:
        print(" ", row)

    print("\nFull report saved to:", OUTPUT_FILE)
    con.close()


if __name__ == "__main__":
    main()
