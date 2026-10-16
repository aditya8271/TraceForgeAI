from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import math
import os
import asyncio
import tempfile
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from pydantic import BaseModel, Field, field_validator

from app.evidence import build_evidence_bundle
from app.claim_linker import link_claims_to_evidence
from app.claim_reviewer import review_claim_links
from app.reviewer import review_investigation
from app.fraud_ring import evaluate_synthetic_rings
from app.graph_engine import FraudGraphEngine
from app.persistence import (
    DatabaseConfigurationError,
    connect as open_database_connection,
    ensure_sqlite_schema,
    using_postgres,
)

from app.services.gemini_investigator import (
    investigate_alert,
    GeminiInvestigationError,
)


ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = ROOT / "data" / "replay"
ALERTS_FILE = REPLAY_DIR / "replay_alerts.csv"
SUMMARY_FILE = REPLAY_DIR / "replay_summary.json"
DB_FILE = REPLAY_DIR / "investigations.db"

CASE_STATUSES = {"New", "Under Review", "Escalated", "Closed"}
REVIEW_DECISIONS = {"Approve", "Reject", "Escalate"}

app = FastAPI(
    title="TraceForge AI API",
    description="Historical transaction alerts and AI-assisted investigations",
    version="0.5.0",
)

cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "TRACEFORGE_CORS_ORIGINS", "http://localhost:3000"
    ).split(",")
    if origin.strip()
]

class RequestSizeLimitMiddleware:
    """Bound request bodies, including requests without Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value.decode("latin-1") for key, value in scope.get("headers", [])
             if key.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    response = JSONResponse(
                        {"detail": "Request body exceeds the configured size limit."},
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse({"detail": "Invalid Content-Length header."}, status_code=400)
                await response(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                response = JSONResponse(
                    {"detail": "Request body exceeds the configured size limit."},
                    status_code=413,
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        sent = False

        async def replay_body():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay_body, send)


try:
    MAX_REQUEST_BODY_BYTES = max(1024, min(
        int(os.getenv("TRACEFORGE_MAX_REQUEST_BYTES", "2200000")),
        10_000_000,
    ))
except ValueError:
    raise RuntimeError("TRACEFORGE_MAX_REQUEST_BYTES must be an integer.") from None
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class PublicDataImportRequest(BaseModel):
    source_name: str = Field(min_length=2, max_length=150)
    source_url: str = Field(min_length=8, max_length=1000)
    csv_text: str = Field(min_length=10, max_length=2_000_000)
    transactions_unit: str = Field(default="million transactions", min_length=1, max_length=80)
    value_unit: str = Field(default="crore INR", min_length=1, max_length=80)

    @field_validator("source_name", "source_url", "transactions_unit", "value_unit")
    @classmethod
    def trim_import_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class InvestigationRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=150)


class CaseUpsertRequest(BaseModel):
    case_key: str = Field(min_length=1, max_length=250)
    case_type: str = Field(min_length=1, max_length=40)
    account_id: Optional[str] = Field(default=None, max_length=150)
    transaction_id: Optional[str] = Field(default=None, max_length=150)
    status: str = Field(default="New", max_length=40)
    notes: str = Field(default="", max_length=20000)

    @field_validator("case_key", "case_type", "status")
    @classmethod
    def trim_required_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in CASE_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(CASE_STATUSES))}"
            )
        return value


class CaseReviewRequest(BaseModel):
    case_key: str = Field(min_length=1, max_length=250)
    decision: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=10, max_length=5000)
    actor: str = Field(
        default="Local analyst session",
        min_length=1,
        max_length=150,
    )

    @field_validator("case_key", "decision", "reason", "actor")
    @classmethod
    def trim_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        if value not in REVIEW_DECISIONS:
            raise ValueError(
                "decision must be Approve, Reject, or Escalate"
            )
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError("reason must contain at least 10 characters")
        return value

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        if not value:
            raise ValueError("actor cannot be empty")
        return value


def ensure_case_table():
    if using_postgres():
        return
    ensure_sqlite_schema(DB_FILE)


@contextmanager
def db_connection():
    with open_database_connection(DB_FILE) as connection:
        yield connection


def load_alerts():
    if not ALERTS_FILE.exists():
        raise HTTPException(
            status_code=503,
            detail="Historical replay alerts file is not available.",
        )
    try:
        with ALERTS_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            return list(csv.DictReader(file))
    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Could not read historical replay alerts file.",
        ) from None


def case_to_dict(row):
    return {key: row[key] for key in row.keys()}


def _reserve_gemini_request_slot() -> bool:
    """Atomically cap all Gemini-triggering routes across service instances."""
    try:
        limit = int(os.getenv("TRACEFORGE_GEMINI_MAX_REQUESTS_PER_MINUTE", "10"))
    except ValueError:
        raise HTTPException(status_code=503, detail="Gemini request limit is misconfigured.") from None
    if limit < 1:
        raise HTTPException(status_code=503, detail="Gemini request limit must be positive.")

    window = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    with db_connection() as con:
        row = con.execute("""
            INSERT INTO api_usage_counters (counter_key, window_start, request_count)
            VALUES ('gemini', ?, 1)
            ON CONFLICT(counter_key) DO UPDATE SET
                request_count = CASE
                    WHEN api_usage_counters.window_start = excluded.window_start
                    THEN api_usage_counters.request_count + 1
                    ELSE 1
                END,
                window_start = excluded.window_start
            WHERE api_usage_counters.window_start <> excluded.window_start
               OR api_usage_counters.request_count < ?
            RETURNING request_count
        """, (window, limit)).fetchone()
    return row is not None


def build_investigation_snapshot(alert: dict) -> dict:
    """Build a fresh investigation result for a review-time evidence snapshot."""
    evidence_bundle = build_evidence_bundle(alert)
    if not _reserve_gemini_request_slot():
        raise HTTPException(
            status_code=429,
            detail="Gemini request limit reached for this service. Try again next minute.",
            headers={"Retry-After": "60"},
        )
    report = investigate_alert(alert)
    reviewer_result = review_investigation(
        json.dumps(report, ensure_ascii=False) if isinstance(report, dict) else report,
        evidence_bundle,
    )
    claim_links = link_claims_to_evidence(report, evidence_bundle)
    if isinstance(report, dict) and isinstance(report.get("claims"), list):
        report = {
            **report,
            "claims": [
                {**claim, "claim_id": claim_links["linked_claims"][index]["claim_id"]}
                for index, claim in enumerate(report["claims"])
            ],
        }
    claim_review = review_claim_links(
        claim_links,
        evidence_bundle,
        report if isinstance(report, dict) else None,
    )

    return {
        "transaction_id": alert.get("transaction_id"),
        "source": "historical_replay",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "report": report,
        "reviewer": reviewer_result,
        "claim_links": claim_links,
        "claim_review": claim_review,
        "evidence_bundle": evidence_bundle,
        "limitations": [
            "This is historical replay data, not a live bank feed.",
            "Evidence references do not independently prove fraud.",
            "Counterparty identifiers do not prove beneficial ownership.",
            "The analyst decision is human-entered.",
            "Authentication is disabled in this local prototype; actor labels are not verified identities.",
        ],
    }


@app.get("/api/health")
def health():
    try:
        with db_connection() as con:
            con.execute("SELECT 1 FROM investigations LIMIT 0").fetchall()
            if using_postgres():
                con.execute("SELECT 1 FROM public_data_cache LIMIT 0").fetchall()
                storage = "postgresql"
            else:
                storage = "local_sqlite"
    except Exception:
        return JSONResponse(
            {"status": "unavailable", "service": "traceforge-api", "storage": "unavailable"},
            status_code=503,
        )
    return {"status": "ok", "service": "traceforge-api", "storage": storage}


PUBLIC_DATA_DIR = ROOT / "data" / "intelligence"
PUBLIC_DATA_FILE = PUBLIC_DATA_DIR / "public_payment_stats.json"
PUBLIC_DATA_STATUS_FILE = PUBLIC_DATA_DIR / "public_payment_stats_status.json"
NPCI_UPI_SOURCE = "https://www.npci.org.in/product/upi/product-statistics"


class _TableParser(HTMLParser):
    """Minimal standard-library HTML table parser."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.depth = 0
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            if self.depth == 0:
                self.tables.append([])
            self.depth += 1
        elif self.depth and tag == "tr":
            self.row = []
        elif self.depth and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.depth and tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif self.depth and tag == "tr":
            if self.row:
                self.tables[-1].append(self.row)
            self.row = None
        elif tag == "table" and self.depth:
            self.depth -= 1


