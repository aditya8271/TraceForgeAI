
"""Link investigation claims to source evidence IDs.

This module creates traceable, source-grounded claims from the
historical alert evidence. It does not determine whether fraud occurred.
"""

import re


def _evidence_map(evidence_bundle: dict) -> dict:
    return {
        item["field"]: item
        for item in evidence_bundle.get("evidence", [])
    }


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _number_in_text(value, report: str) -> bool:
    expected = _number(value)
    if expected is None:
        return False

    matches = re.findall(
        r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?",
        report or "",
    )
    return any(
        _number(match) == expected
        for match in matches
    )


def link_claims_to_evidence(report: str, evidence_bundle: dict) -> dict:
    """Return claims linked to evidence fields and their source record."""

    evidence = _evidence_map(evidence_bundle)
    report_text = report or ""
    report_lower = report_text.lower()
    claims = []

    def add_claim(claim_id, text, fields, supported):
        references = []
        for field in fields:
            item = evidence.get(field)
            if item and item.get("available"):
                references.append({
                    "evidence_id": item["evidence_id"],
                    "field": field,
                    "source": item["source"],
                    "source_record_key": item["source_record_key"],
                })

        claims.append({
            "claim_id": claim_id,
            "claim": text,
            "evidence_refs": references,
            "link_status": (
                "MATCHED_TO_REPORT"
                if supported and references
                else "SOURCE_EVIDENCE_ONLY"
                if references
                else "NO_EVIDENCE_AVAILABLE"
            ),
        })

    amount = evidence.get("amount", {}).get("value")
    if amount is not None:
        amount_found = _number_in_text(amount, report_text)
        add_claim(
            "C001",
            f"Recorded transaction amount: {amount} (currency unspecified).",
            ["amount", "absolute_amount"],
            amount_found,
        )

    baseline = evidence.get("baseline_transactions", {}).get("value")
    history = evidence.get("history_sufficient", {}).get("value")
    if baseline is not None:
        baseline_is_zero = _number(baseline) == 0
        baseline_claim = (
            "No prior baseline transactions are recorded."
            if baseline_is_zero
            else f"Recorded prior baseline transaction count: {baseline}."
        )
        baseline_found = (
            ("zero" in report_lower or "0" in report_text)
            if baseline_is_zero
            else str(baseline).lower() in report_lower
        )
        add_claim(
            "C002",
            baseline_claim,
            ["baseline_transactions", "history_sufficient"],
            baseline_found,
        )

    reason = evidence.get("reasons", {}).get("value")
    if reason:
        reason_found = str(reason).lower() in report_lower
        add_claim(
            "C003",
            f"Recorded alert reason: {reason}.",
            ["reasons"],
            reason_found,
        )

    if history is not None:
        history_is_insufficient = str(history).strip().lower() == "false"
        if history_is_insufficient:
            acknowledges = any(
                phrase in report_lower
                for phrase in (
                    "insufficient baseline",
                    "baseline is completely missing",
                    "zero prior baseline",
                    "no prior baseline",
                    "no established transaction history",
                    "history_sufficient: false",
                )
            )
            add_claim(
                "C004",
                "Historical baseline is marked insufficient.",
                ["history_sufficient", "baseline_transactions"],
                acknowledges,
            )

    return {
        "source": evidence_bundle.get("source", "historical_replay"),
        "transaction_id": evidence_bundle.get("transaction_id"),
        "claim_count": len(claims),
        "linked_claims": claims,
        "limitations": [
            "These are selected source-grounded claims, not an exhaustive extraction of every report sentence.",
            "A linked evidence reference does not prove the claim is a sign of fraud.",
            "Text matching can miss equivalent wording or match misleading wording.",
            "Human review remains necessary.",
        ],
    }
