import pytest

from app.services import gemini_investigator as gemini


def configured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_BACKUP_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_BACKUP_API_KEY_2", raising=False)
    monkeypatch.delenv("GEMINI_BACKUP_API_KEY_3", raising=False)


def test_gemini_timeout_returns_safe_transient_error(monkeypatch):
    configured(monkeypatch)

    class Client:
        def __init__(self, **kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            raise TimeoutError("provider timeout")

    monkeypatch.setattr(gemini.genai, "Client", Client)
    with pytest.raises(gemini.GeminiInvestigationError, match="temporarily unavailable"):
        gemini.investigate_alert({"transaction_id": "SYNTH-TIMEOUT"})


def test_gemini_provider_failure_is_safely_reported(monkeypatch):
    configured(monkeypatch)

    class ProviderError(Exception):
        status_code = 503

    class Client:
        def __init__(self, **kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            raise ProviderError("private provider detail")

    monkeypatch.setattr(gemini.genai, "Client", Client)
    with pytest.raises(gemini.GeminiInvestigationError, match="temporarily unavailable") as error:
        gemini.investigate_alert({"transaction_id": "SYNTH-503"})
    assert "private provider detail" not in str(error.value)


def test_gemini_malformed_json_is_rejected(monkeypatch):
    configured(monkeypatch)

    class Client:
        def __init__(self, **kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            return type("Response", (), {"text": "{this is not valid json"})()

    monkeypatch.setattr(gemini.genai, "Client", Client)
    with pytest.raises(gemini.GeminiInvestigationError, match="JSON format"):
        gemini.investigate_alert({"transaction_id": "SYNTH-BAD-JSON"})


def test_gemini_structured_report_requires_claim_fields(monkeypatch):
    configured(monkeypatch)
    payload = {
        "summary": "Review only", "claims": [{"claim": "Amount is 100", "claim_type": "observed_fact", "evidence_refs": ["E004"], "uncertainty": "medium"}],
        "alternative_explanations": [], "missing_information": [], "uncertainty": "medium",
        "recommended_next_steps": [], "limitations": ["Historical record only"],
    }

    class Client:
        def __init__(self, **kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            import json
            return type("Response", (), {"text": json.dumps(payload)})()

    monkeypatch.setattr(gemini.genai, "Client", Client)
    result = gemini.investigate_alert({"transaction_id": "SYNTH-STRUCTURED"})
    assert result["claims"][0]["claim_type"] == "observed_fact"
