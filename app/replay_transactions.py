
from collections import defaultdict, deque
from pathlib import Path
import argparse
import json

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT.parent / "NFPC-Phase-1" / "EDA-Phase-1"
OUTPUT_DIR = ROOT / "data" / "replay"
TRANSACTION_FILES = sorted(DATA_DIR.glob("transactions_part_*.csv"))

WINDOW_SIZE = 20
MIN_HISTORY = 5
AMOUNT_MULTIPLIER = 5.0
ABSOLUTE_AMOUNT_THRESHOLD = 100_000.0
SAVE_BATCH_SIZE = 1000


def main():
    parser = argparse.ArgumentParser(
        description="Replay historical transactions and flag unusual patterns."
    )
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--account", type=str, default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if not TRANSACTION_FILES:
        raise FileNotFoundError(f"No transaction CSVs found: {DATA_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "replay_alerts.csv"
    summary_file = OUTPUT_DIR / "replay_summary.json"

    # Every run starts a fresh output. --reset is retained for compatibility.
    for path in (output_file, summary_file):
        if path.exists():
            path.unlink()

    print("=" * 60)
    print("TRACEFORGE AI | HISTORICAL TRANSACTION REPLAY")
    print("=" * 60)
    print(f"Source files: {len(TRANSACTION_FILES)}")
    print(f"Account filter: {args.account or 'All accounts'}")
    print(f"Transaction limit: {args.limit or 'All transactions'}")
    print("Mode: Historical replay, not a live bank feed\n")

    con = duckdb.connect(":memory:")
    file_list = "[" + ", ".join(
        "'" + p.as_posix().replace("'", "''") + "'"
        for p in TRANSACTION_FILES
    ) + "]"

    where_clause = ""
    if args.account:
        safe_account = args.account.replace("'", "''")
        where_clause = f"WHERE account_id = '{safe_account}'"

    limit_clause = f"LIMIT {args.limit}" if args.limit > 0 else ""

    query = f"""
        SELECT
            transaction_id,
            account_id,
            CAST(transaction_timestamp AS TIMESTAMP) AS event_time,
            mcc_code,
            channel,
            TRY_CAST(amount AS DOUBLE) AS amount,
            txn_type,
            counterparty_id
        FROM read_csv_auto({file_list}, union_by_name = TRUE)
        {where_clause}
        ORDER BY event_time, transaction_id
        {limit_clause}
    """

    history = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
    total_processed = 0
    alert_count = 0
    type_counts = defaultdict(int)
    alert_rows = []

    def save_alerts():
        if not alert_rows:
            return

        pd.DataFrame(alert_rows).to_csv(
            output_file,
            mode="a",
            header=not output_file.exists(),
            index=False,
        )
        alert_rows.clear()

    try:
        cursor = con.execute(query)

        while True:
            batch = cursor.fetch_df_chunk(10000)
            if batch.empty:
                break

            for row in batch.itertuples(index=False):
                total_processed += 1

                account_id = str(row.account_id)
                amount = row.amount
                txn_type = str(row.txn_type).upper()
                account_history = history[account_id]

                valid_amount = (
                    amount is not None
                    and pd.notna(amount)
                )
                current_amount = abs(float(amount)) if valid_amount else None

                # Only prior transactions are used for the baseline.
                previous_amounts = [
                    abs(value) for value in account_history
                ]
                baseline_count = len(previous_amounts)
                median_amount = None
                amount_multiple = None
                history_sufficient = baseline_count >= MIN_HISTORY

                if history_sufficient:
                    median_amount = float(
                        pd.Series(previous_amounts).median()
                    )

                reasons = []

                if valid_amount and history_sufficient:
                    if median_amount is not None and median_amount > 0:
                        amount_multiple = current_amount / median_amount

                        if amount_multiple >= AMOUNT_MULTIPLIER:
                            reasons.append(
                                "AMOUNT_SPIKE_VS_PAST_MEDIAN"
                            )
                    elif current_amount > 0 and median_amount == 0:
                        reasons.append(
                            "AMOUNT_AFTER_ZERO_MEDIAN_REVIEW"
                        )

                if (
                    valid_amount
                    and current_amount >= ABSOLUTE_AMOUNT_THRESHOLD
                ):
                    reasons.append("LARGE_ABSOLUTE_AMOUNT_REVIEW")

                if reasons:
                    alert_count += 1

                    median_text = (
                        f"{median_amount:.2f}"
                        if median_amount is not None
                        else "unavailable"
                    )
                    multiple_text = (
                        f"{amount_multiple:.2f}x"
                        if amount_multiple is not None
                        else "unavailable"
                    )

                    evidence = (
                        f"Current absolute amount={current_amount:.2f}; "
                        f"past median={median_text}; "
                        f"amount multiple={multiple_text}; "
                        f"prior transactions={baseline_count}; "
                        f"history sufficient={history_sufficient}; "
                        f"rules={','.join(reasons)}"
                    )

                    alert_rows.append({
                        "transaction_id": row.transaction_id,
                        "account_id": account_id,
                        "transaction_timestamp": str(row.event_time),
                        "amount": amount,
                        "absolute_amount": current_amount,
                        "txn_type": txn_type,
                        "channel": row.channel,
                        "mcc_code": row.mcc_code,
                        "counterparty_id": row.counterparty_id,
                        "baseline_transactions": baseline_count,
                        "past_median_amount": median_amount,
                        "amount_multiple": amount_multiple,
                        "history_sufficient": history_sufficient,
                        "reasons": "|".join(reasons),
                        "evidence_summary": evidence,
                        "alert_status": "NEEDS_ANALYST_REVIEW",
                        "is_confirmed_fraud": False,
                    })

                    if len(alert_rows) >= SAVE_BATCH_SIZE:
                        save_alerts()

                # Add this event only after scoring it.
                if valid_amount:
                    account_history.append(float(amount))

                type_counts[txn_type] += 1

            if total_processed % 50000 < len(batch):
                print(
                    f"Processed: {total_processed:,} | "
                    f"Alerts: {alert_count:,}"
                )

        save_alerts()

    finally:
        con.close()

    summary = {
        "mode": "historical_replay",
        "source_files": len(TRANSACTION_FILES),
        "transactions_processed": total_processed,
        "accounts_seen": len(history),
        "alerts_generated": alert_count,
        "transaction_types": dict(type_counts),
        "alert_file": output_file.name,
        "alert_thresholds": {
            "window_size": WINDOW_SIZE,
            "minimum_history": MIN_HISTORY,
            "amount_multiplier": AMOUNT_MULTIPLIER,
            "absolute_amount_threshold": ABSOLUTE_AMOUNT_THRESHOLD,
        },
        "limitations": [
            "Alerts indicate unusual patterns, not confirmed fraud.",
            "Historical replay is not a live bank feed.",
            "Transaction amounts' currency and units are not verified here.",
            "Negative amounts are compared by absolute magnitude.",
            "Counterparty IDs are not assumed to be account IDs.",
            "No transaction-level fraud labels are used.",
        ],
    }

    summary_file.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("REPLAY COMPLETE")
    print("=" * 60)
    print(f"Transactions processed: {total_processed:,}")
    print(f"Accounts seen: {len(history):,}")
    print(f"Review alerts generated: {alert_count:,}")
    print(f"Alerts CSV: {output_file}")
    print(f"Summary JSON: {summary_file}")


if __name__ == "__main__":
    main()
