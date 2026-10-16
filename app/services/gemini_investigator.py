
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from app.evidence import EVIDENCE_FIELDS, FIELD_UNITS


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class GeminiInvestigationError(Exception):
    """Safe, user-facing Gemini investigation error."""


def _status_code(exc):
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)

        if callable(value):
            try:
                value = value()
            except Exception:
                continue

        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass

    return None


def _error_kind(exc):
    status = _status_code(exc)
    message = str(exc).lower()
    name = type(exc).__name__.lower()

    if (
        status == 429
        or "resource_exhausted" in message
        or "quota exceeded" in message
        or "rate limit" in message
        or "too many requests" in message
    ):
        return "quota"

    if status in (400, 401, 403, 404):
        return "configuration"

    if status in (500, 502, 503, 504):
        return "transient"

    transient_names = (
        "timeout",
        "connectionerror",
        "connecterror",
        "networkerror",
        "remoteprotocolerror",
    )

    if any(term in name for term in transient_names):
        return "transient"

    transient_messages = (
        "timed out",
        "connection reset",
        "connection refused",
        "temporary failure",
        "server unavailable",
        "name resolution",
    )

    if any(term in message for term in transient_messages):
        return "transient"

    return "unknown"


def _configured_clients():
    candidates = [
        (
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            "primary",
        ),
        (
            os.getenv("GEMINI_BACKUP_API_KEY"),
            os.getenv("GEMINI_BACKUP_MODEL", "gemini-2.5-flash"),
            "backup 1",
        ),
        (
            os.getenv("GEMINI_BACKUP_API_KEY_2"),
            os.getenv("GEMINI_BACKUP_MODEL_2", "gemini-2.5-flash"),
            "backup 2",
        ),
        (
            os.getenv("GEMINI_BACKUP_API_KEY_3"),
            os.getenv("GEMINI_BACKUP_MODEL_3", "gemini-2.5-flash"),
            "backup 3",
        ),
    ]

    result = []
    seen = set()

    for key, model, label in candidates:
        if key and key not in seen:
            seen.add(key)
            result.append((key, model, label))

    if not result:
        raise GeminiInvestigationError(
            "Gemini API key is not configured. Check your local .env file."
        )

    return result


def _build_prompt(evidence):
    allowed = (
        "transaction_id",
        "account_id",
        "transaction_timestamp",
        "amount",
        "absolute_amount",
        "txn_type",
        "channel",
        "mcc_code",
        "counterparty_id",
        "past_median_amount",
        "amount_multiple",
        "baseline_transactions",
        "history_sufficient",
        "reasons",
        "evidence_summary",
        "alert_status",
    )

    clean = {}

    for field in allowed:
        if field in evidence:
            value = evidence[field]

            if value is not None:
                clean[field] = value

    clean["evidence_reference_map"] = {
        f"E{index:03d}": {
            "source_field": field,
            "value": evidence.get(field),
            "unit": FIELD_UNITS.get(field, "unspecified"),
        }
        for index, field in enumerate(EVIDENCE_FIELDS, start=1)
    }

    evidence_json = json.dumps(
        clean,
        default=str,
        ensure_ascii=False,
    )

    return f"""
You are an analyst assistant for TraceForge AI, a financial-crime
investigation prototype.

Analyze only the supplied evidence.

Do not claim that fraud or mule activity is confirmed.
Do not invent account relationships, transaction history,
customer details, currency, or facts absent from the evidence.

Clearly distinguish:

1. Observed evidence
2. Why it may deserve review
3. Alternative benign explanations
4. Recommended next checks for a human analyst
5. Limitations and missing evidence

Return only valid JSON with this schema:
{{"summary":"...","claims":[{{"claim_type":"observed_fact|derived_calculation|ai_interpretation|recommendation","claim":"...","evidence_refs":["E004"],"uncertainty":"low|medium|high"}}],
"alternative_explanations":["..."],"missing_information":["..."],
"uncertainty":"low|medium|high","recommended_next_steps":["..."],"limitations":["..."]}}
Give every claim an evidence reference when it states a fact. Recommendations may have no evidence reference. Use only IDs present in evidence_reference_map, never infer a field or record. Use observed_fact only for a narrow statement directly represented by a source field; derived_calculation only for a reproducible calculation and name its formula in the claim; distinguish interpretation from fact. State units and uncertainty. Do not expand one-record alert evidence into account-wide or ownership claims.

A high amount or unusual ratio alone does not prove fraud.
If the historical baseline is insufficient or tiny, say so.
Never recommend automatic account freezing.
The human reviewer makes the final decision.

Evidence:
{evidence_json}
""".strip()


def investigate_alert(evidence):
    if not isinstance(evidence, dict):
        raise GeminiInvestigationError(
            "Alert evidence must be a dictionary."
        )

    prompt = _build_prompt(evidence)
    candidates = _configured_clients()
    try:
        timeout_seconds = int(os.getenv("TRACEFORGE_GEMINI_TIMEOUT_SECONDS", "30"))
        if not 1 <= timeout_seconds <= 120:
            raise ValueError
    except ValueError:
        raise GeminiInvestigationError(
            "Gemini timeout must be between 1 and 120 seconds."
        ) from None

    for index, (api_key, model, label) in enumerate(candidates):
        try:
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
            )

            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )

            result = getattr(response, "text", None)

            if not result or not result.strip():
                raise GeminiInvestigationError(
                    "Gemini returned an empty investigation."
                )

            try:
                report = json.loads(result.strip())
            except (json.JSONDecodeError, TypeError):
                raise GeminiInvestigationError("Gemini returned a report that did not match the required JSON format.") from None
            required = ("summary", "claims", "alternative_explanations", "missing_information", "uncertainty", "recommended_next_steps", "limitations")
            if not isinstance(report, dict) or any(key not in report for key in required):
                raise GeminiInvestigationError("Gemini returned an incomplete structured investigation.")
            for key in ("claims", "alternative_explanations", "missing_information", "recommended_next_steps", "limitations"):
                if not isinstance(report[key], list):
                    raise GeminiInvestigationError("Gemini returned an invalid structured investigation.")
            for claim in report["claims"]:
                if not isinstance(claim, dict) or not str(claim.get("claim", "")).strip():
                    raise GeminiInvestigationError("Gemini returned a malformed claim.")
            if report["uncertainty"] not in {"low", "medium", "high"}:
                report["uncertainty"] = None
            return report

        except GeminiInvestigationError:
            raise

        except Exception as exc:
            kind = _error_kind(exc)

            # Do not rotate keys to bypass quotas.
            if kind == "quota":
                raise GeminiInvestigationError(
                    "Gemini quota/rate limit reached. "
                    "No backup key was tried."
                ) from None

            # Authentication, permissions and request configuration errors.
            if kind == "configuration":
                raise GeminiInvestigationError(
                    "Gemini configuration or permission error. "
                    "Check the project API key, API access and model."
                ) from None

            # Only recognized temporary failures allow failover.
            if kind != "transient":
                raise GeminiInvestigationError(
                    "Gemini request failed. Check service configuration."
                ) from None

            if index == len(candidates) - 1:
                raise GeminiInvestigationError(
                    "Gemini is temporarily unavailable across configured "
                    "projects. Please try again later."
                ) from None

    raise GeminiInvestigationError(
        "Gemini investigation could not run."
    )
