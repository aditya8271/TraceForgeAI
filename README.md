# 🔎 TraceForge AI

### From Suspicious Signal to Evidence-Backed, Human-Reviewed Investigation

**AI-assisted financial crime investigation and fraud triage for BFSI analysts.**

> **Existing systems raise an alert.
> TraceForge AI shows where the money went and what evidence supports the lead.
> The analyst stays in control, and every decision leaves an audit trail.**

[![Live Product](https://img.shields.io/badge/Live%20Product-TraceForge%20AI-2563eb?style=for-the-badge)](https://tracforge-ai.web.app/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge)](https://traceforgeai-1.onrender.com)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-4285F4?style=for-the-badge)](https://ai.google.dev/)
[![Firebase](https://img.shields.io/badge/Frontend%20Hosting-Firebase-FFCA28?style=for-the-badge)](https://firebase.google.com/products/hosting)

**AI Builder Cup 2026 · Team HackVerse · Team Lead: Aditya Pandey · Domain: BFSI, Financial Crime and Fraud Investigation**

[Live Demo](https://tracforge-ai.web.app/) · [Demo Video](https://drive.google.com/file/d/1CAuvPv0dt5Rv139JRUTfEYgidEalS2dY/view) · [GitHub Repository](https://github.com/aditya8271/TraceForgeAI)

---

## 🚨 Overview

**TraceForge AI** is a prototype that bridges the gap between **a flagged transaction and a defensible investigation**.

It combines historical transaction replay, rule-based alert generation, graph-based money-trail exploration, Gemini-powered investigation reports, evidence bundles with claim-to-source linking, deterministic reviewer checks, and analyst case management with an audit history in one workflow.

Instead of stopping at:

```text
This transaction looks unusual.
```

the system aims to answer:

```text
What looks unusual, and why?
        ↓
Which accounts and counterparties are connected?
        ↓
Where could the money have moved?
        ↓
What does the evidence actually say?
        ↓
Do the AI's claims match the source records?
        ↓
What did the analyst decide, and why?
        ↓
Who changed the case, and when?
```

> **Suspicious activity is a lead, not a verdict.** TraceForge AI supports investigation and triage. A human analyst remains responsible for every consequential decision.

---

# 🎯 Problem

Fraud and financial-crime teams usually have no shortage of alerts. The hard part is turning an alert into a clear, evidence-linked investigation:

**alert → context → money trail → evidence → review → decision → audit**

Knowing that a transaction was flagged does not answer:

* Why was it flagged, and how far from normal behaviour is it?
* Which accounts and counterparties are connected to it?
* Where could the money have moved across several hops?
* Which statements in an AI-written summary are backed by source data?
* Has anyone checked that the summary matches the records?
* Who decided what, and can that decision be traced later?
* Is the output being mistaken for proof of fraud?

TraceForge AI is designed around this gap.

---

# 💡 Solution

The platform is organised as two complementary layers.

## 🧠 Signal & Trail Intelligence

Turns raw transactions into leads and connected context.

```text
Transaction Data
  ↓
Historical Replay
  ↓
Behavioural Baseline per Account
  ↓
Rule-Based Alerts
  ↓
Graph of Accounts and Transfers
  ↓
Multi-Hop Money Trails
```

It answers:

> **"What looks unusual, and what is it connected to?"**

## 🛰️ Investigation & Accountability

Turns a lead into a reviewed, auditable case.

```text
Alert
  ↓
Evidence Bundle
  ↓
Gemini Investigation Report
  ↓
Claim-to-Evidence Linking
  ↓
Deterministic Reviewer Checks
  ↓
Analyst Decision
  ↓
Case Status + Audit History
```

It answers:

> **"What does the evidence support, who reviewed it, and what was decided?"**

---

# 🔄 End-to-End Workflow

```text
┌────────────────────┐
│ Transaction Dataset│
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Historical Replay  │
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Alert Generation   │
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Money-Trail        │
│ Graph Analysis     │
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Evidence Bundle    │
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Gemini             │
│ Investigation      │
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Claim Linking +    │
│ Reviewer Checks    │
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Analyst Review     │
└─────────┬──────────┘
          ↓
┌─────────────────────────┐
│ Approve / Reject /      │
│ Escalate  +  Audit Log  │
└─────────────────────────┘
```

---

# 🖼️ Screenshots

| Overview | Portfolio Analytics (historical replay) |
|---|---|
| ![Overview](docs/screenshots/overview.png) | ![Portfolio Analytics](docs/screenshots/portfolio-analytics.png) |

| Money-trail graph (synthetic demo data) | Case management with human review |
|---|---|
| ![Money trail](docs/screenshots/money-trail-synthetic.png) | ![Case management](docs/screenshots/case-management.png) |

> The money-trail view uses a **controlled synthetic dataset**. It is kept separate from the historical replay alerts and does not represent real accounts or financial activity.

---

# 📊 Current Prototype

| Component | Current Prototype |
|---|---:|
| Transactions processed (historical replay) | **5,000** |
| Accounts observed | **1,895** |
| Alerts generated | **378** |
| Alert source | Historical replay, not a live bank feed |
| Alert method | Rule-based (see below) |
| AI investigation | Gemini (`gemini-2.5-flash` by default) |
| Money-trail demo | Controlled synthetic dataset |
| Case storage | SQLite locally, PostgreSQL for deployment |
| Frontend | Next.js static export on Firebase Hosting |
| Backend | FastAPI on Render |

> **Note:** The 5,000 / 1,895 / 378 figures describe prototype replay activity. They are **not** confirmed fraud cases, prevented losses, or verified criminal accounts. Precision, recall and false-positive rate on real data are not claimed.

### How replay alerts are produced

The replay compares each transaction with the account's own recent history. The current thresholds in `app/replay_transactions.py` are:

| Parameter | Value |
|---|---:|
| History window per account | 20 transactions |
| Minimum history before comparing | 5 transactions |
| Amount-spike multiplier (vs. past median) | 5.0× |
| Absolute amount threshold | 100,000 |

Alerts therefore carry readable reasons such as an amount spike or a large absolute amount, which is what the dashboard's "Recorded alert reasons" chart counts. Amounts have no verified currency unit.

---

# 🧠 Core Intelligence Modules

TraceForge AI is a modular pipeline inside `app/`.

## 1. Replay Engine (`replay_transactions.py`)

Replays historical transactions through DuckDB, maintains a per-account rolling baseline, and writes alert rows and a replay summary.

## 2. Feature Engine (`feature_engine.py`)

Builds account-level features from transaction data for analysis and baseline experiments.

## 3. Graph Engine (`graph_engine.py`)

Builds a directed NetworkX graph from accounts and transactions and finds **evidence-backed multi-hop money trails** from a source account, bounded by hop count and minimum amount.

## 4. Fraud-Ring Benchmark (`fraud_ring.py`)

Evaluates ring detection against the **synthetic** ground truth produced by `generate_data.py`, with transparent account-level metrics. These numbers must never be presented as real-world performance.

## 5. Evidence Builder (`evidence.py`)

Derives an **evidence bundle** from the selected alert: transaction ID, account, timestamp, amount, type, channel, MCC code, counterparty, baseline size, past median, amount multiple and more. It does not decide whether fraud occurred.

## 6. Investigator (`services/gemini_investigator.py`)

Sends the evidence to Gemini and returns a structured investigation report. Calls are rate-limited and time-bounded, and failures surface as safe, readable errors.

## 7. Claim Linker and Claim Reviewer (`claim_linker.py`, `claim_reviewer.py`)

Link each claim in the report to source evidence IDs, then check those links. Anything that does not pass is flagged instead of being silently trusted.

## 8. Reviewer (`reviewer.py`)

Runs **deterministic** checks that values stated in the report match the evidence bundle, including equivalent numeric formatting.

## 9. Persistence (`persistence.py`)

A storage adapter with SQLite for local development and PostgreSQL for deployment. It refuses to run on ephemeral SQLite when it detects Cloud Run without a database.

---

# 🤖 Gemini-Powered AI

Gemini is part of the investigation workflow, not a standalone chatbot.

```text
Evidence Bundle (from the alert)
        ↓
Gemini Investigation Report
        ↓
Claims Linked to Evidence IDs
        ↓
Deterministic + Evidence-Aware Review
        ↓
Analyst Decision
```

Safeguards around the model:

* The prompt is built from the evidence bundle, so the report is grounded in the alert record.
* Claims are linked back to evidence IDs and reviewed.
* Every response carries explicit limitations: historical data, not proof of fraud, counterparty IDs do not prove ownership, decisions are human-entered.
* Gemini requests are capped per minute across investigation calls, and the API request body size is bounded.

AI output can still be incomplete or wrong. It is a drafting and triage aid, and analysts must verify it against source records.

---

# 🧩 Agent-Oriented Design

The workflow maps to four logical roles:

### 1. Detection Role
Replay engine and rules that surface alerts.

### 2. Trail Analysis Role
Graph engine that explores connected accounts and multi-hop paths.

### 3. Investigation Role
Gemini-backed investigator that drafts a structured, evidence-grounded report.

### 4. Reviewer Role
Claim linker, claim reviewer and deterministic reviewer that check the report before an analyst sees it.

### Important implementation note

These are **logical roles inside one FastAPI service**. The current prototype uses Gemini for the investigation step. It does not run four independently deployed AI agents.

---

# 👷 Analyst Workflow

An analyst can:

1. Open the **Overview** and check replay status
2. Browse **Transaction Replay** alerts
3. Open an alert and review its evidence
4. Explore the **Money Trail** around the account
5. Run the **AI Investigator** on the alert
6. Inspect the report, linked claims and reviewer results
7. Create a **case** from the investigation
8. Update case status and notes
9. Record an analyst decision with a reason
10. Review the **audit history** of the case

The decision can be:

```text
APPROVE
   or
REJECT
   or
ESCALATE
```

This creates an explicit human-in-the-loop accountability layer.

---

# 🔁 Case Lifecycle

```text
NEW
  ↓
UNDER REVIEW
  ↓
ESCALATED   (optional)
  ↓
CLOSED
```

Analyst decisions are recorded separately from status:

```text
Analyst Review
    ├── Approve
    ├── Reject
    └── Escalate  →  case status moves to Escalated
```

Every create, update and decision writes an event to the case audit log. Case writes are transactional.

---

# 🖥️ Application Modules

The command console has these workspaces:

| Module | Purpose |
|---|---|
| **Overview** | Replay status, synthetic demonstration and headline metrics |
| **Investigations** | Alert inspection and investigation results |
| **Case Management** | Create, update and review cases with status and notes |
| **Investigation Quality** | Quality view across saved reviews |
| **Fraud Ring Lab** | Synthetic fraud-ring benchmark with ground truth |
| **Portfolio Analytics** | Replay metrics, alerts by date, alert reasons, review-tier mix |
| **Real-World Intelligence Lab** | Aggregate public payment statistics (NPCI UPI), clearly separated from alerts |
| **Transaction Replay** | Historical replay alerts |
| **Money Trail** | Multi-hop paths and the account graph |
| **AI Investigator** | Gemini-assisted, evidence-linked report |

---

# 🏗️ Application Architecture

```text
                    ┌───────────────────────┐
                    │   Next.js (React/TS)  │
                    │   Analyst Console     │
                    └───────────┬───────────┘
                                │
                                │ REST API (HTTPS)
                                ↓
                    ┌───────────────────────┐
                    │       FastAPI         │
                    │       Backend         │
                    └───────────┬───────────┘
                                │
      ┌──────────────┬──────────┼──────────┬───────────────┐
      ↓              ↓          ↓          ↓               ↓
┌───────────┐  ┌───────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐
│  Replay & │  │   Graph   │ │ Evidence │ │  Reviewer │ │   Cases   │
│  Alerts   │  │  Engine   │ │  Bundle  │ │   Checks  │ │ + Audit   │
│ (DuckDB)  │  │ (NetworkX)│ │          │ │           │ │           │
└─────┬─────┘  └─────┬─────┘ └────┬─────┘ └─────┬─────┘ └─────┬─────┘
      │              │            │             │             │
      ↓              ↓            ↓             ↓             ↓
┌────────────────────────────────┐        ┌───────────────────────────┐
│ Replay data · Synthetic data   │        │ SQLite (local) /          │
│ (CSV)                          │        │ PostgreSQL (deployed)     │
└────────────────────────────────┘        └───────────────────────────┘
                                │
                                ↓
                     ┌─────────────────────┐
                     │   Google Gemini     │
                     │   Investigation     │
                     └─────────────────────┘
```

---

# 🛠️ Technology Stack

## Frontend

* Next.js 16
* React 19
* TypeScript
* Tailwind CSS 4
* Static export hosted on Firebase Hosting

## Backend

* Python
* FastAPI
* Pydantic
* REST APIs

## Data & Graph Analysis

* DuckDB
* pandas / NumPy
* NetworkX
* scikit-learn (baseline experiments)

## AI

* Google Gemini API (`google-genai`)

## Storage

* SQLite for local development
* PostgreSQL (`psycopg`) for deployment, with numbered SQL migrations

## Deployment

* Firebase Hosting (frontend)
* Render (backend)
* Docker image and Cloud Run + Cloud SQL guide in `docs/CLOUD_DEPLOYMENT.md`

---

# 📁 Project Structure

```text
TraceForgeAI/
│
├── app/
│   ├── api.py                    # FastAPI application and all routes
│   ├── replay_transactions.py    # Historical replay + alert rules
│   ├── feature_engine.py         # Account-level features
│   ├── graph_engine.py           # NetworkX money-trail engine
│   ├── fraud_ring.py             # Synthetic fraud-ring benchmark
│   ├── evidence.py               # Evidence bundle builder
│   ├── claim_linker.py           # Claim → evidence ID linking
│   ├── claim_reviewer.py         # Evidence-aware claim review
│   ├── reviewer.py               # Deterministic report checks
│   ├── persistence.py            # SQLite / PostgreSQL adapter
│   ├── dashboard.py              # Optional local Streamlit dashboard
│   ├── services/
│   │   └── gemini_investigator.py
│   └── (training / evaluation scripts)
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx              # Analyst console
│   │   └── layout.tsx
│   └── package.json
│
├── migrations/
│   ├── 001_core.sql
│   └── 002_public_data_cache.sql
│
├── scripts/
│   └── migrate_sqlite_to_postgres.py
│
├── tests/
│   ├── test_api.py
│   └── test_persistence.py
│
├── docs/
│   ├── CLOUD_DEPLOYMENT.md
│   └── screenshots/
│
├── generate_data.py              # Controlled synthetic dataset
├── Dockerfile
├── firebase.json
├── requirements.txt
├── requirements-api.txt
├── .env.example
└── README.md
```

Replay and generated data files are not committed to the repository.

---

# 🔌 API Workflow

### Health

```http
GET /api/health
```

Returns `status`, `service` and `storage` (`local_sqlite` or `postgresql`). Responds `503` when storage is unavailable.

### Replay

```http
GET /api/alerts?limit=100&offset=0
GET /api/replay-summary
```

### AI Investigation

```http
POST /api/investigate
```

### Money Trails

```http
GET /api/money-trail
GET /api/synthetic/money-trails?source_account=V001&max_hops=4&min_amount=1000
```

### Fraud-Ring Benchmark and Quality

```http
GET /api/fraud-ring/evaluate?max_hops=4
GET /api/quality/portfolio
```

### Cases and Audit

```http
GET  /api/cases
POST /api/cases
GET  /api/cases/{case_key}
GET  /api/case-audit/{case_key}
```

### Analyst Review

```http
POST /api/case-review
GET  /api/case-reviews/{case_key}
```

### Public Aggregate Intelligence

```http
GET  /api/intelligence/public-data
POST /api/intelligence/refresh
POST /api/intelligence/public-data/import
```

---

# 🚀 Getting Started

## Prerequisites

* Python 3 (the Docker image uses `python:3.14-slim`)
* Node.js 20+ and npm
* Git
* A Gemini API key for AI investigations

## 1. Clone

```bash
git clone https://github.com/aditya8271/TraceForgeAI.git
cd TraceForgeAI
```

---

# ⚙️ Backend Setup

Create a virtual environment.

### Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt        # full local toolchain
# or, for the API only:
pip install -r requirements-api.txt
```

## 🔐 Configure Environment

Copy `.env.example` to `.env`:

```env
GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
GEMINI_MODEL=gemini-2.5-flash
TRACEFORGE_CORS_ORIGINS=http://localhost:3000
TRACEFORGE_NPCI_AUTO_REFRESH=true
TRACEFORGE_MAX_REQUEST_BYTES=2200000
TRACEFORGE_GEMINI_MAX_REQUESTS_PER_MINUTE=10
TRACEFORGE_GEMINI_TIMEOUT_SECONDS=30
DB_CONNECT_TIMEOUT_SECONDS=5
DATABASE_URL=
```

Leave `DATABASE_URL` blank for local SQLite. In production it must be a PostgreSQL URL.

> Never commit API keys, `.env` files, local databases or raw transaction datasets.

## 🧪 Generate the synthetic dataset

```bash
python generate_data.py
```

This writes `accounts.csv`, `transactions.csv`, `entity_observations.csv` and `ground_truth.csv` to `data/generated`, used by the money-trail demo and the fraud-ring benchmark.

## ▶️ Start the Backend

```bash
uvicorn app.api:app --reload --port 8000
```

Health check:

```text
http://localhost:8000/api/health
```

## ✅ Run the tests

```bash
pytest
```

The suite covers health, alerts, replay summary, money-trail, case creation and audit, mocked Gemini investigation and rate limits, public-data import, and storage safeguards.

---

# 💻 Frontend Setup

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

```bash
npm run dev
```

Open `http://localhost:3000`.

`NEXT_PUBLIC_*` values are baked in at build time. Never put secrets in them.

---

# 🧪 Demo Flow

### Step 1: Open the Console
Show the Overview and replay status.

### Step 2: Show Replay Metrics
Open Portfolio Analytics: 5,000 transactions, 1,895 accounts, 378 alerts.

### Step 3: Triage Alerts
Open Transaction Replay and inspect an alert and its reasons.

### Step 4: Explore the Money Trail
Show the multi-hop graph (synthetic demo data).

### Step 5: Run the AI Investigator
Generate the Gemini report for the selected alert.

### Step 6: Inspect Evidence Linking
Show linked claims and the reviewer results.

### Step 7: Create a Case
Turn the investigation into a case.

### Step 8: Update Status
Move the case through New, Under Review, Escalated or Closed.

### Step 9: Record the Decision
Choose Approve, Reject or Escalate and enter a reason.

### Step 10: Show the Audit Trail
Open the case audit history.

This demonstrates the complete loop:

**Alert → Evidence → AI Report → Reviewer Checks → Analyst Decision → Audit Trail**

---

# 📊 Current Implementation Status

## ✅ Implemented

* FastAPI backend and Next.js analyst console
* Historical transaction replay with rule-based alerts
* Alert listing and replay summary
* Evidence bundles built from alert records
* Gemini investigation reports
* Claim-to-evidence linking and claim review
* Deterministic reviewer checks
* Multi-hop money-trail graph (NetworkX)
* Synthetic dataset generator and fraud-ring benchmark
* Portfolio analytics view
* Case creation, status and notes
* Analyst decisions (Approve / Reject / Escalate)
* Case audit log and review history
* Public aggregate payment statistics view (NPCI UPI), labelled separately
* Gemini rate limiting and request-size limits
* SQLite and PostgreSQL storage adapter with migrations
* Automated API and persistence tests
* Docker image and cloud deployment guide

---

# 🛣️ Roadmap

## 🌐 Real-Time Monitoring
* streaming transaction ingestion and live alerting

## 📈 Validated Evaluation
* labelled evaluation data
* precision, recall and false-positive reporting
* threshold tuning backed by measured results

## 🕸️ Larger-Scale Graph Analytics
* bigger transaction networks and faster path queries
* ring and mule-pattern detection on real data

## 🔍 Stronger Explainability
* tighter links from every finding to source transactions

## 🌏 Multilingual Reports
* investigation summaries in more languages

## 🔐 Access Control
* authenticated analyst identities
* role-based permissions and tenant isolation
* verified actor labels in the audit log

## 🏦 Authorized Integrations
* secure connections to approved institution workflows

---

# 🔐 Human-in-the-Loop by Design

TraceForge AI does not treat AI output as an unquestionable decision.

```text
Alert
  ↓
Evidence Bundle
  ↓
AI Report
  ↓
Claim Linking + Reviewer Checks
  ↓
Analyst Review
  ↓
Recorded Decision + Audit Trail
```

This helps maintain:

* accountability
* auditability
* human oversight
* evidence-based decisions

---

# ⚠️ Prototype Limitations

This repository is a **working prototype**, not a certified fraud-prevention system.

* Alerts come from historical replay, not a live bank feed.
* Alert rules are simple statistical thresholds, not a validated fraud classifier.
* The 5,000 / 1,895 / 378 metrics describe replay activity, not confirmed fraud.
* Amounts have no verified currency unit.
* The money-trail demo and fraud-ring benchmark use **synthetic** data. Their results are not real-world performance.
* Counterparty identifiers do not prove beneficial ownership.
* **Authentication is not enabled.** Analyst names are typed in, so audit-log actor labels are not verified identities, and CORS is not access control.
* The Gemini report can be incomplete or wrong and must be checked.
* Replay data and generated files are not committed to the repository.
* Cloud deployment needs persistent PostgreSQL and an approved API access boundary.
* No fraud accuracy, prevented loss or customer impact is claimed.

> Do not use the public prototype with sensitive real-world financial data.

---

# 🏗️ Production Architecture (Future)

```text
                  DATA SOURCES
                       │
     ┌─────────────────┼──────────────────┐
     ↓                 ↓                  ↓
 Transactions       Counterparty       Public Statistics
     │                 │                  │
     └─────────────────┼──────────────────┘
                       ↓
              Streaming Ingestion
                       ↓
               Detection + Graph
                       ↓
        Gemini Investigation + Reviewer
                       ↓
          Authenticated Analyst Console
                       ↓
        Case Management + Audit Trail
```

---

# 🎯 Why This Architecture Matters

Most fraud workflows can be represented as:

```text
Detect → Alert → Review
```

TraceForge AI extends this into:

```text
Detect
  ↓
Explain Why
  ↓
Trace the Money
  ↓
Build Evidence
  ↓
Draft with AI
  ↓
Check the Draft
  ↓
Human Review
  ↓
Decide
  ↓
Audit
```

The key idea is not simply **flagging suspicious transactions**.

It is creating a feedback loop between:

**alert → evidence → AI explanation → verification → human decision**

---

# 🌟 Key Differentiator

TraceForge AI is not another fraud dashboard.

It connects:

```text
TRANSACTION REPLAY
        +
GRAPH MONEY TRAILS
        +
GEMINI INVESTIGATION
        +
CLAIM-TO-EVIDENCE CHECKS
        +
HUMAN DECISIONS
        +
AUDIT HISTORY
```

into one investigation loop.

> **TraceForge AI finds the trail.
> The reviewer checks the claims.
> The analyst owns the decision.**

---

# 📜 Project Status

**Status:** Working Prototype

**Domain:** BFSI, Financial Crime and Fraud Investigation

**Primary AI:** Google Gemini

**Frontend:** Firebase Hosting · **Backend:** Render

**Live Product:** https://tracforge-ai.web.app/ · **API:** https://traceforgeai-1.onrender.com

---

# 👥 Intended Users

The system is designed conceptually for:

* fraud and AML analysts
* financial-crime investigators
* transaction-monitoring teams
* risk and compliance reviewers
* case managers and supervisors

The current implementation is a prototype and has not been represented as a live bank deployment.

---

# 🤝 Contribution

Contributions are welcome. Areas include:

* validated evaluation on labelled data
* authentication and role-based access
* additional graph analytics
* better explainability and evidence linking
* multilingual reports
* streaming ingestion
* deployment hardening

Please keep changes focused, add tests where practical, document new environment variables, and never include credentials, private datasets or real customer data.

---

# 📄 License

No license has been added yet. Add a `LICENSE` file (for example MIT) before presenting the repository as open source.

---

# 👥 Team

**Project:** TraceForge AI · **Team:** HackVerse · **Team Lead:** Aditya Pandey · **Competition:** AI Builder Cup 2026

---

# 🚀 Vision

An alert is where an investigation starts, not where it ends.

The real challenge begins when an analyst needs to answer:

> **Why was this flagged?**

> **Where did the money go?**

> **What does the evidence support?**

> **Did anyone check the AI's claims?**

> **Who decided, and why?**

TraceForge AI is built around answering those questions in one continuous, auditable loop.

## 🔎 From Alert → Evidence → Trail → Review → Decision → Audit

### **TraceForge AI finds the trail. The analyst owns the decision.**

[🌐 Live Product](https://tracforge-ai.web.app/) · [🎬 Demo Video](https://drive.google.com/file/d/1CAuvPv0dt5Rv139JRUTfEYgidEalS2dY/view) · [💻 GitHub](https://github.com/aditya8271/TraceForgeAI)