def _fetch_npci_upi_statistics():
    """Fetch the published monthly table from NPCI's official HTML page."""
    request = Request(
        NPCI_UPI_SOURCE,
        headers={"User-Agent": "TraceForgeAI/1.0 (public statistics; local research tool)"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            html = response.read(5_000_001).decode("utf-8", errors="replace")
    except HTTPError as exc:
        message = (
            "NPCI is blocking automated access to its public statistics page (HTTP 403). "
            "Use the official page to download/copy its table and import the CSV manually."
            if exc.code == 403
            else f"NPCI statistics page returned HTTP {exc.code}."
        )
        error = RuntimeError(message)
        error.status_code = exc.code
        raise error from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"NPCI connection failed: {type(exc).__name__}"
        ) from None
    if len(html) > 5_000_000:
        raise RuntimeError("NPCI response exceeded the 5 MB size limit.")

    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception as exc:
        raise RuntimeError(f"NPCI statistics response was malformed ({type(exc).__name__}).") from None
    for table in parser.tables:
        for idx, row in enumerate(table[:6]):
            joined = " | ".join(row).lower()
            if "month" not in joined or "volume" not in joined or "value" not in joined:
                continue
            month_idx = next((i for i, cell in enumerate(row) if "month" in cell.lower()), None)
            volume_idx = next((i for i, cell in enumerate(row) if "volume" in cell.lower()), None)
            value_idx = next((i for i, cell in enumerate(row) if "value" in cell.lower()), None)
            if None in (month_idx, volume_idx, value_idx):
                continue
            rows = []
            for data_row in table[idx + 1:]:
                if max(month_idx, volume_idx, value_idx) >= len(data_row):
                    continue
                month = data_row[month_idx].strip()
                try:
                    volume = float(data_row[volume_idx].replace(",", "").strip())
                    value = float(data_row[value_idx].replace(",", "").strip())
                except ValueError:
                    continue
                if month and math.isfinite(volume) and math.isfinite(value) and volume >= 0 and value >= 0:
                    rows.append({
                        "month": month,
                        "transactions": volume,
                        "value": value,
                        "transactions_unit": "million transactions",
                        "value_unit": "crore INR",
                    })
            if rows:
                rows.reverse()  # NPCI generally lists newest month first.
                return rows
    raise RuntimeError("NPCI page was reached, but its monthly table could not be parsed. The page layout may have changed.")


def _atomic_write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _read_public_state():
    if using_postgres():
        with db_connection() as con:
            row = con.execute(
                "SELECT payload, refresh_status FROM public_data_cache WHERE id = 1"
            ).fetchone()
        if not row:
            return {"payload": None, "refresh_status": None}
        return {"payload": row["payload"], "refresh_status": row["refresh_status"]}

    result = {"payload": None, "refresh_status": None}
    for key, path in (
        ("payload", PUBLIC_DATA_FILE),
        ("refresh_status", PUBLIC_DATA_STATUS_FILE),
    ):
        try:
            result[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _persist_public_state(payload=None, refresh_status=None):
    if using_postgres():
        from psycopg.types.json import Jsonb

        with db_connection() as con:
            previous = con.execute(
                "SELECT payload, refresh_status FROM public_data_cache WHERE id = 1"
            ).fetchone() or {"payload": None, "refresh_status": None}
            new_payload = payload if payload is not None else previous["payload"]
            new_status = refresh_status if refresh_status is not None else previous["refresh_status"]
            con.execute("""
                INSERT INTO public_data_cache (id, payload, refresh_status)
                VALUES (1, ?, ?, CURRENT_TIMESTAMP::text)
                ON CONFLICT (id) DO UPDATE SET
                    payload = excluded.payload,
                    refresh_status = excluded.refresh_status,
                    updated_at = CURRENT_TIMESTAMP::text
            """, (
                Jsonb(new_payload) if new_payload is not None else None,
                Jsonb(new_status) if new_status is not None else None,
            ))
        return

    if payload is not None:
        _atomic_write_json(PUBLIC_DATA_FILE, payload)
    if refresh_status is not None:
        _atomic_write_json(PUBLIC_DATA_STATUS_FILE, refresh_status)


def _record_npci_status(source_status: str, message: str, status_code=None, success_at=None):
    previous = _read_public_state().get("refresh_status") or {}
    status = {
        "source_status": source_status,
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "last_success_at": success_at or previous.get("last_success_at"),
        "http_status": status_code,
        "message": message,
        "source_url": NPCI_UPI_SOURCE,
    }
    _persist_public_state(refresh_status=status)
    return status


def _save_auto_public_data(rows, source_name, source_url):
    if not rows:
        raise RuntimeError("NPCI statistics response contained no data rows.")
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "source_name": source_name,
        "source_url": source_url,
        "imported_at": fetched_at,
        "fetched_at": fetched_at,
        "data_period_start": rows[0]["month"],
        "data_period_end": rows[-1]["month"],
        "reporting_period_start": rows[0]["month"],
        "reporting_period_end": rows[-1]["month"],
        "row_count": len(rows),
        "transactions_unit": rows[0].get("transactions_unit", "million transactions"),
        "value_unit": rows[0].get("value_unit", "crore INR"),
        "rows": rows,
        "data_origin": "automatically_fetched_public_aggregate_data",
        "fetch_method": "public_html_table",
    }
    _persist_public_state(payload=payload)
    return payload


async def _initial_npci_refresh():
    """Attempt once at startup; a recorded 403 requires an explicit user refresh."""
    if os.getenv("TRACEFORGE_NPCI_AUTO_REFRESH", "true").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        return
    previous = _read_public_state().get("refresh_status") or {}
    if previous.get("http_status") == 403:
        return
    try:
        rows = await asyncio.to_thread(_fetch_npci_upi_statistics)
        payload = _save_auto_public_data(rows, "NPCI UPI Product Statistics", NPCI_UPI_SOURCE)
        _record_npci_status("available", "NPCI statistics were fetched successfully.", success_at=payload["fetched_at"])
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        state = "blocked" if status_code == 403 else "error"
        message = str(exc) if isinstance(exc, RuntimeError) else f"NPCI refresh failed ({type(exc).__name__})."
        _record_npci_status(state, message, status_code)
        print(f"[TraceForge NPCI source status: {state}] {message}")


@app.on_event("startup")
async def start_public_data_refresh():
    app.state.public_data_refresh_task = asyncio.create_task(_initial_npci_refresh())


@app.on_event("shutdown")
async def stop_public_data_refresh():
    task = getattr(app.state, "public_data_refresh_task", None)
    if task:
        task.cancel()
RBI_REPORTS_SOURCE = "https://www.rbi.org.in/scripts/AnnualReportPublications.aspx"


def _parse_public_monthly_csv(csv_text: str):
    """Parse user-supplied public aggregate statistics; never invent missing values."""
    reader = csv.DictReader(csv_text.splitlines())
    if not reader.fieldnames:
        raise ValueError("CSV needs a header row.")
    normalised = {str(name).strip().lower(): name for name in reader.fieldnames if name}
    month_key = next((normalised[k] for k in ("month", "period", "date", "reporting_month") if k in normalised), None)
    tx_key = next((normalised[k] for k in ("transactions", "transaction_count", "volume", "txn_count") if k in normalised), None)
    value_key = next((normalised[k] for k in ("value", "transaction_value", "amount", "total_value") if k in normalised), None)
    if not month_key or not tx_key or not value_key:
        raise ValueError("CSV headers must include month, transactions, value. Example: month,transactions,value")
    parsed = []
    for line_no, row in enumerate(reader, start=2):
        month = (row.get(month_key) or "").strip()
        if not month:
            continue
        # Keep original reporting period label; parse numbers after removing separators/currency marks.
        def number(raw):
            cleaned = str(raw or "").strip().replace(",", "").replace("₹", "").replace("$", "")
            if not cleaned:
                raise ValueError(f"Row {line_no}: missing numeric value.")
            result = float(cleaned)
            if not math.isfinite(result):
                raise ValueError(f"Row {line_no}: numeric values must be finite.")
            if result < 0:
                raise ValueError(f"Row {line_no}: negative values are not supported.")
            return result
        try:
            transactions = number(row.get(tx_key))
            value = number(row.get(value_key))
        except ValueError as exc:
            raise ValueError(f"Row {line_no}: {exc}") from None
        parsed.append({"month": month, "transactions": transactions, "value": value})
    if not parsed:
        raise ValueError("No data rows found in CSV.")
    # Sorting is chronological for ISO YYYY-MM; otherwise retain supplied order.
    if all(len(r["month"]) >= 7 and r["month"][4:5] == "-" for r in parsed):
        parsed.sort(key=lambda r: r["month"])
    return parsed


@app.post("/api/intelligence/refresh")
def refresh_public_data_now():
    """Make one explicitly requested fetch from NPCI's public statistics page."""
    try:
        rows = _fetch_npci_upi_statistics()
        payload = _save_auto_public_data(rows, "NPCI UPI Product Statistics", NPCI_UPI_SOURCE)
        _record_npci_status("available", "NPCI statistics were fetched successfully.", success_at=payload["fetched_at"])
    except RuntimeError as exc:
        status_code = getattr(exc, "status_code", None)
        source_status = "blocked" if status_code == 403 else "error"
        _record_npci_status(source_status, str(exc), status_code)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except OSError:
        _record_npci_status("error", "NPCI data could not be saved locally.")
        raise HTTPException(status_code=502, detail="Could not save fetched public data.") from None
    return {
        "message": "NPCI public statistics fetched successfully.",
        "data_status": "LIVE",
        "row_count": len(rows),
        "period_start": payload["data_period_start"],
        "period_end": payload["data_period_end"],
        "imported_at": payload["imported_at"],
        "source_url": NPCI_UPI_SOURCE,
    }


@app.get("/api/intelligence/public-data")
def get_public_data_insights():
    """Return insights computed only from imported public aggregate statistics."""
    stored_state = _read_public_state()
    refresh_status = stored_state["refresh_status"] or {
        "source_status": "not_checked",
        "message": "NPCI has not yet been checked by this service.",
        "source_url": NPCI_UPI_SOURCE,
    }
    payload = stored_state["payload"]
    if payload is None:
        return {
            "status": "empty",
            "data_status": "empty",
            "source_name": None,
            "source_url": NPCI_UPI_SOURCE,
            "last_updated": None,
            "rows": [],
            "insights": [],
            "row_count": 0,
            "refresh_status": refresh_status,
            "notice": refresh_status.get("message", "No public data available yet."),
        }
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="Cached public data has an invalid rows field.")
    insights = []
    # ISO reporting periods sort lexically; named months retain validated source/import order.
    if all(len(str(row.get("month", ""))) >= 7 and str(row.get("month", ""))[4:5] == "-" for row in rows):
        rows = sorted(rows, key=lambda r: str(r.get("month", "")))
    legacy_live_data = payload.get("data_origin") == "automatically_fetched_public_aggregate_data"
    transactions_unit = payload.get("transactions_unit") or (
        "million transactions" if legacy_live_data else (rows[0].get("transactions_unit") if rows else None)
    ) or "units not recorded"
    value_unit = payload.get("value_unit") or (
        "crore INR" if legacy_live_data else (rows[0].get("value_unit") if rows else None)
    ) or "units not recorded"
    for row in rows:
        row.setdefault("transactions_unit", transactions_unit)
        row.setdefault("value_unit", value_unit)

    if rows:
        latest = rows[-1]
        volume = float(latest.get("transactions", 0) or 0)
        value = float(latest.get("value", 0) or 0)
        # Only calculate the converted average when both published units are known.
        avg_ticket = (value / volume * 10) if volume > 0 and transactions_unit == "million transactions" and value_unit == "crore INR" else None
        insights.extend([
            {
                "metric": "Latest transaction volume",
                "latest_period": latest.get("month"),
                "latest_value": volume,
                "unit_note": f"Reported volume, in {transactions_unit}."
            },
            {
                "metric": "Latest transaction value",
                "latest_period": latest.get("month"),
                "latest_value": value,
                "unit_note": f"Reported value, in {value_unit}."
            },
            {
                "metric": "Average value per transaction",
                "latest_period": latest.get("month"),
                "latest_value": round(avg_ticket, 2) if avg_ticket is not None else None,
                "unit_note": "Estimated INR per transaction, calculated only when source units are million transactions and crore INR."
            }
        ])
    if len(rows) >= 2:
        previous, latest = rows[-2], rows[-1]
        for field, label in (("transactions", "Month-on-month transaction volume"), ("value", "Month-on-month transaction value")):
            old, new_value = float(previous[field]), float(latest[field])
            change = ((new_value - old) / old * 100) if old else None
            insights.append({
                "metric": label,
                "previous_period": previous["month"],
                "latest_period": latest["month"],
                "previous_value": old,
                "latest_value": new_value,
                "change_percent": round(change, 2) if change is not None else None,
                "direction": "up" if change is not None and change > 0 else "down" if change is not None and change < 0 else "unchanged" if change == 0 else "not_calculable",
            })
    if len(rows) >= 4:
        prior = rows[-4]
        latest = rows[-1]
        for field, label in (("transactions", "Three-month transaction volume change"), ("value", "Three-month transaction value change")):
            old, new_value = float(prior[field]), float(latest[field])
            change = ((new_value - old) / old * 100) if old else None
            insights.append({
                "metric": label,
                "previous_period": prior["month"],
                "latest_period": latest["month"],
                "previous_value": old,
                "latest_value": new_value,
                "change_percent": round(change, 2) if change is not None else None,
                "direction": "up" if change is not None and change > 0 else "down" if change is not None and change < 0 else "unchanged" if change == 0 else "not_calculable",
            })
    if rows:
        peak_volume = max(rows, key=lambda r: float(r.get("transactions", 0) or 0))
        peak_value = max(rows, key=lambda r: float(r.get("value", 0) or 0))
        insights.extend([
            {"metric": "Peak transaction volume in available history", "latest_period": peak_volume["month"], "latest_value": float(peak_volume["transactions"]), "unit_note": "Peak among fetched months only; not an all-time record unless the source provides full history."},
            {"metric": "Peak transaction value in available history", "latest_period": peak_value["month"], "latest_value": float(peak_value["value"]), "unit_note": "Peak among fetched months only; not an all-time record unless the source provides full history."},
        ])
    return {
        **payload,
        "rows": rows,
        "transactions_unit": transactions_unit,
        "value_unit": value_unit,
        "status": "ready" if rows else "empty",
        "row_count": len(rows),
        "data_status": "MANUALLY_IMPORTED" if payload.get("data_origin") == "user_imported_public_aggregate_data" else "CACHED",
        "refresh_status": refresh_status,
        "insights": insights,
        "notice": "Aggregate payment statistics describe overall reported activity. They do not show individual transactions, prove fraud, or establish that fraud increased or decreased.",
    }


