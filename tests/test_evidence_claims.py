from app.claim_linker import link_claims_to_evidence
from app.claim_reviewer import review_claim_links
from app.evidence import build_evidence_bundle


def bundle(**overrides):
    alert = {
        "transaction_id": "SYNTH-T1", "amount": "1200", "absolute_amount": "1200",
        "baseline_transactions": "3", "history_sufficient": "true",
        "past_median_amount": "100", "amount_multiple": "12",
    }
    alert.update(overrides)
    return build_evidence_bundle(alert)


def review(claim, source=None, **report_overrides):
    source = source or bundle()
    report = {"uncertainty": "medium", "limitations": ["Synthetic fixture"], **report_overrides}
    links = link_claims_to_evidence({"claims": [claim]}, source)
    return links, review_claim_links(links, source, report)


def fact(text, ref="E004", claim_type="observed_fact", uncertainty="medium"):
    return {"claim_type": claim_type, "claim": text, "evidence_refs": [ref], "uncertainty": uncertainty}


def test_source_consistent_claim_gets_source_status_not_truth_verification():
    links, result = review(fact("Recorded amount is 1200"))
    item = links["linked_claims"][0]
    assert item["claim_id"] == "CLM-001"
    assert item["evidence_refs"][0]["source_field"] == "amount"
    assert item["evidence_refs"][0]["source_record_id"] == "SYNTH-T1"
    assert result["claims"][0]["status"] == "SUPPORTED_BY_SOURCE"
    assert "does not prove" in result["status_definitions"]["SUPPORTED_BY_SOURCE"]


def test_valid_reference_with_false_numeric_claim_is_contradicted():
    _, result = review(fact("Recorded amount is 9999"))
    assert result["claims"][0]["status"] == "CONTRADICTED_BY_SOURCE"


def test_valid_reference_with_reversed_history_claim_is_contradicted():
    _, result = review(fact("There are no prior transactions in the baseline", "E010"))
    assert result["claims"][0]["status"] == "CONTRADICTED_BY_SOURCE"


def test_valid_reference_with_overgeneralized_ownership_claim_is_insufficient():
    _, result = review(fact("The counterparty is owned by the account holder", "E009"))
    assert result["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"


def test_valid_amount_reference_with_unverified_currency_is_insufficient():
    _, result = review(fact("The amount is INR 1200"))
    assert result["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"


def test_derived_amount_multiple_is_recomputed_from_cited_fields():
    links = link_claims_to_evidence({"claims": [{
        "claim_type": "derived_calculation", "claim": "1200 divided by 100 equals 12 times",
        "evidence_refs": ["E004", "E011", "E012"], "uncertainty": "medium",
    }]}, bundle())
    result = review_claim_links(links, bundle(), {"uncertainty": "medium", "limitations": ["Fixture"]})
    assert result["claims"][0]["status"] == "SUPPORTED_BY_SOURCE"
    wrong = link_claims_to_evidence({"claims": [{
        "claim_type": "derived_calculation", "claim": "1200 divided by 100 equals 8 times",
        "evidence_refs": ["E004", "E011", "E012"], "uncertainty": "medium",
    }]}, bundle())
    wrong_result = review_claim_links(wrong, bundle(), {"uncertainty": "medium", "limitations": ["Fixture"]})
    assert wrong_result["claims"][0]["status"] == "CONTRADICTED_BY_SOURCE"


def test_invalid_and_missing_references_are_insufficient():
    _, missing = review({"claim_type": "observed_fact", "claim": "The amount is 1200", "evidence_refs": [], "uncertainty": "medium"})
    _, invalid = review(fact("The amount is 1200", "E999"))
    assert missing["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"
    assert invalid["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"


def test_factual_claim_without_uncertainty_is_insufficient():
    _, result = review(fact("Recorded amount is 1200", uncertainty=None))
    assert result["claims"][0]["status"] == "INSUFFICIENT_EVIDENCE"


def test_missing_history_and_source_conflict_are_reported():
    missing_history = bundle(history_sufficient="false", baseline_transactions="0")
    _, result = review(fact("Recorded amount is 1200"), source=missing_history)
    assert any(check["check"] == "history_and_missing_information" for check in result["checks"])
    conflicting = bundle(absolute_amount="900")
    _, conflict_result = review(fact("Recorded amount is 1200"), source=conflicting)
    assert any(check["check"] == "conflicting_source_fields" for check in conflict_result["checks"])


def test_report_missing_uncertainty_and_limitations_is_flagged():
    _, result = review(fact("Recorded amount is 1200"), uncertainty=None, limitations=[])
    assert {check["check"] for check in result["checks"]} >= {"report_uncertainty", "report_limitations"}


def test_recommendation_is_not_presented_as_a_verified_fact():
    _, result = review({"claim_type": "recommendation", "claim": "Request transaction history", "evidence_refs": [], "uncertainty": "medium"})
    assert result["claims"][0]["status"] == "NOT_CHECKED"
