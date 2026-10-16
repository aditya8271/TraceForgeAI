
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = (
    ROOT.parent / "NFPC-Phase-1" / "EDA-Phase-1"
).resolve()


def main():
    files = sorted(DATA_DIR.glob("transactions_part_*.csv"))

    if not files:
        raise FileNotFoundError(
            f"No transaction CSV files found in {DATA_DIR}"
        )

    con = duckdb.connect(":memory:")
    con.execute("SET threads = 4")
    con.execute("SET memory_limit = '2GB'")

    # Use a safely escaped list of CSV paths.
    file_list = "[" + ", ".join(
        "'" + file.as_posix().replace("'", "''") + "'"
        for file in files
    ) + "]"

    print("TRACEFORGE AI — TRANSACTION DATA INSPECTION")
    print("Source directory:", DATA_DIR)
    print("Files found:", len(files))

    summary = con.execute(f"""
        SELECT
            COUNT(*) AS total_transactions,
            MIN(TRY_CAST(transaction_timestamp AS TIMESTAMP))
                AS earliest_timestamp,
            MAX(TRY_CAST(transaction_timestamp AS TIMESTAMP))
                AS latest_timestamp,
            COUNT(DISTINCT account_id) AS unique_accounts,
            COUNT(DISTINCT transaction_id) AS unique_transaction_ids
        FROM read_csv_auto(
            {file_list},
            union_by_name = true
        )
    """).fetchone()

    print("\n=== DATASET SUMMARY ===")
    print("Total transactions:", f"{summary[0]:,}")
    print("Earliest timestamp:", summary[1])
    print("Latest timestamp:", summary[2])
    print("Unique accounts:", f"{summary[3]:,}")
    print("Unique transaction IDs:", f"{summary[4]:,}")

    print("\n=== TRANSACTION TYPES ===")
    types = con.execute(f"""
        SELECT txn_type, COUNT(*) AS total
        FROM read_csv_auto(
            {file_list},
            union_by_name = true
        )
        GROUP BY txn_type
        ORDER BY txn_type
    """).fetchall()

    for txn_type, total in types:
        print(f"{txn_type}: {total:,}")

    print("\n=== SAMPLE TRANSACTIONS ===")
    sample = con.execute(f"""
        SELECT
            transaction_id,
            account_id,
            transaction_timestamp,
            txn_type,
            amount,
            counterparty_id,
            channel
        FROM read_csv_auto(
            {file_list},
            union_by_name = true
        )
        ORDER BY TRY_CAST(transaction_timestamp AS TIMESTAMP)
        LIMIT 5
    """).df()

    print(sample.to_string(index=False))

    con.close()


if __name__ == "__main__":
    main()