@app.post("/api/intelligence/public-data/import")
def import_public_data(request: PublicDataImportRequest):
    """Import public monthly aggregates copied from an official source into the local prototype."""
    from urllib.parse import urlparse
    parsed_url = urlparse(request.source_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise HTTPException(status_code=422, detail="Source URL must be a valid HTTPS URL.")
    try:
        rows = _parse_public_monthly_csv(request.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    imported_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row["transactions_unit"] = request.transactions_unit
        row["value_unit"] = request.value_unit
    payload = {
        "source_name": request.source_name,
        "source_url": request.source_url,
        "imported_at": imported_at,
        "reporting_period_start": rows[0]["month"],
        "reporting_period_end": rows[-1]["month"],
        "data_period_start": rows[0]["month"],
        "data_period_end": rows[-1]["month"],
        "transactions_unit": request.transactions_unit,
        "value_unit": request.value_unit,
        "row_count": len(rows),
        "rows": rows,
        "data_origin": "user_imported_public_aggregate_data",
    }
    _persist_public_state(payload=payload)
    return {
        "message": "Public aggregate data imported successfully.",
        "data_status": "MANUALLY_IMPORTED",
        "source_name": request.source_name,
        "source_url": request.source_url,
        "imported_at": imported_at,
        "transactions_unit": request.transactions_unit,
        "value_unit": request.value_unit,
        "row_count": len(rows),
        "period_start": rows[0]["month"],
        "period_end": rows[-1]["month"],
        "next_step": "Open GET /api/intelligence/public-data to view calculated insights.",
    }


@app.get("/api/alerts")
def get_alerts(limit: int = 100, offset: int = 0):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be zero or greater")
    rows = load_alerts()
    columns = list(rows[0].keys()) if rows else []
    return {
        "source": "historical_replay",
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "columns": columns,
        "alerts": rows[offset:offset + limit],
    }


@app.get("/api/replay-summary")
def get_replay_summary():
    if not SUMMARY_FILE.exists():
        raise HTTPException(status_code=503, detail="Replay summary file is not available.")
    try:
        with SUMMARY_FILE.open("r", encoding="utf-8") as file:
            summary = json.load(file)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Could not read replay summary.") from None
    return {"source": "historical_replay", "summary": summary}


@app.post("/api/investigate")
def investigate(request: InvestigationRequest):
    transaction_id = request.transaction_id.strip()
    if not transaction_id:
        raise HTTPException(status_code=400, detail="transaction_id cannot be empty.")

    alert = next(
        (row for row in load_alerts()
         if row.get("transaction_id") == transaction_id),
        None,
    )
    if alert is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction alert not found in historical replay.",
        )

    try:
        snapshot = build_investigation_snapshot(alert)
    except GeminiInvestigationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    return {
        "transaction_id": transaction_id,
        "source": "historical_replay",
        "investigator": "Gemini",
        "status": "completed",
        "report": snapshot["report"],
        "reviewer": snapshot["reviewer"],
        "claim_links": snapshot["claim_links"],
        "claim_review": snapshot["claim_review"],
        "evidence_bundle": snapshot["evidence_bundle"],
        "disclaimer": (
            "AI-assisted analysis only. The evidence bundle references "
            "fields from the historical alert record; it does not prove "
            "fraud. A human analyst must review the evidence."
        ),
    }



@app.get("/api/synthetic/money-trails")
def get_synthetic_money_trails(
    source_account: str = Query(default="V001", min_length=1, max_length=150),
    max_hops: int = Query(default=4, ge=1, le=6),
    min_amount: float = Query(default=1000, ge=0),
    ):
    """Evidence-backed multi-hop paths over the controlled synthetic dataset."""
    generated_dir = ROOT / "data" / "generated"
    try:
        engine = FraudGraphEngine(data_dir=generated_dir)
        engine.load_data()
        trails = engine.find_money_trails(
            source_account=source_account, max_hops=max_hops, min_amount=min_amount
        )
        summary = engine.summary()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Synthetic dataset unavailable. Run generate_data.py first. {exc}",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "mode": "controlled_synthetic_dataset",
        "source_account": source_account,
        "max_hops": max_hops,
        "min_amount": min_amount,
        "graph_summary": summary,
        "trail_count": len(trails),
        "trails": trails[:250],
        "limitations": [
            "This endpoint uses the separate generated synthetic dataset, not NFPC counterparty IDs.",
            "Paths represent synthetic transaction records; they are not proof of real-world laundering.",
            "Amounts have no verified currency unit.",
        ],
    }


