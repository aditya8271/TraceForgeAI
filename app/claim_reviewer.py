"""Conservative deterministic source-consistency checks, not truth verification."""

from __future__ import annotations

import re


NUMERIC_FIELDS = {
    "amount", "absolute_amount", "baseline_transactions",
    "past_median_amount", "amount_multiple",
}
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?")
SCOPE_PATTERNS = (
    r"\b(?:owned by|beneficial owner|account holder is|customer owns)\b",
    r"\b(?:all transactions|every transaction|entire account|always|never)\b",
    r"\b(?:account-wide|across the account|multiple accounts|other accounts|all counterparties)\b",
    r"\b(?:confirmed fraud|confirmed mule|illicit funds)\b",
)


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _claim_check(claim, references, evidence_by_id):
    text = str(claim.get("claim", "")).strip()
    claim_type = claim.get("claim_type")
    if not text:
        return "INSUFFICIENT_EVIDENCE", "Claim text is missing."
    if not references and claim_type != "recommendation":
        return "INSUFFICIENT_EVIDENCE", "Factual claim has no evidence reference."

    resolved = []
    for ref in references:
        if not isinstance(ref, dict):
            return "INSUFFICIENT_EVIDENCE", "Evidence reference is malformed."
        item = evidence_by_id.get(ref.get("evidence_id"))
        if item is None:
            return "INSUFFICIENT_EVIDENCE", f"Evidence reference {ref.get('evidence_id')!r} does not exist."
        if not item.get("available"):
            return "INSUFFICIENT_EVIDENCE", f"Evidence {item.get('evidence_id')} has no source value."
        if (ref.get("source_field") != item.get("field")
                or ref.get("source_record_id") != item.get("source_record_key")
                or ref.get("source") != item.get("source")):
            return "INSUFFICIENT_EVIDENCE", f"Evidence {item.get('evidence_id')} metadata does not match its source record."
        resolved.append(item)

    if claim_type == "recommendation":
        return "NOT_CHECKED", "Recommendations are proposed actions, not source facts."

    lowered = text.lower()
    if any(re.search(pattern, lowered) for pattern in SCOPE_PATTERNS):
        return "INSUFFICIENT_EVIDENCE", "The claim asserts ownership, universal scope, or confirmed wrongdoing beyond this alert record."

    history = next((item for item in resolved if item.get("field") in {"baseline_transactions", "history_sufficient"}), None)
    history_count = next((_number(item.get("value")) for item in resolved if item.get("field") == "baseline_transactions"), None)
    says_no_history = bool(re.search(r"\b(no|none|never|zero|without)\b.*\b(history|prior|previous|baseline|transaction)", lowered))
    says_has_history = bool(re.search(r"\b(has|have|recorded|established)\b.*\b(history|prior|previous|baseline|transaction)", lowered))
    if history_count is not None and history_count > 0 and says_no_history:
        return "CONTRADICTED_BY_SOURCE", "Claim says no prior activity, while the cited source records prior transactions."
    if history_count == 0 and says_has_history:
        return "CONTRADICTED_BY_SOURCE", "Claim says prior activity exists, while the cited source records zero baseline transactions."

    numbers = [_number(token) for token in NUMBER_RE.findall(text)]
    numbers = [number for number in numbers if number is not None]
    numeric_sources = [item for item in resolved if item.get("field") in NUMERIC_FIELDS]
    if numbers and numeric_sources:
        comparable = [_number(item.get("value")) for item in numeric_sources]
        comparable = [number for number in comparable if number is not None]
        if not comparable or any(number not in comparable for number in numbers):
            return "CONTRADICTED_BY_SOURCE", "The numeric value in the claim does not match the cited numeric source field(s)."
        if claim_type == "derived_calculation":
            fields = {item.get("field"): _number(item.get("value")) for item in resolved}
            if not {"amount", "past_median_amount", "amount_multiple"} <= fields.keys():
                return "INSUFFICIENT_EVIDENCE", "A derived amount multiple needs amount, baseline median, and recorded multiple fields."
            if not fields["past_median_amount"]:
                return "INSUFFICIENT_EVIDENCE", "The cited baseline median cannot support a ratio calculation."
            expected_ratio = abs(fields["amount"]) / fields["past_median_amount"]
            if abs(expected_ratio - fields["amount_multiple"]) > 1e-6 or expected_ratio not in numbers:
                return "CONTRADICTED_BY_SOURCE", "The claimed amount multiple does not match amount divided by past median."
            return "SUPPORTED_BY_SOURCE", "The cited amount divided by cited median reproduces the recorded multiple; this does not establish fraud or broader meaning."
        if len(numeric_sources) != 1 or len(set(numbers)) != 1:
            return "NOT_CHECKED", "Multiple numeric fields or values require an explicit field-to-value mapping that this deterministic check does not infer."
        if numbers[0] != comparable[0]:
            return "CONTRADICTED_BY_SOURCE", "Claim value does not equal the cited source field value."

    unit_tokens = {"usd", "inr", "rupees", "dollars", "transactions", "times", "x"}
    claimed_units = {token.lower() for token in re.findall(r"\b(?:USD|INR|rupees|dollars|transactions|times|x)\b", text, re.I)}
    expected_units = {str(item.get("unit", "unspecified")).lower() for item in numeric_sources}
    if claimed_units:
        if claim_type != "derived_calculation" and any(unit in {"source_units_unverified", "unspecified"} for unit in expected_units) and claimed_units & {"usd", "inr", "rupees", "dollars"}:
            return "INSUFFICIENT_EVIDENCE", "The source record does not verify the claimed currency or amount unit."
        if "ratio" in expected_units and claimed_units & {"transactions", "usd", "inr", "rupees", "dollars"}:
            return "CONTRADICTED_BY_SOURCE", "Claimed unit conflicts with the cited ratio field."
        if "transactions" in expected_units and claimed_units & {"usd", "inr", "rupees", "dollars", "times", "x"}:
            return "CONTRADICTED_BY_SOURCE", "Claimed unit conflicts with the cited transaction-count field."
        if claim_type != "derived_calculation" and any(unit in {"source_units_unverified", "unspecified"} for unit in expected_units) and claimed_units & {"transactions", "times", "x"}:
            return "INSUFFICIENT_EVIDENCE", "The source record does not establish the claimed unit."

    if numeric_sources and numbers:
        return "SUPPORTED_BY_SOURCE", "The cited numeric value and available unit information are consistent with this claim; this is not independent truth verification."

    source_values = [str(item.get("value", "")).strip().lower() for item in resolved]
    if any(value and value in lowered for value in source_values):
        return "SUPPORTED_BY_SOURCE", "The cited source value appears in the claim; this supports only that field-level statement."
    if claim_type == "observed_fact":
        return "INSUFFICIENT_EVIDENCE", "The cited fields do not deterministically establish this observed-fact claim."
    return "NOT_CHECKED", "The deterministic reviewer cannot establish semantic consistency for this claim."


