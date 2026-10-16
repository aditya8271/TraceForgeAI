"""Normalize model claims and attach trusted source metadata.

This module links references; it never decides that a claim is true.
"""

from __future__ import annotations

from typing import Any


CLAIM_TYPES = {
    "observed_fact",
    "derived_calculation",
    "ai_interpretation",
    "recommendation",
}


def link_claims_to_evidence(report: dict | str, evidence_bundle: dict) -> dict:
    source_items = evidence_bundle.get("evidence", [])
    by_id = {item.get("evidence_id"): item for item in source_items}
    claims: list[dict[str, Any]] = []
    structured_claims = report.get("claims", []) if isinstance(report, dict) else []
    if isinstance(report, dict) and not structured_claims:
        for section in ("observed_evidence", "interpretations"):
            for raw in report.get(section, []):
                if isinstance(raw, dict):
                    structured_claims.append({
                        **raw,
                        "claim_type": "observed_fact" if section == "observed_evidence" else "ai_interpretation",
                    })

    # Compatibility for existing API callers that still return plain report text.
    if not isinstance(report, dict):
        structured_claims = [{
            "claim_type": "ai_interpretation",
            "claim": str(report or ""),
            "evidence_refs": [],
            "uncertainty": None,
        }]

    for index, raw in enumerate(structured_claims, start=1):
        if not isinstance(raw, dict):
            raw = {"claim": str(raw), "claim_type": "ai_interpretation", "evidence_refs": []}
        claim_type = raw.get("claim_type") or "unknown"
        references = raw.get("evidence_refs", [])
        if not isinstance(references, list):
            references = []
        linked_refs = []
        for reference in references:
            evidence_id = reference.get("evidence_id") if isinstance(reference, dict) else reference
            item = by_id.get(evidence_id)
            if item:
                linked_refs.append({
                    "evidence_id": evidence_id,
                    "field": item.get("field"),
                    "source_record_key": item.get("source_record_key"),
                    "source_field": item.get("field"),
                    "source": item.get("source"),
                    "source_record_id": item.get("source_record_key"),
                    "value": item.get("value"),
                    "unit": item.get("unit", "unspecified"),
                })
            else:
                linked_refs.append({
                    "evidence_id": evidence_id,
                    "field": None,
                    "source_record_key": None,
                    "source_field": None,
                    "source": None,
                    "source_record_id": None,
                    "value": None,
                    "unit": "unspecified",
                })

        claims.append({
            "claim_id": f"CLM-{index:03d}",
            "claim_type": claim_type,
            "claim": str(raw.get("claim", "")).strip(),
            "uncertainty": raw.get("uncertainty"),
            "evidence_refs": linked_refs,
            "link_status": "REFERENCE_ATTACHED" if linked_refs else "MISSING_REFERENCE",
        })

    return {
        "source": evidence_bundle.get("source", "historical_replay"),
        "transaction_id": evidence_bundle.get("transaction_id"),
        "claim_count": len(claims),
        "linked_claims": claims,
        "limitations": [
            "Server-assigned links identify cited records; they do not establish claim truth.",
            "Deterministic checks are conservative and do not replace analyst judgment.",
        ],
    }
