import asyncio
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app import api


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Use isolated files so tests never touch the real replay database."""
    replay_dir = tmp_path / "replay"
    replay_dir.mkdir()
    alerts_file = replay_dir / "replay_alerts.csv"
    summary_file = replay_dir / "replay_summary.json"
    db_file = replay_dir / "investigations_test.db"

    rows = [
        {
            "transaction_id": "TXN_TEST_100",
            "account_id": "ACCT_TEST_100",
            "counterparty_id": "CP_TEST_100",
            "amount": "1200",
            "absolute_amount": "1200",
            "txn_type": "D",
            "transaction_timestamp": "2026-01-01T10:00:00",
            "channel": "test",
            "baseline_transactions": "0",
            "past_median_amount": "0",
            "amount_multiple": "6",
            "history_sufficient": "false",
            "reasons": "test_reason",
            "evidence_summary": "Fixture transaction for workflow validation",
            "alert_status": "Review",
        }
    ]
    with alerts_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary_file.write_text(json.dumps({"transactions_processed": 1}), encoding="utf-8")

    monkeypatch.setattr(api, "REPLAY_DIR", replay_dir)
    monkeypatch.setattr(api, "ALERTS_FILE", alerts_file)
    monkeypatch.setattr(api, "SUMMARY_FILE", summary_file)
    monkeypatch.setattr(api, "DB_FILE", db_file)
    monkeypatch.setattr(api, "GENERATED_DIR", tmp_path / "generated")
    intelligence_dir = tmp_path / "intelligence"
    monkeypatch.setattr(api, "PUBLIC_DATA_DIR", intelligence_dir)
    monkeypatch.setattr(api, "PUBLIC_DATA_FILE", intelligence_dir / "public_payment_stats.json")
    monkeypatch.setattr(api, "PUBLIC_DATA_STATUS_FILE", intelligence_dir / "public_payment_stats_status.json")

    # Keep the application startup hook offline and deterministic in all tests.
    async def skip_startup_refresh():
        return None

    monkeypatch.setattr(api, "_initial_npci_refresh", skip_startup_refresh)

    with TestClient(api.app) as test_client:
        yield test_client


def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_configured_data_root_resolves_replay_assets_to_expected_paths(tmp_path):
    data_root = tmp_path / "private-runtime-data"
    environment = os.environ.copy()
    environment["TRACEFORGE_DATA_DIR"] = str(data_root)
    probe = (
        "import json; from app import api; "
        "print(json.dumps({'alerts': str(api.ALERTS_FILE), "
        "'summary': str(api.SUMMARY_FILE), 'database': str(api.DB_FILE)}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        check=True,
        text=True,
    )
    paths = json.loads(result.stdout.splitlines()[-1])
    replay_dir = data_root / "replay"
    assert paths == {
        "alerts": str(replay_dir / "replay_alerts.csv"),
        "summary": str(replay_dir / "replay_summary.json"),
        "database": str(replay_dir / "investigations.db"),
    }


def test_health_does_not_require_database(client, monkeypatch):
    monkeypatch.setattr(api, "db_connection", lambda: (_ for _ in ()).throw(AssertionError("health must not connect to storage")))
    assert client.get("/api/health").status_code == 200


def test_ready_reports_missing_cloud_run_database(client, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "traceforge-test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_database_connection_failure_returns_safe_503(client, monkeypatch):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.invalid/test")
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(psycopg.OperationalError("connection failed for secret DSN")))
    response = client.get("/api/cases")
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "Persistent database is unavailable" in response.text


def test_cloud_runtime_rejects_unsafe_cors_and_invalid_database_timeout(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "traceforge-test")
    monkeypatch.setenv("TRACEFORGE_CORS_ORIGINS", "*")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.invalid/test")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "5")
    with pytest.raises(RuntimeError, match="exact HTTPS"):
        api.validate_runtime_configuration()
    monkeypatch.setenv("TRACEFORGE_CORS_ORIGINS", "https://traceforge.example")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "0")
    with pytest.raises(api.DatabaseConfigurationError, match="DB_CONNECT_TIMEOUT_SECONDS") as exc:
        api.validate_runtime_configuration()
    assert "secret" not in str(exc.value)


def test_cloud_runtime_can_start_without_optional_gemini_or_database(monkeypatch, caplog):
    monkeypatch.setenv("K_SERVICE", "traceforge-test")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TRACEFORGE_CORS_ORIGINS", "https://traceforge.example")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in ("GEMINI_API_KEY", "GEMINI_BACKUP_API_KEY", "GEMINI_BACKUP_API_KEY_2", "GEMINI_BACKUP_API_KEY_3"):
        monkeypatch.delenv(name, raising=False)
    api.validate_runtime_configuration()
    assert "without DATABASE_URL" in caplog.text


def test_missing_optional_replay_and_synthetic_assets_return_clear_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "ALERTS_FILE", tmp_path / "missing-alerts.csv")
    monkeypatch.setattr(api, "SUMMARY_FILE", tmp_path / "missing-summary.json")
    monkeypatch.setattr(api, "GENERATED_DIR", Path(__file__).resolve().parents[1] / "data" / "generated")
    missing_alerts = client.get("/api/alerts")
    assert missing_alerts.status_code == 503
    assert "SUPABASE_URL" in missing_alerts.json()["detail"]
    missing_summary = client.get("/api/replay-summary")
    assert missing_summary.status_code == 503
    assert "SUPABASE_URL" in missing_summary.json()["detail"]
    # Missing historical replay files do not take down the independent fixtures.
    trails = client.get("/api/synthetic/money-trails")
    assert trails.status_code == 200
    assert trails.json()["mode"] == "controlled_synthetic_dataset"
    assert trails.json()["trail_count"] > 0
    assert client.get("/api/fraud-ring/evaluate").status_code == 200
    assert client.get("/api/quality/portfolio").status_code == 200
    synthetic = client.get("/api/fraud-ring/evaluate")
    assert synthetic.json()["mode"] == "controlled_synthetic_benchmark"


def test_oversized_request_is_rejected_with_cors(client):
    response = client.post(
        "/api/public-data/import",
        content=b"x" * (api.MAX_REQUEST_BODY_BYTES + 1),
        headers={"Content-Type": "application/json", "Origin": "http://localhost:3000"},
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_production_frontend_origin_preflight(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "https://tracforge-ai.web.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://tracforge-ai.web.app"


def test_alerts_returns_historical_rows(client):
    response = client.get("/api/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "historical_replay"
    assert body["total"] == 1
    assert body["alerts"][0]["transaction_id"] == "TXN_TEST_100"


def test_alerts_rejects_invalid_limit(client):
    assert client.get("/api/alerts?limit=0").status_code == 400
    assert client.get("/api/alerts?limit=1001").status_code == 400


def test_replay_summary_returns_json(client):
    response = client.get("/api/replay-summary")
    assert response.status_code == 200
    assert response.json()["summary"]["transactions_processed"] == 1


def test_private_storage_downloads_only_approved_replay_assets(client, monkeypatch, tmp_path):
    secret = "test-supabase-secret-never-log"
    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", secret)
    alerts_file = tmp_path / "replay" / "replay_alerts.csv"
    summary_file = tmp_path / "replay" / "replay_summary.json"
    alerts_file.unlink(missing_ok=True)
    summary_file.unlink(missing_ok=True)
    monkeypatch.setattr(api, "ALERTS_FILE", alerts_file)
    monkeypatch.setattr(api, "SUMMARY_FILE", summary_file)
    payloads = {
        "replay_alerts.csv": (
            b"transaction_id,account_id,amount,txn_type,transaction_timestamp\n"
            b"TXN_PRIVATE_TEST,ACCT_PRIVATE_TEST,42.5,D,2026-01-01T00:00:00Z\n"
        ),
        "replay_summary.json": b'{"transactions_processed":1,"alerts_generated":1,"accounts_seen":1}',
    }
    requests = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_urlopen(request, timeout):
        requests.append(request)
        filename = request.full_url.rsplit("/", 1)[-1]
        return FakeResponse(payloads[filename])

    monkeypatch.setattr(api, "urlopen", fake_urlopen)
    alerts = client.get("/api/alerts")
    summary = client.get("/api/replay-summary")

    assert alerts.status_code == 200
    assert alerts.json()["alerts"][0]["transaction_id"] == "TXN_PRIVATE_TEST"
    assert summary.status_code == 200
    assert summary.json()["summary"]["transactions_processed"] == 1
    assert [request.full_url for request in requests] == [
        "https://project-ref.supabase.co/storage/v1/object/traceforge-replay/replay_alerts.csv",
        "https://project-ref.supabase.co/storage/v1/object/traceforge-replay/replay_summary.json",
    ]
    for request in requests:
        assert request.get_header("Apikey") == secret
        assert request.get_header("Authorization") == f"Bearer {secret}"
        assert "investigations.db" not in request.full_url
        assert "investigations.backup.db" not in request.full_url
    assert alerts_file.is_file() and summary_file.is_file()


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("replay_alerts.csv", b"transaction_id,amount\nTXN,12\n"),
        ("replay_summary.json", b"[]"),
    ],
)
def test_invalid_private_replay_asset_is_not_cached(client, monkeypatch, tmp_path, filename, payload):
    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret")
    alerts_file = tmp_path / "replay" / "replay_alerts.csv"
    summary_file = tmp_path / "replay" / "replay_summary.json"
    alerts_file.unlink(missing_ok=True)
    summary_file.unlink(missing_ok=True)
    monkeypatch.setattr(api, "ALERTS_FILE", alerts_file)
    monkeypatch.setattr(api, "SUMMARY_FILE", summary_file)
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))

    response = client.get("/api/alerts" if filename.endswith(".csv") else "/api/replay-summary")

    assert response.status_code == 503
    assert "test-secret" not in response.text
    assert not (alerts_file if filename.endswith(".csv") else summary_file).exists()


def test_private_storage_missing_credentials_and_missing_object_are_safe(client, monkeypatch, tmp_path, caplog):
    alerts_file = tmp_path / "missing" / "replay_alerts.csv"
    monkeypatch.setattr(api, "ALERTS_FILE", alerts_file)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.setattr(api, "urlopen", lambda *args, **kwargs: pytest.fail("must not request without credentials"))
    missing_credentials = client.get("/api/alerts")
    assert missing_credentials.status_code == 503
    assert "SUPABASE_URL" in missing_credentials.json()["detail"]

    secret = "secret-value-for-test"
    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", secret)

    def missing_object(request, timeout):
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(api, "urlopen", missing_object)
    missing_file = client.get("/api/alerts")
    assert missing_file.status_code == 503
    assert secret not in missing_file.text
    assert secret not in caplog.text
    assert not alerts_file.exists()


def test_money_trail_builds_nodes_and_edges(client):
    response = client.get("/api/money-trail?limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["alerts_in_graph"] == 1
    assert body["node_count"] == 3
    assert body["edge_count"] == 2


def test_create_case_and_audit_event(client):
    payload = {
        "case_key": "transaction:TXN_TEST_100",
        "case_type": "transaction",
        "account_id": "ACCT_TEST_100",
        "transaction_id": "TXN_TEST_100",
        "status": "New",
        "notes": "Created by automated test",
    }
    response = client.post("/api/cases", json=payload)
    assert response.status_code == 200
    assert response.json()["case"]["notes"] == payload["notes"]

    listing = client.get("/api/cases?search=TXN_TEST_100")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    audit = client.get("/api/case-audit/transaction:TXN_TEST_100")
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1
    assert audit.json()["events"]


def test_update_case_records_status_and_notes_changes(client):
    base = {
        "case_key": "transaction:TXN_TEST_200",
        "case_type": "transaction",
        "account_id": "ACCT_TEST_200",
        "transaction_id": "TXN_TEST_200",
        "status": "New",
        "notes": "Initial note",
    }
    assert client.post("/api/cases", json=base).status_code == 200

    updated = {**base, "status": "Escalated", "notes": "Escalated for review"}
    response = client.post("/api/cases", json=updated)
    assert response.status_code == 200
    assert response.json()["case"]["status"] == "Escalated"

    audit = client.get("/api/case-audit/transaction:TXN_TEST_200")
    assert audit.status_code == 200
    fields = {event["field_name"] for event in audit.json()["events"]}
    assert "status" in fields
    assert "notes" in fields


def test_invalid_case_status_is_rejected(client):
    payload = {
        "case_key": "transaction:TXN_BAD_STATUS",
        "case_type": "transaction",
        "transaction_id": "TXN_BAD_STATUS",
        "status": "Fraud Confirmed Automatically",
        "notes": "test",
    }
    assert client.post("/api/cases", json=payload).status_code == 422


def test_missing_case_returns_404(client):
    assert client.get("/api/cases/transaction:DOES_NOT_EXIST").status_code == 404
    assert client.get("/api/case-audit/transaction:DOES_NOT_EXIST").status_code == 404


def test_investigation_uses_mocked_gemini(client, monkeypatch):
    monkeypatch.setattr(api, "investigate_alert", lambda alert: "Mocked report")
    response = client.post("/api/investigate", json={"transaction_id": "TXN_TEST_100"})
    assert response.status_code == 200
    assert response.json()["report"] == "Mocked report"


def test_gemini_requests_are_capped_across_investigation_calls(client, monkeypatch):
    monkeypatch.setenv("TRACEFORGE_GEMINI_MAX_REQUESTS_PER_MINUTE", "1")
    calls = []
    monkeypatch.setattr(api, "investigate_alert", lambda alert: calls.append(alert) or "Mock report")
    first = client.post("/api/investigate", json={"transaction_id": "TXN_TEST_100"})
    second = client.post("/api/investigate", json={"transaction_id": "TXN_TEST_100"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert len(calls) == 1


def test_end_to_end_investigation_case_decision_and_audit(client, monkeypatch):
    report = (
        "Review TXN_TEST_100 for account ACCT_TEST_100 at 2026-01-01T10:00:00. "
        "Recorded amount 1200, transaction type D, channel test, counterparty "
        "CP_TEST_100, baseline_transactions 0, past median 0, amount multiple 6. "
        "Historical baseline is insufficient; reason test_reason needs human review."
    )
    monkeypatch.setattr(api, "investigate_alert", lambda alert: report)

    selected_alert = client.get("/api/alerts?limit=10").json()["alerts"][0]
    assert selected_alert["transaction_id"] == "TXN_TEST_100"

    investigation = client.post("/api/investigate", json={"transaction_id": selected_alert["transaction_id"]})
    assert investigation.status_code == 200
    result = investigation.json()
    assert result["source"] == "historical_replay"
    assert result["evidence_bundle"]["transaction_id"] == "TXN_TEST_100"
    assert result["reviewer"]["checks"]
    assert result["claim_links"]["linked_claims"]
    assert result["claim_review"]["checks_run"] > 0

    case_key = "transaction:TXN_TEST_100"
    saved = client.post("/api/cases", json={
        "case_key": case_key,
        "case_type": "transaction",
        "account_id": "ACCT_TEST_100",
        "transaction_id": "TXN_TEST_100",
        "status": "New",
        "notes": "E2E audit test",
    })
    assert saved.status_code == 200

    decision = client.post("/api/case-review", json={
        "case_key": case_key,
        "decision": "Escalate",
        "reason": "Escalate for human review",
        "actor": "E2E test analyst",
    })
    assert decision.status_code == 200
    assert decision.json()["decision"] == "Escalate"
    assert decision.json()["reviewer"]["checks"]
    assert decision.json()["claim_review"]["checks_run"] > 0

    review_history = client.get(f"/api/case-reviews/{case_key}")
    audit_history = client.get(f"/api/case-audit/{case_key}")
    assert review_history.status_code == 200
    assert review_history.json()["reviews"][0]["decision"] == "Escalate"
    assert review_history.json()["reviews"][0]["evidence_snapshot"]["evidence_bundle"]["transaction_id"] == "TXN_TEST_100"
    assert audit_history.status_code == 200
    assert any(event["action"] == "Analyst decision recorded" for event in audit_history.json()["events"])


def test_structured_claim_review_and_decision_persist_end_to_end(client, monkeypatch):
    report = {
        "summary": "Historical alert requires review.",
        "claims": [
            {"claim_type": "observed_fact", "claim": "Recorded amount is 1200", "evidence_refs": ["E004"], "uncertainty": "medium"},
            {"claim_type": "observed_fact", "claim": "Recorded amount is 9999", "evidence_refs": ["E004"], "uncertainty": "medium"},
            {"claim_type": "recommendation", "claim": "Obtain more transaction history", "evidence_refs": [], "uncertainty": "medium"},
        ],
        "alternative_explanations": ["A legitimate one-off payment is possible."],
        "missing_information": ["Customer purpose is unavailable."],
        "uncertainty": "high",
        "recommended_next_steps": ["Review source transaction details."],
        "limitations": ["Historical replay record only."],
    }
    monkeypatch.setattr(api, "investigate_alert", lambda alert: report)

    investigation = client.post("/api/investigate", json={"transaction_id": "TXN_TEST_100"})
    assert investigation.status_code == 200
    result = investigation.json()
    assert result["report"]["claims"]
    assert result["report"]["claims"][0]["claim_id"] == "CLM-001"
    assert result["claim_links"]["linked_claims"][0]["claim_id"] == "CLM-001"
    reference = result["claim_links"]["linked_claims"][0]["evidence_refs"][0]
    assert reference["source_field"] == "amount"
    assert reference["source_record_id"] == "TXN_TEST_100"
    statuses = {claim["status"] for claim in result["claim_review"]["claims"]}
    assert "SUPPORTED_BY_SOURCE" in statuses
    assert "CONTRADICTED_BY_SOURCE" in statuses
    assert "NOT_CHECKED" in statuses

    case_key = "transaction:TXN_TEST_100"
    assert client.post("/api/cases", json={
        "case_key": case_key, "case_type": "transaction", "transaction_id": "TXN_TEST_100",
        "status": "New", "notes": "Structured workflow persistence fixture",
    }).status_code == 200
    decision = client.post("/api/case-review", json={
        "case_key": case_key, "decision": "Escalate",
        "reason": "Source contradiction requires analyst review", "actor": "Test analyst",
    })
    assert decision.status_code == 200
    history = client.get(f"/api/case-reviews/{case_key}").json()["reviews"]
    assert history[0]["decision"] == "Escalate"
    snapshot = history[0]["evidence_snapshot"]
    assert snapshot["report"]["claims"][1]["claim"] == "Recorded amount is 9999"
    assert any(claim["status"] == "CONTRADICTED_BY_SOURCE" for claim in snapshot["claim_review"]["claims"])
    audit = client.get(f"/api/case-audit/{case_key}").json()["events"]
    assert any(event["action"] == "Analyst decision recorded" for event in audit)


def test_investigation_unknown_transaction_returns_404(client):
    response = client.post("/api/investigate", json={"transaction_id": "TXN_UNKNOWN"})
    assert response.status_code == 404


def test_public_csv_import_parses_and_labels_manual_data(client, monkeypatch, tmp_path):
    response = client.post("/api/intelligence/public-data/import", json={
        "source_name": "Official sample",
        "source_url": "https://example.gov/statistics",
        "csv_text": "month,transactions,value\n2026-01,1,2\n2026-02,3,6\n",
        "transactions_unit": "million transactions",
        "value_unit": "crore INR",
    })
    assert response.status_code == 200
    body = client.get("/api/intelligence/public-data").json()
    assert body["data_origin"] == "user_imported_public_aggregate_data"
    assert body["data_status"] == "MANUALLY_IMPORTED"
    assert body["row_count"] == 2
    assert body["rows"][-1]["month"] == "2026-02"
    assert body["reporting_period_start"] == "2026-01"
    assert body["transactions_unit"] == "million transactions"
    assert body["imported_at"]
    assert body["insights"][0]["latest_value"] == 3


def test_public_csv_import_rejects_missing_numeric_values(client):
    response = client.post("/api/intelligence/public-data/import", json={
        "source_name": "Official sample",
        "source_url": "https://example.gov/statistics",
        "csv_text": "month,transactions,value\n2026-01,,2\n",
    })
    assert response.status_code == 422


def test_npci_http_403_is_source_specific_and_preserves_cache(client, monkeypatch):
    original = {
        "source_name": "Previously fetched NPCI data",
        "source_url": api.NPCI_UPI_SOURCE,
        "data_origin": "automatically_fetched_public_aggregate_data",
        "rows": [{"month": "2026-01", "transactions": 1, "value": 2}],
    }
    api._atomic_write_json(api.PUBLIC_DATA_FILE, original)
    requested_urls = []

    def blocked_request(request, timeout):
        requested_urls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(api, "urlopen", blocked_request)
    response = client.post("/api/intelligence/refresh")
    assert response.status_code == 502
    assert "NPCI" in response.json()["detail"] and "403" in response.json()["detail"]
    assert requested_urls == [api.NPCI_UPI_SOURCE]
    assert json.loads(api.PUBLIC_DATA_FILE.read_text(encoding="utf-8")) == original
    body = client.get("/api/intelligence/public-data").json()
    assert body["data_status"] == "CACHED"
    assert body["refresh_status"]["source_status"] == "blocked"
    assert body["refresh_status"]["http_status"] == 403


def test_startup_does_not_retry_previously_blocked_npcisource(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "PUBLIC_DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "PUBLIC_DATA_FILE", tmp_path / "public_payment_stats.json")
    monkeypatch.setattr(api, "PUBLIC_DATA_STATUS_FILE", tmp_path / "public_payment_stats_status.json")
    api._atomic_write_json(api.PUBLIC_DATA_STATUS_FILE, {"http_status": 403, "source_status": "blocked"})
    calls = []
    monkeypatch.setattr(api, "_fetch_npci_upi_statistics", lambda: calls.append("fetch"))

    asyncio.run(api._initial_npci_refresh())

    assert calls == []


def test_malformed_npci_html_is_reported_without_changing_cache(client, monkeypatch):
    original = {"source_name": "Last good data", "rows": [{"month": "2026-01", "transactions": 1, "value": 2}]}
    api._atomic_write_json(api.PUBLIC_DATA_FILE, original)

    def malformed_request(request, timeout):
        return io.BytesIO(b"<!doctype html><html><body>You need to enable JavaScript</body></html>")

    monkeypatch.setattr(api, "urlopen", malformed_request)
    response = client.post("/api/intelligence/refresh")
    assert response.status_code == 502
    assert "could not be parsed" in response.json()["detail"]
    assert json.loads(api.PUBLIC_DATA_FILE.read_text(encoding="utf-8")) == original
    assert client.get("/api/intelligence/public-data").json()["refresh_status"]["source_status"] == "error"


def test_successful_npci_refresh_records_live_rows_and_cache(client, monkeypatch):
    html = b"""<table>
      <tr><th>Month</th><th>No. of Banks live on UPI</th><th>Volume (In Mn.)</th><th>Value (In Cr.)</th></tr>
      <tr><td>February-2026</td><td>700</td><td>10,000.00</td><td>20,000.00</td></tr>
      <tr><td>January-2026</td><td>690</td><td>9,000.00</td><td>18,000.00</td></tr>
    </table>"""

    def successful_request(request, timeout):
        return io.BytesIO(html)

    monkeypatch.setattr(api, "urlopen", successful_request)
    response = client.post("/api/intelligence/refresh")
    assert response.status_code == 200
    assert response.json()["data_status"] == "LIVE"
    assert response.json()["row_count"] == 2
    body = client.get("/api/intelligence/public-data").json()
    assert body["data_status"] == "CACHED"
    assert body["rows"][0]["month"] == "January-2026"
    assert body["transactions_unit"] == "million transactions"
    assert body["value_unit"] == "crore INR"