def review_claim_links(claim_links: dict, evidence_bundle: dict, report: dict | None = None) -> dict:
    source_items = evidence_bundle.get("evidence", [])
    evidence_by_id = {item.get("evidence_id"): item for item in source_items if item.get("evidence_id")}
    claims = claim_links.get("linked_claims", [])
    reviews = []
    for claim in claims:
        if not claim.get("claim_id"):
            status, detail = "INSUFFICIENT_EVIDENCE", "Claim identifier is missing."
        elif claim.get("claim_type") not in {"observed_fact", "derived_calculation", "ai_interpretation", "recommendation"}:
            status, detail = "INSUFFICIENT_EVIDENCE", "Claim type is missing or unknown."
        elif claim.get("claim_type") in {"observed_fact", "derived_calculation"} and claim.get("uncertainty") not in {"low", "medium", "high"}:
            status, detail = "INSUFFICIENT_EVIDENCE", "Factual claim omitted a valid low, medium, or high uncertainty statement."
        else:
            status, detail = _claim_check(claim, claim.get("evidence_refs", []), evidence_by_id)
        reviews.append({"claim_id": claim.get("claim_id", "UNKNOWN"), "claim": claim.get("claim", ""), "claim_type": claim.get("claim_type"), "status": status, "meaning": detail})

    quality_checks = []
    if not claims:
        quality_checks.append({
            "check": "claims_present",
            "status": "INSUFFICIENT_EVIDENCE",
            "details": "Structured investigation contained no reviewable claims.",
        })
    if report is not None:
        if report.get("uncertainty") not in {"low", "medium", "high"}:
            quality_checks.append({"check": "report_uncertainty", "status": "INSUFFICIENT_EVIDENCE", "details": "Structured report omitted overall uncertainty."})
        if not report.get("limitations"):
            quality_checks.append({"check": "report_limitations", "status": "INSUFFICIENT_EVIDENCE", "details": "Structured report omitted limitations."})
    if evidence_bundle.get("warnings"):
        quality_checks.append({"check": "history_and_missing_information", "status": "NOT_CHECKED", "details": "Source evidence has warnings: " + " ".join(evidence_bundle["warnings"])})
    if evidence_bundle.get("conflicts"):
        quality_checks.append({"check": "conflicting_source_fields", "status": "CONTRADICTED_BY_SOURCE", "details": str(evidence_bundle["conflicts"])})

    return {
        "reviewer": "TraceForge Conservative Claim Reviewer",
        "review_status": "REVIEW_REQUIRED" if any(item["status"] in {"CONTRADICTED_BY_SOURCE", "INSUFFICIENT_EVIDENCE", "NOT_CHECKED"} for item in reviews + quality_checks) else "SOURCE_CONSISTENT_WITH_LIMITATIONS",
        "status_definitions": {
            "SUPPORTED_BY_SOURCE": "Cited source values are consistent with the narrow statement; this does not prove the broader claim or independent truth.",
            "CONTRADICTED_BY_SOURCE": "A deterministic comparison found a conflict with the cited source value or unit.",
            "INSUFFICIENT_EVIDENCE": "Required source, metadata, or scope support is missing or inadequate.",
            "NOT_CHECKED": "No safe deterministic semantic check applies; analyst review is required.",
        },
        "claims_reviewed": len(reviews),
        "claims": reviews,
        "checks": quality_checks,
        "checks_run": len(reviews) + len(quality_checks),
        "passed_checks": sum(item["status"] == "SUPPORTED_BY_SOURCE" for item in reviews),
        "flags_count": sum(item["status"] != "SUPPORTED_BY_SOURCE" for item in reviews + quality_checks),
        "limitations": [
            "Statuses report deterministic consistency with supplied source records, not full semantic truth verification.",
            "Natural-language scope detection is heuristic and can miss paraphrases or context.",
            "Human analyst review remains required for consequential decisions.",
        ],
    }
