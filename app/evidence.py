

"""Evidence bundles for TraceForge AI historical investigations.

Evidence is derived from the selected replay alert. This module does not
decide whether a transaction is fraudulent.
"""

from typing import Any


EVIDENCE_FIELDS = (
    "transaction_id",
    "account_id",
    "transaction_timestamp",
    "amount",
    "absolute_amount",
    "txn_type",
    "channel",
    "mcc_code",
    "counterparty_id",
    "baseline_transactions",
    "past_median_amount",
    "amount_multiple",
    "history_sufficient",
    "reasons",
    "evidence_summary",
    "alert_status",
)

FIELD_UNITS = {
    "amount": "source_units_unverified",
    "absolute_amount": "source_units_unverified",
    "baseline_transactions": "transactions",
    "past_median_amount": "source_units_unverified",
    "amount_multiple": "ratio",
    "transaction_timestamp": "source_timestamp_unverified",
}


def _clean_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return value


def build_evidence_bundle(alert: dict) -> dict:
    """Create stable, field-level evidence references for one alert."""

    transaction_id = str(alert.get("transaction_id") or "").strip()

    if not transaction_id:
        raise ValueError("Alert has no transaction_id.")

    items = []

    for index, field in enumerate(EVIDENCE_FIELDS, start=1):
        value = _clean_value(alert.get(field))

        items.append({
            "evidence_id": f"E{index:03d}",
            "field": field,
            "value": value,
            "available": value is not None,
            "source": "data/replay/replay_alerts.csv",
            "source_record_key": transaction_id,
            "unit": FIELD_UNITS.get(field, "unspecified"),
        })

    by_field = {item["field"]: item for item in items}

    baseline = by_field["baseline_transactions"]["value"]
    history_sufficient = by_field["history_sufficient"]["value"]
    median = by_field["past_median_amount"]["value"]
    multiple = by_field["amount_multiple"]["value"]

    warnings = []
    conflicts = []

    recorded_amount = by_field["amount"]["value"]
    absolute_amount = by_field["absolute_amount"]["value"]
    try:
        if recorded_amount is not None and absolute_amount is not None and abs(float(recorded_amount)) != float(absolute_amount):
            conflicts.append({
                "fields": ["amount", "absolute_amount"],
                "details": "Recorded amount magnitude differs from the absolute_amount field.",
            })
    except (TypeError, ValueError):
        conflicts.append({
            "fields": ["amount", "absolute_amount"],
            "details": "Amount fields could not be compared as numeric values.",
        })

    if str(history_sufficient).lower() != "true":
        warnings.append(
            "Historical baseline is marked insufficient. "
            "Do not treat an amount comparison as a reliable anomaly "
            "without additional evidence."
        )

    if baseline is not None:
        try:
            if int(float(baseline)) == 0:
                warnings.append(
                    "No prior baseline transactions are recorded for this alert."
                )
        except (TypeError, ValueError):
            warnings.append("Prior transaction count could not be interpreted.")

    if median is None or multiple is None:
        warnings.append(
            "Past median or amount multiple is unavailable; "
            "do not invent or calculate a missing historical comparison."
        )

    return {
        "source": "historical_replay",
        "transaction_id": transaction_id,
        "record_key": transaction_id,
        "evidence": items,
        "warnings": warnings,
        "conflicts": conflicts,
        "limitations": [
            "Evidence reflects the selected historical alert record.",
            "Evidence availability does not establish that fraud occurred.",
            "The source currency and unit are not verified by this bundle.",
            "Counterparty identifiers do not independently prove account ownership.",
        ],
    }
