from pathlib import Path
from app.services.gemini_investigator import (
    investigate_alert,
    GeminiInvestigationError,
)
import json
import sqlite3

import joblib
import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
FEATURES_FILE = ROOT / "data" / "features" / "account_features.csv"
MODEL_FILE = ROOT / "models" / "mule_counterparty_model.joblib"
REPORT_FILE = ROOT / "data" / "reports" / "counterparty_model_metrics.json"
ALERTS_FILE = ROOT / "data" / "replay" / "replay_alerts.csv"
DB_FILE = ROOT / "data" / "replay" / "investigations.db"

STATUSES = ["New", "Under Review", "Escalated", "Closed"]


st.set_page_config(
    page_title="TraceForge AI",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ TraceForge AI")
st.caption("Financial Crime Investigation & Mule-Account Risk Triage")
st.warning(
    "Decision support only. Model scores and replay alerts are not proof "
    "of fraud. Analysts must review the available evidence."
)


# -------------------- Persistent case database --------------------

def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS investigations (
                case_key TEXT PRIMARY KEY,
                case_type TEXT NOT NULL,
                account_id TEXT,
                transaction_id TEXT,
                status TEXT NOT NULL DEFAULT 'New',
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def get_case(case_key, case_type, account_id=None, transaction_id=None):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM investigations WHERE case_key = ?",
            (case_key,),
        ).fetchone()

    if row:
        return dict(row)

    return {
        "case_key": case_key,
        "case_type": case_type,
        "account_id": account_id,
        "transaction_id": transaction_id,
        "status": "New",
        "notes": "",
        "updated_at": "",
    }


def save_case(case_key, case_type, account_id, transaction_id, status, notes):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO investigations (
                case_key, case_type, account_id, transaction_id,
                status, notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(case_key) DO UPDATE SET
                status = excluded.status,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
        """, (
            case_key,
            case_type,
            account_id,
            transaction_id,
            status,
            notes,
        ))
        conn.commit()


initialize_database()


# -------------------- Load account model and features --------------------

required_files = [FEATURES_FILE, MODEL_FILE]
missing = [str(path) for path in required_files if not path.exists()]

if missing:
    st.error("Required files not found:\n" + "\n".join(missing))
    st.stop()


@st.cache_data
def load_features(path, modified):
    return pd.read_csv(path)


@st.cache_resource
def load_model(path, modified):
    return joblib.load(path)


df = load_features(str(FEATURES_FILE), FEATURES_FILE.stat().st_mtime)
artifact = load_model(str(MODEL_FILE), MODEL_FILE.stat().st_mtime)

pipeline = artifact["pipeline"]
threshold = float(artifact["threshold"])
required_features = artifact.get("features", [])

if not required_features:
    st.error("Model artifact does not contain its feature list.")
    st.stop()

missing_features = [c for c in required_features if c not in df.columns]
if missing_features:
    st.error(f"Feature CSV is missing model inputs: {missing_features}")
    st.stop()

scores = pipeline.predict_proba(df[required_features])[:, 1]

df = df.copy()
df["risk_score"] = scores
df["risk_band"] = pd.cut(
    df["risk_score"],
    bins=[-0.001, 0.10, 0.30, 1.001],
    labels=["Lower", "Moderate", "Elevated"],
)
df["review_recommended"] = df["risk_score"] >= threshold


# -------------------- Sidebar filters --------------------

with st.sidebar:
    st.header("Account Filters")

    search_id = st.text_input("Search account ID").strip().upper()
    selected_risk = st.selectbox(
        "Risk band", ["All", "Lower", "Moderate", "Elevated"]
    )
    selected_status = st.selectbox(
        "Account review status", ["All"] + STATUSES
    )
    only_review = st.checkbox(
        "Only accounts above model threshold", value=False
    )


account_view = df.copy()

if search_id:
    account_view = account_view[
        account_view["account_id"].astype(str).str.upper().str.contains(
            search_id, regex=False
        )
    ]

if selected_risk != "All":
    account_view = account_view[
        account_view["risk_band"].astype(str) == selected_risk
    ]

if only_review:
    account_view = account_view[account_view["review_recommended"]]

# Retrieve persisted account-review states.
with get_connection() as conn:
    saved_accounts = pd.read_sql_query(
        """
        SELECT case_key, status, notes
        FROM investigations
        WHERE case_type = 'account'
        """,
        conn,
    )

status_map = (
    dict(zip(saved_accounts["case_key"], saved_accounts["status"]))
    if not saved_accounts.empty else {}
)

account_view["review_status"] = account_view["account_id"].map(
    status_map
).fillna("New")

if selected_status != "All":
    account_view = account_view[
        account_view["review_status"] == selected_status
    ]

account_view = account_view.sort_values("risk_score", ascending=False)


# -------------------- Dashboard overview --------------------

total_accounts = len(df)
labelled = int(df["is_mule"].notna().sum()) if "is_mule" in df else 0
review_count = int(df["review_recommended"].sum())
elevated_count = int((df["risk_band"] == "Elevated").sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Accounts Profiled", f"{total_accounts:,}")
c2.metric("Model Review Queue", f"{review_count:,}")
c3.metric("Elevated Risk Band", f"{elevated_count:,}")
c4.metric("Labelled Accounts", f"{labelled:,}")

st.caption(
    f"Account model threshold: {threshold:.2f} · "
    "Risk bands are display groupings, not calibrated fraud probabilities."
)


# -------------------- Load replay alerts --------------------

if ALERTS_FILE.exists():
    try:
        alerts = pd.read_csv(ALERTS_FILE)
        alerts_load_error = None
    except Exception as exc:
        alerts = pd.DataFrame()
        alerts_load_error = str(exc)
else:
    alerts = pd.DataFrame()
    alerts_load_error = None


if not alerts.empty:
    # Keep identifiers as strings and ensure numeric fields are usable.
    for column in [
        "amount",
        "absolute_amount",
        "past_median_amount",
        "amount_multiple",
        "baseline_transactions",
    ]:
        if column in alerts.columns:
            alerts[column] = pd.to_numeric(
                alerts[column], errors="coerce"
            )

    if "transaction_id" not in alerts.columns:
        alerts["transaction_id"] = ""

    if "account_id" not in alerts.columns:
        alerts["account_id"] = ""


# -------------------- Tabs --------------------

account_tab, alert_tab, report_tab = st.tabs([
    "Account Investigations",
    "Transaction Replay & Alerts",
    "Model Evaluation",
])


# -------------------- Account investigations --------------------

with account_tab:
    st.subheader("Account Investigation Queue")

    display_columns = [
        c for c in [
            "account_id",
            "risk_score",
            "risk_band",
            "review_recommended",
            "review_status",
            "txn_count",
            "debit_count",
            "credit_count",
            "distinct_counterparties",
            "debit_counterparties",
            "credit_counterparties",
            "total_abs_amount",
            "is_mule",
        ]
        if c in account_view.columns
    ]

    st.dataframe(
        account_view[display_columns].head(500),
        use_container_width=True,
        hide_index=True,
        column_config={
            "risk_score": st.column_config.NumberColumn(
                "Model Score", format="%.4f"
            ),
            "review_recommended": st.column_config.CheckboxColumn(
                "Above Threshold"
            ),
            "is_mule": st.column_config.NumberColumn(
                "Known Label (evaluation only)", format="%d"
            ),
        },
    )

    st.caption(
        f"Showing {min(len(account_view), 500):,} of "
        f"{len(account_view):,} matching accounts."
    )

    st.divider()
    st.subheader("Investigate an Account")

    account_ids = account_view["account_id"].astype(str).tolist()

    if not account_ids:
        st.info("No accounts match the selected filters.")
    else:
        selected_account = st.selectbox(
            "Select account",
            account_ids,
            key="account_detail_select",
        )

        row = df.loc[
            df["account_id"].astype(str) == selected_account
        ].iloc[0]

        case_key = f"account:{selected_account}"
        case = get_case(
            case_key, "account", account_id=selected_account
        )

        left, right = st.columns(2)

        with left:
            st.markdown("### Risk Assessment")
            st.metric("Account model score", f"{row['risk_score']:.4f}")
            st.write("Risk band:", str(row["risk_band"]))
            st.write(
                "Above model review threshold:",
                "Yes" if row["review_recommended"] else "No",
            )
            st.markdown("### Transaction Evidence")

            evidence_fields = [
                ("Transaction count", "txn_count"),
                ("Debit transactions", "debit_count"),
                ("Credit transactions", "credit_count"),
                ("Unique counterparties", "distinct_counterparties"),
                ("Debit counterparties", "debit_counterparties"),
                ("Credit counterparties", "credit_counterparties"),
                ("Distinct channels", "distinct_channels"),
                ("Active days", "active_days"),
                ("Absolute debit amount (dataset units)", "debit_abs_amount"),
                ("Absolute credit amount (dataset units)", "credit_abs_amount"),
                ("Average balance (source units)", "avg_balance"),
                ("KYC compliant", "kyc_compliant"),
                ("Product family", "product_family"),
            ]

            for label, column in evidence_fields:
                if column not in df.columns:
                    continue

                value = row[column]
                if pd.isna(value):
                    value = "Not available"
                elif isinstance(value, float):
                    value = f"{value:,.2f}"

                st.write(f"**{label}:** {value}")

        with right:
            st.markdown("### Persistent Analyst Review")

            status = st.selectbox(
                "Review status",
                STATUSES,
                index=STATUSES.index(
                    case["status"]
                    if case["status"] in STATUSES else "New"
                ),
                key=f"account_status_{selected_account}",
            )

            notes = st.text_area(
                "Investigation notes",
                value=case["notes"],
                key=f"account_notes_{selected_account}",
                placeholder="Record evidence reviewed and next steps.",
            )

            if st.button(
                "Save account review",
                type="primary",
                key=f"save_account_{selected_account}",
            ):
                save_case(
                    case_key,
                    "account",
                    selected_account,
                    None,
                    status,
                    notes,
                )
                st.success("Account review saved to SQLite.")
                st.rerun()


# -------------------- Transaction replay alerts --------------------

with alert_tab:
    st.subheader("Historical Transaction Replay & Alerts")
    st.caption(
        "These are rule-based historical replay alerts, not confirmed fraud "
        "and not a live bank transaction feed."
    )

    if alerts_load_error:
        st.error(f"Could not read replay alerts: {alerts_load_error}")
    elif alerts.empty:
        st.info(
            "No replay alerts file found or the file is empty. "
            "Run app/replay_transactions.py to generate alerts."
        )
    else:
        a1, a2, a3 = st.columns(3)
        a1.metric("Replay Alerts", f"{len(alerts):,}")
        a2.metric(
            "Accounts In Alert Queue",
            f"{alerts['account_id'].nunique():,}",
        )
        a3.metric(
            "Sufficient History",
            f"{int(alerts['history_sufficient'].fillna(False).sum()):,}"
            if "history_sufficient" in alerts.columns
            else "Not recorded",
        )

        f1, f2, f3 = st.columns(3)

        with f1:
            alert_search = st.text_input(
                "Search alert account ID",
                key="alert_account_filter",
            ).strip().upper()

        with f2:
            reason_options = ["All"] + sorted(
                alerts["reasons"].dropna().astype(str).unique().tolist()
            )
            selected_reason = st.selectbox(
                "Exact alert reason",
                reason_options,
                key="alert_reason_filter",
            )

        with f3:
            only_sufficient = st.checkbox(
                "Only alerts with sufficient history",
                value=False,
            )

        alert_view = alerts.copy()

        if alert_search:
            alert_view = alert_view[
                alert_view["account_id"].astype(str).str.upper().str.contains(
                    alert_search, regex=False
                )
            ]

        if selected_reason != "All":
            alert_view = alert_view[
                alert_view["reasons"].astype(str) == selected_reason
            ]

        if only_sufficient and "history_sufficient" in alert_view.columns:
            alert_view = alert_view[
                alert_view["history_sufficient"].fillna(False).astype(bool)
            ]

        if "amount_multiple" in alert_view.columns:
            alert_view = alert_view.sort_values(
                "amount_multiple", ascending=False, na_position="last"
            )

        alert_columns = [
            c for c in [
                "transaction_timestamp",
                "transaction_id",
                "account_id",
                "amount",
                "txn_type",
                "channel",
                "past_median_amount",
                "amount_multiple",
                "baseline_transactions",
                "history_sufficient",
                "reasons",
                "alert_status",
            ]
            if c in alert_view.columns
        ]

        st.dataframe(
            alert_view[alert_columns].head(1000),
            use_container_width=True,
            hide_index=True,
            column_config={
                "amount": st.column_config.NumberColumn(
                    "Amount (source units)", format="%.2f"
                ),
                "past_median_amount": st.column_config.NumberColumn(
                    "Past median", format="%.2f"
                ),
                "amount_multiple": st.column_config.NumberColumn(
                    "Amount multiple", format="%.2fx"
                ),
            },
        )

        st.caption(
            f"Showing {min(len(alert_view), 1000):,} of "
            f"{len(alert_view):,} matching alerts."
        )

        if not alert_view.empty:
            st.divider()
            st.subheader("Investigate a Replay Alert")

            options = alert_view.index.tolist()

            def format_alert(index):
                r = alert_view.loc[index]
                return (
                    f"{r.get('transaction_id', 'Unknown transaction')} | "
                    f"{r.get('account_id', 'Unknown account')} | "
                    f"{r.get('reasons', 'No reason recorded')}"
                )

            selected_index = st.selectbox(
                "Select alert",
                options,
                format_func=format_alert,
                key="selected_replay_alert",
            )

            selected = alert_view.loc[selected_index]
            tx_id = str(selected.get("transaction_id", ""))
            account_id = str(selected.get("account_id", ""))
            case_key = f"transaction:{tx_id}"
            case = get_case(
                case_key,
                "transaction",
                account_id=account_id,
                transaction_id=tx_id,
            )

            left, right = st.columns(2)

            with left:
                st.markdown("### Alert Evidence")
                for label, column in [
                    ("Transaction ID", "transaction_id"),
                    ("Account ID", "account_id"),
                    ("Timestamp", "transaction_timestamp"),
                    ("Amount", "amount"),
                    ("Transaction type", "txn_type"),
                    ("Channel", "channel"),
                    ("Counterparty ID", "counterparty_id"),
                    ("Past median", "past_median_amount"),
                    ("Amount multiple", "amount_multiple"),
                    ("Prior transactions", "baseline_transactions"),
                    ("History sufficient", "history_sufficient"),
                    ("Reasons", "reasons"),
                    ("Evidence summary", "evidence_summary"),
                ]:
                    if column in selected.index:
                        value = selected[column]
                        if pd.isna(value):
                            value = "Not available"
                        st.write(f"**{label}:** {value}")

                account_match = df[
                    df["account_id"].astype(str) == account_id
                ]

                if not account_match.empty:
                    account_score = float(
                        account_match.iloc[0]["risk_score"]
                    )
                    st.metric(
                        "Account-level model score (separate signal)",
                        f"{account_score:.4f}",
                    )
                    st.caption(
                        "This is an account-level score, not a prediction "
                        "that this individual transaction is fraudulent."
                    )

            with right:
                st.markdown("### Persistent Case Review")

                tx_status = st.selectbox(
                    "Case status",
                    STATUSES,
                    index=STATUSES.index(
                        case["status"]
                        if case["status"] in STATUSES else "New"
                    ),
                    key=f"tx_status_{tx_id}",
                )

                tx_notes = st.text_area(
                    "Investigation notes",
                    value=case["notes"],
                    key=f"tx_notes_{tx_id}",
                    placeholder="Record what was reviewed and any follow-up.",
                )

                st.divider()
                st.markdown("### Gemini AI Investigation")
                st.caption(
                    "AI-generated triage assistance based only on the selected "
                    "alert evidence. Verify findings; this is not a fraud verdict."
                )

                if st.button(
                    "Analyze alert with Gemini",
                    key=f"gemini_tx_{tx_id}",
                    help="Generate an evidence-grounded analyst summary.",
                ):
                    evidence_fields = [
                        "transaction_id",
                        "account_id",
                        "transaction_timestamp",
                        "amount",
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
                    ]

                    evidence = {}
                    for field in evidence_fields:
                        if field in selected.index:
                            value = selected[field]
                            if not pd.isna(value):
                                if hasattr(value, "item"):
                                    value = value.item()
                                evidence[field] = value

                    with st.spinner("Gemini is reviewing the alert evidence..."):
                        try:
                            result = investigate_alert(evidence)
                            st.session_state[f"gemini_report_{tx_id}"] = result
                            st.success("Gemini investigation completed.")
                        except GeminiInvestigationError as exc:
                            st.error(str(exc))
                        except Exception:
                            st.error(
                                "Investigation failed unexpectedly. Check "
                                "the application configuration and logs."
                            )

                report_key = f"gemini_report_{tx_id}"
                if st.session_state.get(report_key):
                    st.markdown("#### Gemini investigation findings")
                    st.markdown(st.session_state[report_key])
                    st.caption(
                        "Human review is required. No account action is taken "
                        "automatically, and the AI output is not proof of fraud."
                    )

                if st.button(
                    "Save alert investigation",
                    type="primary",
                    key=f"save_tx_{tx_id}",
                ):
                    save_case(
                        case_key,
                        "transaction",
                        account_id,
                        tx_id,
                        tx_status,
                        tx_notes,
                    )
                    st.success("Alert investigation saved to SQLite.")
                    st.rerun()


# -------------------- Model report --------------------

with report_tab:
    st.subheader("Model Evaluation")

    if REPORT_FILE.exists():
        try:
            report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
            st.json(report)
        except Exception as exc:
            st.error(f"Could not load model report: {exc}")
    else:
        st.info("No model evaluation report found.")


st.divider()
st.caption(
    "TraceForge AI prototype · Scores and alerts prioritize investigation; "
    "they do not establish criminal activity. This dashboard does not "
    "freeze accounts or perform financial actions."
)

