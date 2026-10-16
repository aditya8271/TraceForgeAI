
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(r"C:\Users\ueser\NFPC-Phase-1\EDA-Phase-1")
FEATURES = ROOT / "data" / "features" / "account_features.csv"
OUT = ROOT / "data" / "reports"
OUT.mkdir(parents=True, exist_ok=True)

files = sorted(DATA.glob("transactions_part_*.csv"))
if not files:
    raise FileNotFoundError(f"No transaction CSV files in {DATA}")

def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"

file_list = "[" + ", ".join(
    sql_string(f.as_posix()) for f in files
) + "]"

con = duckdb.connect()
con.execute("SET memory_limit = '2GB'")
con.execute("SET threads = 4")

try:
    print("Aggregating account-counterparty activity...")

    query = f"""
        WITH tx AS (
            SELECT
                account_id,
                counterparty_id,
                txn_type,
                amount,
                channel
            FROM read_csv_auto(
                {file_list},
                union_by_name = true
            )
        ),
        account_signals AS (
            SELECT
                account_id,
                COUNT(*) AS txn_count,
                COUNT(DISTINCT counterparty_id)
                    AS distinct_counterparties,
                COUNT(DISTINCT channel) AS distinct_channels,
                COUNT(*) FILTER (WHERE txn_type = 'D')
                    AS debit_count,
                COUNT(*) FILTER (WHERE txn_type = 'C')
                    AS credit_count,
                COUNT(DISTINCT counterparty_id) FILTER (
                    WHERE txn_type = 'D'
                ) AS debit_counterparties,
                COUNT(DISTINCT counterparty_id) FILTER (
                    WHERE txn_type = 'C'
                ) AS credit_counterparties,
                SUM(ABS(amount)) AS total_abs_amount
            FROM tx
            GROUP BY account_id
        )
        SELECT
            f.account_id,
            f.is_mule,
            s.txn_count,
            s.distinct_counterparties,
            s.distinct_channels,
            s.debit_count,
            s.credit_count,
            s.debit_counterparties,
            s.credit_counterparties,
            s.total_abs_amount
        FROM read_csv_auto({sql_string(FEATURES.as_posix())}) f
        LEFT JOIN account_signals s USING (account_id)
        WHERE f.is_mule IS NOT NULL
    """

    result = con.execute(query).fetchdf()

    output = OUT / "counterparty_signal_validation.csv"
    result.to_csv(output, index=False)

    print("\n=== LABELLED ACCOUNT SIGNALS ===")
    print(
        result.groupby("is_mule")[
            [
                "txn_count",
                "distinct_counterparties",
                "distinct_channels",
                "debit_count",
                "credit_count",
                "debit_counterparties",
                "credit_counterparties",
                "total_abs_amount",
            ]
        ].median().round(2).to_string()
    )

    print("\nLabelled rows:", len(result))
    print("Saved:", output)

finally:
    con.close()
