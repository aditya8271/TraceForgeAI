
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = (
    ROOT.parent / "NFPC-Phase-1" / "EDA-Phase-1"
).resolve()
OUTPUT_DIR = ROOT / "data" / "features"
OUTPUT_FILE = OUTPUT_DIR / "account_features.csv"


def main():
    transaction_glob = str(
        DATA_DIR / "transactions_part_*.csv"
    ).replace("\\", "/")

    accounts_path = str(
        DATA_DIR / "accounts.csv"
    ).replace("\\", "/")

    labels_path = str(
        DATA_DIR / "train_labels.csv"
    ).replace("\\", "/")

    for path in (
        DATA_DIR / "accounts.csv",
        DATA_DIR / "train_labels.csv",
    ):
        if not path.exists():
            raise FileNotFoundError(f"Missing file: {path}")

    transaction_files = list(
        DATA_DIR.glob("transactions_part_*.csv")
    )
    if not transaction_files:
        raise FileNotFoundError(
            f"No transaction CSV files found in {DATA_DIR}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(":memory:")
    con.execute("SET threads = 4")
    con.execute("SET memory_limit = '2GB'")

    con.execute(f"""
        CREATE VIEW transactions AS
        SELECT *
        FROM read_csv_auto(
            '{transaction_glob}',
            union_by_name = true
        )
    """)

    con.execute(f"""
        CREATE VIEW accounts AS
        SELECT *
        FROM read_csv_auto('{accounts_path}')
    """)

    con.execute(f"""
        CREATE VIEW labels AS
        SELECT
            account_id,
            TRY_CAST(is_mule AS INTEGER) AS is_mule
        FROM read_csv_auto('{labels_path}')
    """)

    # Aggregate transaction behavior by account.
    # Counterparty counts are split by transaction direction.
    con.execute("""
        CREATE TEMP TABLE transaction_features AS
        SELECT
            account_id,

            COUNT(*) AS txn_count,

            COUNT(*) FILTER (
                WHERE txn_type = 'D'
            ) AS debit_count,

            COUNT(*) FILTER (
                WHERE txn_type = 'C'
            ) AS credit_count,

            COUNT(DISTINCT counterparty_id) FILTER (
                WHERE txn_type = 'D'
                  AND counterparty_id IS NOT NULL
            ) AS debit_counterparties,

            COUNT(DISTINCT counterparty_id) FILTER (
                WHERE txn_type = 'C'
                  AND counterparty_id IS NOT NULL
            ) AS credit_counterparties,

            SUM(
                CASE
                    WHEN txn_type = 'D'
                    THEN ABS(TRY_CAST(amount AS DOUBLE))
                    ELSE 0
                END
            ) AS debit_abs_amount,

            SUM(
                CASE
                    WHEN txn_type = 'C'
                    THEN ABS(TRY_CAST(amount AS DOUBLE))
                    ELSE 0
                END
            ) AS credit_abs_amount,

            AVG(ABS(TRY_CAST(amount AS DOUBLE)))
                AS avg_abs_amount,

            MAX(ABS(TRY_CAST(amount AS DOUBLE)))
                AS max_abs_amount,

            COUNT(*) FILTER (
                WHERE TRY_CAST(amount AS DOUBLE) < 0
            ) AS negative_amount_count,

            COUNT(DISTINCT counterparty_id)
                AS distinct_counterparties,

            COUNT(DISTINCT channel)
                AS distinct_channels,

            COUNT(DISTINCT CAST(
                TRY_CAST(transaction_timestamp AS TIMESTAMP)
                AS DATE
            )) AS active_days,

            MIN(TRY_CAST(transaction_timestamp AS TIMESTAMP))
                AS first_transaction,

            MAX(TRY_CAST(transaction_timestamp AS TIMESTAMP))
                AS last_transaction

        FROM transactions
        GROUP BY account_id
    """)

    # Exclude investigation outcome fields that may leak labels.
    query = """
        SELECT
            a.account_id,
            a.product_code,
            a.currency_code,
            a.account_opening_date,
            a.branch_code,
            a.branch_pin,
            TRY_CAST(a.avg_balance AS DOUBLE) AS avg_balance,
            a.product_family,
            a.nomination_flag,
            a.cheque_allowed,
            a.cheque_availed,
            TRY_CAST(a.num_chequebooks AS DOUBLE)
                AS num_chequebooks,
            a.last_mobile_update_date,
            a.kyc_compliant,
            a.last_kyc_date,
            a.rural_branch,
            TRY_CAST(a.monthly_avg_balance AS DOUBLE)
                AS monthly_avg_balance,
            TRY_CAST(a.quarterly_avg_balance AS DOUBLE)
                AS quarterly_avg_balance,
            TRY_CAST(a.daily_avg_balance AS DOUBLE)
                AS daily_avg_balance,

            COALESCE(t.txn_count, 0) AS txn_count,
            COALESCE(t.debit_count, 0) AS debit_count,
            COALESCE(t.credit_count, 0) AS credit_count,

            COALESCE(t.debit_counterparties, 0)
                AS debit_counterparties,

            COALESCE(t.credit_counterparties, 0)
                AS credit_counterparties,

            COALESCE(t.debit_abs_amount, 0)
                AS debit_abs_amount,

            COALESCE(t.credit_abs_amount, 0)
                AS credit_abs_amount,

            t.avg_abs_amount,
            t.max_abs_amount,

            COALESCE(t.negative_amount_count, 0)
                AS negative_amount_count,

            COALESCE(t.distinct_counterparties, 0)
                AS distinct_counterparties,

            COALESCE(t.distinct_channels, 0)
                AS distinct_channels,

            COALESCE(t.active_days, 0) AS active_days,
            t.first_transaction,
            t.last_transaction,

            l.is_mule

        FROM accounts a
        LEFT JOIN transaction_features t
            ON a.account_id = t.account_id
        LEFT JOIN labels l
            ON a.account_id = l.account_id
    """

    output_path = str(OUTPUT_FILE).replace("\\", "/")
    escaped_path = output_path.replace("'", "''")

    con.execute(f"""
        COPY ({query})
        TO '{escaped_path}'
        (HEADER, DELIMITER ',')
    """)

    summary = con.execute("""
        SELECT
            COUNT(*) AS accounts,
            COUNT(*) FILTER (
                WHERE is_mule = 1
            ) AS mule_labels,
            COUNT(*) FILTER (
                WHERE is_mule = 0
            ) AS legitimate_labels,
            COUNT(*) FILTER (
                WHERE is_mule IS NULL
            ) AS unlabelled,
            COUNT(*) FILTER (
                WHERE txn_count = 0
            ) AS accounts_without_transactions
        FROM read_csv_auto(?)
    """, [output_path]).fetchone()

    print("TRACEFORGE AI — FEATURE ENGINE")
    print("Output:", OUTPUT_FILE)
    print("Accounts:", summary[0])
    print("Mule-labelled:", summary[1])
    print("Legitimate-labelled:", summary[2])
    print("Unlabelled:", summary[3])
    print("Accounts without transactions:", summary[4])

    print("\nNew features added:")
    print("- debit_counterparties")
    print("- credit_counterparties")
    print("- Counts are unique counterparties per transaction direction.")

    print("\nExisting safeguards:")
    print("- Freeze status and label explanations are excluded.")
    print("- Negative amounts are counted separately.")
    print("- Null is_mule means no training label is available.")

    con.close()


if __name__ == "__main__":
    main()