@app.get("/api/fraud-ring/evaluate")
def evaluate_fraud_ring_benchmark(max_hops: int = Query(default=4, ge=1, le=6)):
    """Run transparent account-level metrics against synthetic ground truth."""
    try:
        result = evaluate_synthetic_rings(ROOT / "data" / "generated", max_hops=max_hops)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Synthetic dataset unavailable. Run generate_data.py first. {exc}",
        ) from None
    return result


@app.get("/api/quality/portfolio")
def get_portfolio_quality():
    """Aggregate stored review snapshots across all cases; snapshots may repeat cases."""
    with db_connection() as con:
        case_rows = con.execute(
            "SELECT status, COUNT(*) AS count FROM investigations GROUP BY status"
        ).fetchall()
        review_rows = con.execute(
            """
            SELECT id, case_key, decision, evidence_snapshot, created_at
            FROM case_reviews ORDER BY id DESC
            """
        ).fetchall()

    status_counts = {row["status"]: row["count"] for row in case_rows}
    decision_counts = {"Approve": 0, "Reject": 0, "Escalate": 0}
    evidence_available = evidence_total = claims_with_refs = claims_total = 0
    claim_checks = claim_checks_passed = reviewer_flags = claim_flags = 0
    parse_errors = 0
    reviewed_case_keys = set()
    for row in review_rows:
        decision_counts[row["decision"]] = decision_counts.get(row["decision"], 0) + 1
        reviewed_case_keys.add(row["case_key"])
        try:
            snapshot = json.loads(row["evidence_snapshot"])
        except (json.JSONDecodeError, TypeError):
            parse_errors += 1
            continue
        bundle = snapshot.get("evidence_bundle") or {}
        evidence = bundle.get("evidence") or []
        evidence_total += len(evidence)
        evidence_available += sum(1 for item in evidence if item.get("available") is True)
        links = snapshot.get("claim_links") or {}
        claims = links.get("linked_claims") or []
        claims_total += len(claims)
        claims_with_refs += sum(1 for claim in claims if claim.get("evidence_refs"))
        claim_review = snapshot.get("claim_review") or {}
        claim_checks += int(claim_review.get("checks_run") or 0)
        claim_checks_passed += int(claim_review.get("passed_checks") or 0)
        reviewer_flags += int((snapshot.get("reviewer") or {}).get("flags_count") or 0)
        claim_flags += int(claim_review.get("flags_count") or 0)

    return {
        "scope": "all currently stored cases and review snapshots",
        "case_count": sum(status_counts.values()),
        "case_status_counts": status_counts,
        "review_count": len(review_rows),
        "distinct_reviewed_cases": len(reviewed_case_keys),
        "decision_counts": decision_counts,
        "evidence": {
            "available": evidence_available, "total": evidence_total,
            "coverage": round(evidence_available / evidence_total, 4) if evidence_total else None,
        },
        "claims": {
            "with_evidence_refs": claims_with_refs, "total": claims_total,
            "coverage": round(claims_with_refs / claims_total, 4) if claims_total else None,
        },
        "claim_reference_checks": {
            "passed": claim_checks_passed, "total": claim_checks,
            "pass_rate": round(claim_checks_passed / claim_checks, 4) if claim_checks else None,
        },
        "reported_flags": {"reviewer": reviewer_flags, "claim_reference": claim_flags},
        "snapshot_parse_errors": parse_errors,
        "limitations": [
            "Metrics aggregate saved review snapshots; repeated reviews count separately.",
            "Passing reference checks does not prove a claim is true or relevant.",
            "These metrics are operational QA indicators, not fraud-detection accuracy.",
            "Actor labels are local and unverified in this no-login prototype.",
        ],
    }


