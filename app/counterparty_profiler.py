
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(r"C:\Users\ueser\NFPC-Phase-1\EDA-Phase-1")
OUTPUT_DIR = ROOT / "data" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

files = sorted(DATA_DIR.glob("transactions_part_*.csv"))

if not files:
    raise FileNotFoundError(f"No transaction files found: {DATA_DIR}")

def sql_string(value):
    """Safely quote a value as a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"

file_list = "[" + ", ".join(
    sql_string(file.as_posix()) for file in files
) + "]"

con = duckdb.connect()
con.execute("SET memory_limit = '2GB'")
con.execute("SET threads = 4")

try:
    print(f"Found {len(files)} transaction files.")
    print("Reading transaction data...")

    # Direct query avoids CREATE VIEW prepared-parameter errors.
    summary_query = f"""
        SELECT
            COUNT(*) AS transaction_count,
            COUNT(DISTINCT account_id) AS unique_accounts,
            COUNT(DISTINCT counterparty_id) AS unique_counterparties,
            COUNT(*) FILTER (WHERE txn_type = 'D') AS debit_count,
            COUNT(*) FILTER (WHERE txn_type = 'C') AS credit_count,
            COUNT(*) FILTER (
                WHERE counterparty_id IS NULL
            ) AS missing_counterparty_count
        FROM read_csv_auto({file_list}, union_by_name = true)
    """

    summary = con.execute(summary_query).fetchdf()

    print("\n=== OVERALL SUMMARY ===")
    print(summary.to_string(index=False))

    print("\nAggregating counterparty statistics...")

    stats_query = f"""
        SELECT
            counterparty_id,
            COUNT(*) AS transaction_count,
            COUNT(DISTINCT account_id) AS unique_accounts,
            COUNT(*) FILTER (
                WHERE txn_type = 'D'
            ) AS debit_count,
            COUNT(*) FILTER (
                WHERE txn_type = 'C'
            ) AS credit_count,
            ROUND(SUM(ABS(amount)), 2) AS total_absolute_amount,
            COUNT(DISTINCT channel) AS unique_channels,
            MIN(transaction_timestamp) AS first_seen,
            MAX(transaction_timestamp) AS last_seen
        FROM read_csv_auto({file_list}, union_by_name = true)
        WHERE counterparty_id IS NOT NULL
        GROUP BY counterparty_id
    """

    stats = con.execute(stats_query).fetchdf()

    output_file = OUTPUT_DIR / "counterparty_stats.csv"
    stats.to_csv(output_file, index=False)

    print("\n=== TOP 15 COUNTERPARTIES BY UNIQUE ACCOUNTS ===")
    print(
        stats.sort_values(
            ["unique_accounts", "transaction_count"],
            ascending=[False, False],
        ).head(15).to_string(index=False)
    )

    print(f"\nUnique counterparties: {len(stats):,}")
    print(f"Saved report: {output_file}")
    print("\nCounterparty profiling completed.")

finally:
    con.close()
