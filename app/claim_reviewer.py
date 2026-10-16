
"""Evidence-aware review of claim-to-evidence references."""

def review_claim_links(claim_links: dict, evidence_bundle: dict) -> dict:
    source_items = evidence_bundle.get("evidence", [])

    evidence_by_id = {
        item.get("evidence_id"): item
        for item in source_items
        if item.get("evidence_id")
    }

    checks = []
    flags = []

    def add_check(claim_id, check_name, status, details):
        result = {
            "claim_id": claim_id,
            "check": check_name,
            "status": status,
            "details": details,
        }
        checks.append(result)

        if status != "PASS":
            flags.append(result)

    linked_claims = claim_links.get("linked_claims", [])

    for claim in linked_claims:
        claim_id = claim.get("claim_id", "UNKNOWN")
        references = claim.get("evidence_refs", [])

        if not references:
            add_check(
                claim_id,
                "evidence_presence",
                "REVIEW_REQUIRED",
                "Claim has no evidence references.",
            )
            continue

        for reference in references:
            evidence_id = reference.get("evidence_id")
            source_item = evidence_by_id.get(evidence_id)

            if source_item is None:
                add_check(
                    claim_id,
                    "evidence_id_exists",
                    "FAIL",
                    f"Evidence ID {evidence_id!r} was not found in the evidence bundle.",
                )
                continue

            add_check(
                claim_id,
                "evidence_id_exists",
                "PASS",
                f"Evidence ID {evidence_id} exists in the evidence bundle.",
            )

            expected_field = source_item.get("field")
            cited_field = reference.get("field")

            if cited_field != expected_field:
                add_check(
                    claim_id,
                    "evidence_field_matches",
                    "FAIL",
                    f"Cited field {cited_field!r} differs from source field {expected_field!r}.",
                )
            else:
                add_check(
                    claim_id,
                    "evidence_field_matches",
                    "PASS",
                    f"Evidence field {expected_field!r} matches.",
                )

            expected_source = source_item.get("source")
            cited_source = reference.get("source")

            if cited_source != expected_source:
                add_check(
                    claim_id,
                    "evidence_source_matches",
                    "FAIL",
                    "Cited source does not match the evidence bundle.",
                )
            else:
                add_check(
                    claim_id,
                    "evidence_source_matches",
                    "PASS",
                    "Evidence source matches.",
                )

            expected_record = source_item.get("source_record_key")
            cited_record = reference.get("source_record_key")

            if cited_record != expected_record:
                add_check(
                    claim_id,
                    "source_record_key_matches",
                    "FAIL",
                    "Cited source record key does not match the evidence bundle.",
                )
            else:
                add_check(
                    claim_id,
                    "source_record_key_matches",
                    "PASS",
                    "Source record key matches.",
                )

    if not linked_claims:
        add_check(
            "NONE",
            "claims_present",
            "REVIEW_REQUIRED",
            "No linked claims were supplied for review.",
        )

    return {
        "reviewer": "TraceForge Evidence-Aware Claim Reviewer",
        "review_status": (
            "REVIEW_REQUIRED"
            if flags
            else "REFERENCE_CHECKS_PASSED"
        ),
        "claims_reviewed": len(linked_claims),
        "checks_run": len(checks),
        "passed_checks": sum(
            check["status"] == "PASS" for check in checks
        ),
        "flags_count": len(flags),
        "checks": checks,
        "flags": flags,
        "limitations": [
            "This verifies reference integrity, not the truth of the claim.",
            "A valid evidence reference may still be irrelevant to the claim.",
            "It does not independently verify every sentence in the Gemini report.",
            "Human review remains necessary before operational decisions.",
        ],
    }