@app.get("/api/money-trail")
def get_money_trail(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    alerts = load_alerts()
    selected_alerts = alerts[:limit]
    nodes = {}
    edges = []

    for row in selected_alerts:
        transaction_id = (row.get("transaction_id") or "").strip()
        account_id = (row.get("account_id") or "").strip()
        counterparty_id = (row.get("counterparty_id") or "").strip()
        if not transaction_id:
            continue

        if account_id:
            nodes[f"account:{account_id}"] = {
                "id": f"account:{account_id}",
                "label": account_id,
                "type": "account",
            }

        nodes[f"transaction:{transaction_id}"] = {
            "id": f"transaction:{transaction_id}",
            "label": transaction_id,
            "type": "transaction",
            "amount": row.get("amount"),
            "txn_type": row.get("txn_type"),
            "timestamp": row.get("transaction_timestamp"),
            "channel": row.get("channel"),
            "alert_reasons": row.get("reasons"),
            "amount_multiple": row.get("amount_multiple"),
        }

        if counterparty_id:
            nodes[f"counterparty:{counterparty_id}"] = {
                "id": f"counterparty:{counterparty_id}",
                "label": counterparty_id,
                "type": "counterparty",
            }

        if account_id:
            edges.append({
                "id": f"account-transaction:{account_id}:{transaction_id}",
                "source": f"account:{account_id}",
                "target": f"transaction:{transaction_id}",
                "relationship": "account_recorded_transaction",
            })
        if counterparty_id:
            edges.append({
                "id": f"transaction-counterparty:{transaction_id}:{counterparty_id}",
                "source": f"transaction:{transaction_id}",
                "target": f"counterparty:{counterparty_id}",
                "relationship": "recorded_counterparty",
            })

    return {
        "source": "historical_replay_alerts",
        "total_alerts": len(alerts),
        "alerts_in_graph": len(selected_alerts),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
        "limitations": [
            "Graph is built from historical alert records, not all transactions.",
            "Account and counterparty identifiers are separate entity types.",
            "Edges represent recorded transaction associations, not verified beneficial ownership.",
            "Transaction direction and amount alone do not establish illicit fund movement.",
            "Currency is not verified in the available evidence.",
        ],
    }


@app.get("/api/cases")
def list_cases(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = None,
    search: Optional[str] = None,
    ):
    if status and status not in CASE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of: {', '.join(sorted(CASE_STATUSES))}",
        )

    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        where.append(
            "(case_key LIKE ? OR account_id LIKE ? OR transaction_id LIKE ? OR notes LIKE ?)"
        )
        params.extend([term, term, term, term])

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with db_connection() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM investigations" + where_sql, params
        ).fetchone()[0]
        rows = con.execute(
            """
            SELECT case_key, case_type, account_id, transaction_id,
                   status, notes, updated_at
            FROM investigations
            """
            + where_sql
            + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "statuses": sorted(CASE_STATUSES),
        "cases": [case_to_dict(row) for row in rows],
    }


