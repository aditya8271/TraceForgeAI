
"""Deterministic evidence checks for TraceForge AI investigation reports."""

import re


def _normalise_number(value):
    """Convert a numeric value to a float, handling thousands separators."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _value_found_in_report(field, value, report_text, report_lower):
    """Check text values and equivalent numeric formatting."""
    value_text = str(value).strip()

    if value_text.lower() in report_lower:
        return True

    numeric_fields = {
        "amount",
        "absolute_amount",
        "past_median_amount",
        "amount_multiple",
    }

    if field not in numeric_fields:
        return False

    expected = _normalise_number(value_text)
    if expected is None:
        return False

    numbers = re.findall(
        r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?",
        report_text,
    )

    for number in numbers:
        parsed = _normalise_number(number)
        if parsed is not None and parsed == expected:
            return True

    return False


def review_investigation(report: str, evidence_bundle: dict) -> dict:
    """Review report/evidence consistency; this is not a fraud classifier."""

    evidence = {
        item["field"]: item.get("value")
        for item in evidence_bundle.get("evidence", [])
        if item.get("available")
    }

    report_text = report or ""
    report_lower = report_text.lower()

    checks = []
    supported_count = 0
    review_count = 0

    fields_to_check = (
        "transaction_id",
        "account_id",
        "counterparty_id",
        "transaction_timestamp",
        "amount",
        "txn_type",
        "channel",
        "mcc_code",
        "baseline_transactions",
        "reasons",
    )

    for field in fields_to_check:
        value = evidence.get(field)

        if value is None or str(value).strip() == "":
            continue

        value_text = str(value).strip()
        found = _value_found_in_report(
            field, value, report_text, report_lower
        )

        check = {
            "check": f"source_value:{field}",
            "field": field,
            "expected_value": value_text,
            "status": (
                "SUPPORTED_MATCH" if found else "NOT_FOUND_IN_REPORT"
            ),
            "evidence_record_key": evidence_bundle.get("record_key"),
        }
        checks.append(check)

        if found:
            supported_count += 1
        else:
            review_count += 1

    history_flag = str(
        evidence.get("history_sufficient", "")
    ).strip().lower()

    median_available = evidence.get("past_median_amount") not in (None, "")
    multiple_available = evidence.get("amount_multiple") not in (None, "")

    if history_flag == "false" or not median_available or not multiple_available:
        acknowledges_missing_history = any(
            phrase in report_lower
            for phrase in (
                "insufficient baseline",
                "baseline is insufficient",
                "history_sufficient: false",
                "no established",
                "historical baseline",
                "no prior",
                "unavailable",
            )
        )

        checks.append({
            "check": "missing_history_acknowledgement",
            "status": (
                "ACKNOWLEDGED"
                if acknowledges_missing_history
                else "ANALYST_REVIEW_REQUIRED"
            ),
            "details": (
                "The historical baseline is insufficient or "
                "comparison metrics are unavailable."
            ),
        })

        if acknowledges_missing_history:
            supported_count += 1
        else:
            review_count += 1

    unsupported_context_patterns = {
        "verified_account_ownership": [
            r"\bthe counterparty is owned by\b",
            r"\bthe account owner is\b",
            r"\bverified beneficial owner\b",
        ],
        "confirmed_source_of_funds": [
            r"\bsource of funds is confirmed\b",
            r"\bfunds are confirmed to be illicit\b",
        ],
        "confirmed_fraud": [
            r"\bfraud is confirmed\b",
            r"\bconfirmed fraudulent transaction\b",
            r"\bthis account is a confirmed mule\b",
        ],
    }

    for claim_type, patterns in unsupported_context_patterns.items():
        matches = [
            pattern
            for pattern in patterns
            if re.search(pattern, report_lower)
        ]

        if matches:
            checks.append({
                "check": f"unsupported_context:{claim_type}",
                "status": "FLAG_FOR_ANALYST",
                "details": (
                    "The report may assert a fact not established "
                    "by the supplied alert evidence."
                ),
            })
            review_count += 1

    flag_statuses = {
        "NOT_FOUND_IN_REPORT",
        "ANALYST_REVIEW_REQUIRED",
        "FLAG_FOR_ANALYST",
    }

    flags = [
        item for item in checks
        if item["status"] in flag_statuses
    ]

    return {
        "reviewer": "TraceForge Deterministic Evidence Reviewer",
        "review_status": (
            "REVIEW_REQUIRED"
            if flags
            else "CHECKS_PASSED_WITH_LIMITATIONS"
        ),
        "checks_run": len(checks),
        "supported_matches": supported_count,
        "flags_count": len(flags),
        "checks": checks,
        "flags": flags,
        "limitations": [
            "Text matching does not prove that every sentence is factually correct.",
            "A matching value can still be used in a misleading statement.",
            "This reviewer is not an independent fraud classifier.",
            "Human review remains necessary before any operational decision.",
        ],
    }