@app.get("/api/case-audit/{case_key:path}")
def get_case_audit(case_key: str, limit: int = Query(default=100, ge=1, le=500)):
    with db_connection() as con:
        exists = con.execute(
            "SELECT 1 FROM investigations WHERE case_key = ?", (case_key,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Investigation case not found.")

        rows = con.execute(
            """
            SELECT id, case_key, action, field_name, old_value,
                   new_value, actor, created_at
            FROM case_audit_log
            WHERE case_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (case_key, limit),
        ).fetchall()

    return {
        "case_key": case_key,
        "total": len(rows),
        "events": [case_to_dict(row) for row in rows],
        "notice": (
            "Actor is a local session label, not a verified user identity; "
            "authentication is not configured."
        ),
    }


@app.get("/api/cases/{case_key:path}")
def get_case(case_key: str):
    with db_connection() as con:
        row = con.execute(
            """
            SELECT case_key, case_type, account_id, transaction_id,
                   status, notes, updated_at
            FROM investigations
            WHERE case_key = ?
            """,
            (case_key,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Investigation case not found.")
    return {"case": case_to_dict(row)}


@app.post("/api/cases")
def save_case(request: CaseUpsertRequest):
    case_key = request.case_key.strip()
    case_type = request.case_type.strip()
    if not case_key or not case_type:
        raise HTTPException(status_code=400, detail="case_key and case_type cannot be empty.")
    if case_type not in {"account", "transaction"}:
        raise HTTPException(status_code=400, detail="case_type must be 'account' or 'transaction'.")

    with db_connection() as con:
        previous = con.execute(
            """
            SELECT case_type, account_id, transaction_id, status, notes
            FROM investigations WHERE case_key = ?
            """,
            (case_key,),
        ).fetchone()

        con.execute(
            """
            INSERT INTO investigations (
                case_key, case_type, account_id, transaction_id,
                status, notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(case_key) DO UPDATE SET
                case_type = excluded.case_type,
                account_id = excluded.account_id,
                transaction_id = excluded.transaction_id,
                status = excluded.status,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                case_key, case_type, request.account_id,
                request.transaction_id, request.status, request.notes,
            ),
        )

        if previous is None:
            con.execute(
                """
                INSERT INTO case_audit_log
                    (case_key, action, field_name, old_value, new_value)
                VALUES (?, ?, ?, ?, ?)
                """,
                (case_key, "Case created", "status", None, request.status),
            )
            if request.notes.strip():
                con.execute(
                    """
                    INSERT INTO case_audit_log
                        (case_key, action, field_name, old_value, new_value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (case_key, "Notes added", "notes", None, request.notes),
                )
        else:
            if previous["status"] != request.status:
                con.execute(
                    """
                    INSERT INTO case_audit_log
                        (case_key, action, field_name, old_value, new_value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        case_key, "Status changed", "status",
                        previous["status"], request.status,
                    ),
                )
            if previous["notes"] != request.notes:
                con.execute(
                    """
                    INSERT INTO case_audit_log
                        (case_key, action, field_name, old_value, new_value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        case_key, "Notes updated", "notes",
                        previous["notes"], request.notes,
                    ),
                )

        row = con.execute(
            """
            SELECT case_key, case_type, account_id, transaction_id,
                   status, notes, updated_at
            FROM investigations WHERE case_key = ?
            """,
            (case_key,),
        ).fetchone()

    return {"message": "Case saved successfully.", "case": case_to_dict(row)}


@app.post("/api/case-review")
def submit_case_review(request: CaseReviewRequest):
    case_key = request.case_key.strip()
    reason = request.reason.strip()
    actor = request.actor.strip() or "Local analyst session"

    with db_connection() as con:
        case_row = con.execute(
            """
            SELECT case_key, case_type, account_id, transaction_id,
                   status, notes, updated_at
            FROM investigations WHERE case_key = ?
            """,
            (case_key,),
        ).fetchone()

    if case_row is None:
        raise HTTPException(status_code=404, detail="Investigation case not found.")

    case_data = case_to_dict(case_row)
    transaction_id = case_data.get("transaction_id")
    if not transaction_id:
        raise HTTPException(
            status_code=422,
            detail="This workflow requires a case linked to a transaction_id.",
        )

    alert = next(
        (row for row in load_alerts()
         if row.get("transaction_id") == transaction_id),
        None,
    )
    if alert is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction alert not found in historical replay.",
        )

    try:
        snapshot = build_investigation_snapshot(alert)
    except GeminiInvestigationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)

    with db_connection() as con:
        current_case = con.execute(
            "SELECT status FROM investigations WHERE case_key = ?",
            (case_key,),
        ).fetchone()
        if current_case is None:
            raise HTTPException(status_code=404, detail="Investigation case no longer exists.")

        old_status = current_case["status"]
        new_status = "Escalated" if request.decision == "Escalate" else old_status

        if request.decision == "Escalate" and old_status != "Escalated":
            con.execute(
                """
                UPDATE investigations
                SET status = 'Escalated', updated_at = CURRENT_TIMESTAMP
                WHERE case_key = ?
                """,
                (case_key,),
            )

        inserted_review = con.execute(
            """
            INSERT INTO case_reviews
                (case_key, decision, reason, actor, evidence_snapshot)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            (case_key, request.decision, reason, actor, snapshot_json),
        ).fetchone()
        review_id = inserted_review[0]

        con.execute(
            """
            INSERT INTO case_audit_log
                (case_key, action, field_name, old_value, new_value, actor)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                case_key,
                "Analyst decision recorded",
                "decision",
                None,
                json.dumps(
                    {"decision": request.decision, "reason": reason},
                    ensure_ascii=False,
                ),
                actor,
            ),
        )

        if request.decision == "Escalate" and old_status != "Escalated":
            con.execute(
                """
                INSERT INTO case_audit_log
                    (case_key, action, field_name, old_value, new_value, actor)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    case_key, "Status changed", "status",
                    old_status, "Escalated", actor,
                ),
            )

    return {
        "message": "Analyst decision recorded successfully.",
        "review_id": review_id,
        "case_key": case_key,
        "decision": request.decision,
        "reason": reason,
        "actor": actor,
        "case_status": new_status,
        "snapshot_saved": True,
        "reviewer": snapshot["reviewer"],
        "claim_review": snapshot["claim_review"],
        "disclaimer": (
            "This is a human-entered review decision, not an automated "
            "determination of fraud. Actor is an unverified local label."
        ),
    }


@app.get("/api/case-reviews/{case_key:path}")
def get_case_reviews(
    case_key: str,
    limit: int = Query(default=50, ge=1, le=200),
    ):
    with db_connection() as con:
        exists = con.execute(
            "SELECT 1 FROM investigations WHERE case_key = ?", (case_key,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Investigation case not found.")

        rows = con.execute(
            """
            SELECT id, case_key, decision, reason, actor,
                   evidence_snapshot, created_at
            FROM case_reviews
            WHERE case_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (case_key, limit),
        ).fetchall()

    reviews = []
    for row in rows:
        item = case_to_dict(row)
        try:
            item["evidence_snapshot"] = json.loads(item["evidence_snapshot"])
        except (json.JSONDecodeError, TypeError):
            item["evidence_snapshot"] = None
            item["snapshot_parse_error"] = True
        reviews.append(item)

    return {"case_key": case_key, "total": len(reviews), "reviews": reviews}
