"use client";
import { useEffect, useMemo, useState } from "react";
const API = process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");
const navigation = [
  { name: "Overview", icon: "◫" },
  { name: "Investigations", icon: "⌕" },
  { name: "Case Management", icon: "▣" },
  { name: "Investigation Quality", icon: "✓" },
  { name: "Fraud Ring Lab", icon: "◎" },
  { name: "Portfolio Analytics", icon: "▥" },
  { name: "Real-World Intelligence Lab", icon: "🌐" },
  { name: "Transaction Replay", icon: "↻" },
  { name: "Money Trail", icon: "⌘" },
  { name: "AI Investigator", icon: "✳" },
];
type AlertRecord = {
  transaction_id: string;
  account_id: string;
  transaction_timestamp: string;
  amount: string;
  absolute_amount: string;
  txn_type: string;
  channel: string;
  mcc_code: string;
  counterparty_id: string;
  baseline_transactions: string;
  past_median_amount: string;
  amount_multiple: string;
  history_sufficient: string;
  reasons: string;
  evidence_summary: string;
  alert_status: string;
  is_confirmed_fraud: string;
};
type ReplaySummary = {
  mode?: string;
  source_files?: number;
  transactions_processed?: number;
  accounts_seen?: number;
  alerts_generated?: number;
  transaction_types?: Record<string, number>;
  limitations?: string[];
};
type MoneyTrailNode = {
  id: string;
  label: string;
  type: "account" | "transaction" | "counterparty" | string;
  amount?: string;
  txn_type?: string;
  timestamp?: string;
  channel?: string;
  alert_reasons?: string;
  amount_multiple?: string;
};
type MoneyTrailEdge = {
  id: string;
  source: string;
  target: string;
  relationship: string;
};
type MoneyTrailData = {
  source: string;
  total_alerts: number;
  alerts_in_graph: number;
  node_count: number;
  edge_count: number;
  nodes: MoneyTrailNode[];
  edges: MoneyTrailEdge[];
  limitations: string[];
};
type SavedCase = {
  case_key: string;
  case_type: "account" | "transaction" | string;
  account_id: string | null;
  transaction_id: string | null;
  status: "New" | "Under Review" | "Escalated" | "Closed" | string;
  notes: string;
  updated_at: string;
};
type AuditEvent = {
  id: number;
  case_key: string;
  action: string;
  field_name: string | null;
  old_value: string | null;
  new_value: string | null;
  actor: string;
  created_at: string;
};

type CaseReview = {
  id: number;
  case_key: string;
  decision: "Approve" | "Reject" | "Escalate" | string;
  reason: string;
  actor: string;
  evidence_snapshot: Record<string, unknown> | null;
  created_at: string;
};
type InvestigationResponse = {
  transaction_id: string;
  source: string;
  investigator: string;
  status: string;
  report: string | StructuredInvestigation;
  evidence_bundle?: { evidence?: unknown[]; [key: string]: unknown };
  reviewer?: { review_status?: string; flags_count?: number; [key: string]: unknown };
  claim_review?: { review_status?: string; flags_count?: number; passed_checks?: number; checks_run?: number; claims?: { claim_id: string; claim: string; claim_type: string; status: string; meaning: string }[]; [key: string]: unknown };
  claim_links?: { linked_claims?: unknown[]; [key: string]: unknown };
  disclaimer?: string;
};
type StructuredInvestigation = {
  summary?: string;
  claims?: { claim_type: string; claim: string; evidence_refs?: string[]; uncertainty?: string }[];
  observed_evidence?: { claim: string; evidence_refs?: string[] }[];
  interpretations?: { claim: string; evidence_refs?: string[]; uncertainty?: string }[];
  alternative_explanations?: string[];
  missing_information?: string[];
  uncertainty?: string;
  recommended_next_steps?: string[];
  limitations?: string[];
};
function formatCompact(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 2 }).format(number);
}

function formatNumber(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("en-IN") : "—";
}
function formatAmount(value: string | number | undefined) {
  if (value === undefined || value === null || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString("en-IN", { maximumFractionDigits: 2 })
    : String(value);
}
function formatMultiple(value: string | undefined) {
  if (!value) return "—";
  const number = Number(value);
  return Number.isFinite(number)
    ? `${number.toLocaleString("en-IN", { maximumFractionDigits: 2 })}×`
    : "—";
}
function priorityFor(alert: AlertRecord) {
  const amount = Math.abs(Number(alert.absolute_amount || alert.amount));
  const multiple = Number(alert.amount_multiple);
  if (Number.isFinite(multiple) && multiple >= 50) return "High";
  if (amount >= 100000 || (Number.isFinite(multiple) && multiple >= 10))
    return "Medium";
  return "Review";
}
function reasonLabel(reasons: string) {
  return (reasons || "UNSPECIFIED_ALERT")
    .split("|")
    .map((reason) => reason.replaceAll("_", " ").toLowerCase())
    .join(" · ");
}

function AlertVisualAnalytics({ alerts, title = "Alert analytics", loading = false }: { alerts: AlertRecord[]; title?: string; loading?: boolean }) {
  const dated = new Map<string, number>();
  const reasons = new Map<string, number>();
  const priorities = new Map<string, number>();
  alerts.forEach((alert) => {
    const day = String(alert.transaction_timestamp || "").match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
    if (day && Number.isFinite(Date.parse(day))) {
      dated.set(day, (dated.get(day) || 0) + 1);
    }
    (alert.reasons || "UNSPECIFIED_ALERT").split("|").filter(Boolean).forEach((reason) => reasons.set(reason, (reasons.get(reason) || 0) + 1));
    const priority = priorityFor(alert);
    priorities.set(priority, (priorities.get(priority) || 0) + 1);
  });
  const orderedDates = [...dated.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-10).map(([label, value]) => ({ label: label.slice(5), value }));
  const reasonBars = [...reasons.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7).map(([label, value]) => ({ label: label.toLowerCase().replaceAll("_", " "), value }));
  return <section className="analytics-block" aria-label={title}>
    <div className="chart-grid">
      <BarPanel title="Alert records by date" unit="alerts per day" source={`Historical replay alert records · ${alerts.length} loaded rows`} data={orderedDates} empty="No valid timestamps are present in the loaded alert page." loading={loading} />
      <BarPanel title="Recorded alert reasons" unit="reason occurrences" source={`Reason field from ${alerts.length} loaded alert records; multi-reason alerts count once per reason`} data={reasonBars} empty="No alert reasons are present in the loaded alert page." loading={loading} />
      <DonutPanel title="Review tier mix" source={`Derived from loaded replay alerts (${alerts.length} rows); tiers use the existing local amount/multiple thresholds`} values={[...priorities.entries()].map(([label, value]) => ({ label, value }))} loading={loading} />
    </div>
  </section>;
}

function BarPanel({ title, unit, source, data, empty, loading = false }: { title: string; unit: string; source: string; data: { label: string; value: number }[]; empty: string; loading?: boolean }) {
  const max = Math.max(1, ...data.map((item) => item.value));
  return <div className="panel-card chart-panel">
    <div className="card-heading"><div><h3>{title}</h3><p>{unit}</p></div></div>
    {loading ? <div className="chart-skeleton" role="status" aria-label={`Loading ${title}`}><i /><i /><i /><i /></div> : !data.length ? <div className="chart-empty" role="status">{empty}</div> : <div className="bar-chart" role="img" aria-label={`${title}; ${data.map((item) => `${item.label}: ${item.value}`).join(", ")}`}>
      {data.map((item) => <div className="bar-row" key={item.label} title={`${item.label}: ${formatNumber(item.value)} ${unit}`}><span className="bar-label">{item.label}</span><span className="bar-track"><span className="bar-fill" style={{ width: `${Math.max(2, item.value / max * 100)}%` }} /></span><strong>{formatNumber(item.value)}</strong></div>)}
    </div>}
    <p className="chart-source">Source: {source}</p>
  </div>;
}

function DonutPanel({ title, source, values, loading = false }: { title: string; source: string; values: { label: string; value: number }[]; loading?: boolean }) {
  const palette = ["#69e2d7", "#78aefb", "#efbc72", "#b49af5", "#ee8299"];
  const total = values.reduce((sum, item) => sum + item.value, 0);
  let offset = 0;
  const gradient = values.map((item, index) => {
    const start = offset;
    offset += total ? item.value / total * 100 : 0;
    return `${palette[index % palette.length]} ${start}% ${offset}%`;
  }).join(", ");
  return <div className="panel-card chart-panel">
    <div className="card-heading"><div><h3>{title}</h3><p>Share of loaded alerts</p></div></div>
    {loading ? <div className="chart-skeleton donut-skeleton" role="status" aria-label={`Loading ${title}`}><i /></div> : !total ? <div className="chart-empty" role="status">No outcome data is available for this breakdown.</div> : <div className="donut-layout">
      <div className="donut-chart" role="img" aria-label={`${title}; ${values.map((item) => `${item.label} ${item.value}`).join(", ")}`} style={{ background: `conic-gradient(${gradient})` }}><span>{formatNumber(total)}<small>alerts</small></span></div>
      <ul className="chart-legend">{values.map((item, index) => <li key={item.label}><i style={{ background: palette[index % palette.length] }} />{item.label}<strong>{formatNumber(item.value)}</strong></li>)}</ul>
    </div>}
    <p className="chart-source">Source: {source}</p>
  </div>;
}

function StatusBars({ title, description, values, unit = "records" }: { title: string; description: string; values: Record<string, number>; unit?: string }) {
  return <BarPanel title={title} unit={unit} source={description} data={Object.entries(values).map(([label, value]) => ({ label, value: Number(value) })).filter((item) => Number.isFinite(item.value))} empty="No records are available for this breakdown." />;
}

function TimelineItem({ title, detail, state }: { title: string; detail: string; state: string }) {
  return <div className="timeline-item"><span className="timeline-node" /><div><div className="timeline-title"><strong>{title}</strong><span className="tag tag-gray">{state}</span></div><p>{detail}</p></div></div>;
}

function SyntheticTrailGraph({ trails }: { trails: any[] }) {
  const transactions = trails.slice(0, 8).flatMap((trail) => Array.isArray(trail.transactions) ? trail.transactions : []);
  const accountIds = [...new Set(transactions.flatMap((tx) => [String(tx.from_account), String(tx.to_account)]))];
  if (!transactions.length || !accountIds.length) return <div className="chart-empty">No synthetic transaction paths were returned for graphing.</div>;
  const positions = new Map(accountIds.map((id, index) => [id, { x: 110 + (index % 5) * 185, y: 55 + Math.floor(index / 5) * 105 }]));
  return <div className="panel-card synthetic-network">
    <div className="card-heading"><div><h3>Synthetic transaction network</h3><p>Account nodes and directed transaction records from the first eight returned paths</p></div><span className="tag tag-amber">SYNTHETIC</span></div>
    <div className="table-wrap network-scroll"><svg viewBox={`0 0 980 ${Math.max(170, Math.ceil(accountIds.length / 5) * 105 + 35)}`} role="img" aria-label="Synthetic ground truth transaction network. Edges are generated synthetic records." className="synthetic-network-svg">
      <defs><marker id="synthetic-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#70d5d0" /></marker></defs>
      {transactions.map((tx, index) => {
        const from = positions.get(String(tx.from_account)); const to = positions.get(String(tx.to_account));
        if (!from || !to) return null;
        return <g key={`${tx.transaction_id}-${index}`}><line x1={from.x + 54} y1={from.y} x2={to.x - 54} y2={to.y} stroke="#70d5d0" strokeOpacity=".6" strokeWidth="1.5" markerEnd="url(#synthetic-arrow)" /><title>{`${tx.transaction_id}: ${tx.from_account} → ${tx.to_account}; amount ${tx.amount} (synthetic source units)`}</title><text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 5} textAnchor="middle" fill="#a9c1d5" fontSize="9">{tx.transaction_id}</text></g>;
      })}
      {accountIds.map((id) => { const point = positions.get(id)!; return <g key={id}><rect x={point.x - 52} y={point.y - 18} width="104" height="36" rx="9" fill="#163348" stroke="#62c9d0" /><text x={point.x} y={point.y + 4} textAnchor="middle" fill="#eaf7ff" fontSize="11">{id}</text></g>; })}
    </svg></div>
    <div className="chart-legend-inline"><span><i className="legend-account" /> Synthetic account</span><span><i className="legend-edge" /> Directed synthetic transaction</span></div>
    <p className="chart-source">Source: synthetic money-trails API. Layout positions are for readability; displayed edges correspond to returned transaction records. This does not represent real accounts or financial activity.</p>
  </div>;
}
async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  if (!API) {
    throw new Error("NEXT_PUBLIC_API_URL must be set to the deployed TraceForge API URL before building the production frontend.");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45_000);
  try {
    return await fetch(input, { ...init, signal: init.signal || controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

export default function Home() {
  const [active, setActive] = useState("Overview");
  const [query, setQuery] = useState("");
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [summary, setSummary] = useState<ReplaySummary | null>(null);
  const [totalAlerts, setTotalAlerts] = useState(0);
  const [selected, setSelected] = useState<AlertRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [investigationReport, setInvestigationReport] =
    useState<InvestigationResponse | null>(null);
  const [investigationLoading, setInvestigationLoading] = useState(false);
  const [investigationError, setInvestigationError] = useState("");
  const [moneyTrail, setMoneyTrail] = useState<MoneyTrailData | null>(null);
  const [moneyTrailLoading, setMoneyTrailLoading] = useState(false);
  const [moneyTrailError, setMoneyTrailError] = useState("");
  const [selectedTrailNode, setSelectedTrailNode] = useState<MoneyTrailNode | null>(null);
  const [savedCases, setSavedCases] = useState<SavedCase[]>([]);
  const [caseLoading, setCaseLoading] = useState(false);
  const [caseError, setCaseError] = useState("");
  const [caseMessage, setCaseMessage] = useState("");
  const [caseSearch, setCaseSearch] = useState("");
  const [caseStatusFilter, setCaseStatusFilter] = useState("All");
  const [editingCase, setEditingCase] = useState<SavedCase | null>(null);
  const [caseSaving, setCaseSaving] = useState(false);
  const [caseAudit, setCaseAudit] = useState<AuditEvent[]>([]);
  const [caseAuditLoading, setCaseAuditLoading] = useState(false);
  const [caseAuditError, setCaseAuditError] = useState("");
  const [reviewDecision, setReviewDecision] = useState("Escalate");
  const [reviewReason, setReviewReason] = useState("");
  const [reviewActor, setReviewActor] = useState("Analyst");
  const [reviewSaving, setReviewSaving] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [reviewMessage, setReviewMessage] = useState("");
  const [caseReviews, setCaseReviews] = useState<CaseReview[]>([]);
  const [caseReviewsLoading, setCaseReviewsLoading] = useState(false);
  const [selectedSnapshotReviewId, setSelectedSnapshotReviewId] = useState<number | null>(null);
  const [fraudRingResult, setFraudRingResult] = useState<any>(null);
  const [fraudRingLoading, setFraudRingLoading] = useState(false);
  const [fraudRingError, setFraudRingError] = useState("");
  const [syntheticTrails, setSyntheticTrails] = useState<any>(null);
  const [syntheticTrailLoading, setSyntheticTrailLoading] = useState(false);
  const [syntheticTrailError, setSyntheticTrailError] = useState("");
  const [portfolioQuality, setPortfolioQuality] = useState<any>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [portfolioError, setPortfolioError] = useState("");
  const [publicData, setPublicData] = useState<any>(null);
  const [publicDataLoading, setPublicDataLoading] = useState(false);
  const [publicDataError, setPublicDataError] = useState("");
  const [publicDataMessage, setPublicDataMessage] = useState("");
  const [publicSourceName, setPublicSourceName] = useState("NPCI UPI monthly statistics");
  const [publicSourceUrl, setPublicSourceUrl] = useState("https://www.npci.org.in/product/upi/product-statistics");
  const [publicTransactionsUnit, setPublicTransactionsUnit] = useState("million transactions");
  const [publicValueUnit, setPublicValueUnit] = useState("crore INR");
  const [publicCsv, setPublicCsv] = useState("month,transactions,value\n");


  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [alertsResponse, summaryResponse] = await Promise.all([
        apiFetch(`${API}/api/alerts?limit=100&offset=0`, { cache: "no-store" }),
        apiFetch(`${API}/api/replay-summary`, { cache: "no-store" }),
      ]);
      if (!alertsResponse.ok) {
        throw new Error(`Alerts API returned HTTP ${alertsResponse.status}`);
      }
      if (!summaryResponse.ok) {
        throw new Error(`Summary API returned HTTP ${summaryResponse.status}`);
      }
      const alertsData = await alertsResponse.json();
      const summaryData = await summaryResponse.json();
      const loadedAlerts: AlertRecord[] = alertsData.alerts || [];
      setAlerts(loadedAlerts);
      setTotalAlerts(Number(alertsData.total || 0));
      setSummary(summaryData.summary || {});
      setSelected((previous) => {
        if (previous) {
          return (
            loadedAlerts.find(
              (item) => item.transaction_id === previous.transaction_id
            ) ||
            loadedAlerts[0] ||
            null
          );
        }
        return loadedAlerts[0] || null;
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message}. Confirm the FastAPI server is running on port 8000.`
          : "Could not load backend data."
      );
    } finally {
      setLoading(false);
    }
  }
  async function loadCases() {
    setCaseLoading(true);
    setCaseError("");
    try {
      const response = await apiFetch(`${API}/api/cases?limit=500&offset=0`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Cases API returned HTTP ${response.status}`);
      const rows: SavedCase[] = data.cases || [];
      setSavedCases(rows);
      setEditingCase((previous) => previous ? rows.find((item) => item.case_key === previous.case_key) || previous : null);
    } catch (err) {
      setCaseError(err instanceof Error ? err.message : "Could not load saved cases.");
    } finally {
      setCaseLoading(false);
    }
  }
  async function loadCaseAudit(caseKey: string) {
    setCaseAuditLoading(true);
    setCaseAuditError("");
    try {
      const response = await apiFetch(`${API}/api/case-audit/${encodeURIComponent(caseKey)}?limit=100`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Audit API returned HTTP ${response.status}`);
      setCaseAudit(data.events || []);
    } catch (err) {
      setCaseAuditError(err instanceof Error ? err.message : "Could not load case activity.");
      setCaseAudit([]);
    } finally {
      setCaseAuditLoading(false);
    }
  }
  async function saveCaseChanges() {
    if (!editingCase || caseSaving) return;
    setCaseSaving(true);
    setCaseError("");
    setCaseMessage("");
    try {
      const response = await apiFetch(`${API}/api/cases`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(editingCase),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Save failed with HTTP ${response.status}`);
      setEditingCase(data.case as SavedCase);
      setCaseMessage("Case saved successfully.");
      await loadCases();
      await loadCaseAudit(data.case.case_key);
    } catch (err) {
      setCaseError(err instanceof Error ? err.message : "Could not save case.");
    } finally {
      setCaseSaving(false);
    }
  }
  async function loadCaseReviews(caseKey: string) {
    setCaseReviewsLoading(true);
    setReviewError("");
    try {
      const response = await apiFetch(`${API}/api/case-reviews/${encodeURIComponent(caseKey)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Review history API returned HTTP ${response.status}`);
      setCaseReviews(data.reviews || data.case_reviews || []);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "Could not load review history.");
      setCaseReviews([]);
    } finally {
      setCaseReviewsLoading(false);
    }
  }

  async function submitCaseReview() {
    if (!editingCase || reviewSaving) return;
    if (!editingCase.transaction_id) {
      setReviewError("This case has no transaction ID. The current review workflow requires a transaction-linked case.");
      return;
    }
    if (reviewReason.trim().length < 10) {
      setReviewError("Enter a review reason of at least 10 characters.");
      return;
    }
    setReviewSaving(true);
    setReviewError("");
    setReviewMessage("");
    try {
      const response = await apiFetch(`${API}/api/case-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          case_key: editingCase.case_key,
          decision: reviewDecision,
          reason: reviewReason.trim(),
          actor: "Local analyst session",
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Review submission failed with HTTP ${response.status}`);
      setReviewMessage(`Decision recorded: ${data.decision || reviewDecision}. Review ID: ${data.review_id ?? "—"}.`);
      setReviewReason("");
      await Promise.all([loadCaseReviews(editingCase.case_key), loadCases(), loadCaseAudit(editingCase.case_key)]);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "Could not record the analyst decision.");
    } finally {
      setReviewSaving(false);
    }
  }

  async function loadMoneyTrail() {
    setMoneyTrailLoading(true);
    setMoneyTrailError("");
    try {
      const response = await apiFetch(`${API}/api/money-trail?limit=12`, {
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : `Money Trail API returned HTTP ${response.status}`
        );
      }
      setMoneyTrail(data as MoneyTrailData);
      setSelectedTrailNode((previous) => {
        if (!previous) return null;
        return data.nodes?.find((node: MoneyTrailNode) => node.id === previous.id) || null;
      });
    } catch (err) {
      setMoneyTrailError(
        err instanceof Error
          ? err.message
          : "Could not load Money Trail data."
      );
    } finally {
      setMoneyTrailLoading(false);
    }
  }

  async function loadFraudRingBenchmark() {
    setFraudRingLoading(true); setFraudRingError("");
    try {
      const response = await apiFetch(`${API}/api/fraud-ring/evaluate?max_hops=4`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Benchmark API returned HTTP ${response.status}`);
      setFraudRingResult(data);
    } catch (err) { setFraudRingError(err instanceof Error ? err.message : "Could not load synthetic benchmark."); }
    finally { setFraudRingLoading(false); }
  }
  async function loadSyntheticTrails() {
    setSyntheticTrailLoading(true); setSyntheticTrailError("");
    try {
      const response = await apiFetch(`${API}/api/synthetic/money-trails?source_account=V001&max_hops=4&min_amount=1000`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Synthetic trail API returned HTTP ${response.status}`);
      setSyntheticTrails(data);
    } catch (err) { setSyntheticTrailError(err instanceof Error ? err.message : "Could not load synthetic money trails."); }
    finally { setSyntheticTrailLoading(false); }
  }
  async function loadPortfolioQuality() {
    setPortfolioLoading(true); setPortfolioError("");
    try {
      const response = await apiFetch(`${API}/api/quality/portfolio`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Portfolio API returned HTTP ${response.status}`);
      setPortfolioQuality(data);
    } catch (err) { setPortfolioError(err instanceof Error ? err.message : "Could not load portfolio metrics."); }
    finally { setPortfolioLoading(false); }
  }


  async function refreshPublicDataNow() {
    setPublicDataLoading(true);
    setPublicDataError("");
    setPublicDataMessage("");
    try {
      const response = await apiFetch(`${API}/api/intelligence/refresh`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Source refresh returned HTTP ${response.status}`);
      setPublicDataMessage(`Live fetch succeeded: ${data.row_count} NPCI rows (${data.period_start} to ${data.period_end}).`);
      await loadPublicData(true);
    } catch (err) {
      await loadPublicData();
      setPublicDataError(err instanceof Error ? err.message : "Could not fetch NPCI public data.");
    } finally {
      setPublicDataLoading(false);
    }
  }

  async function loadPublicData(liveFetch = false) {
    setPublicDataLoading(true);
    setPublicDataError("");
    try {
      const response = await apiFetch(`${API}/api/intelligence/public-data`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Public data API returned HTTP ${response.status}`);
      setPublicData({ ...data, data_status: liveFetch ? "LIVE" : data.data_status });
    } catch (err) {
      setPublicDataError(err instanceof Error ? err.message : "Could not load public-data insights.");
    } finally {
      setPublicDataLoading(false);
    }
  }

  async function importPublicData() {
    setPublicDataLoading(true);
    setPublicDataError("");
    setPublicDataMessage("");
    try {
      const response = await apiFetch(`${API}/api/intelligence/public-data/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          source_name: publicSourceName,
          source_url: publicSourceUrl,
          csv_text: publicCsv,
          transactions_unit: publicTransactionsUnit,
          value_unit: publicValueUnit,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Import failed with HTTP ${response.status}`);
      setPublicDataMessage(`Imported ${data.row_count} monthly rows (${data.period_start} to ${data.period_end}).`);
      await loadPublicData();
    } catch (err) {
      setPublicDataError(err instanceof Error ? err.message : "Could not import public data.");
    } finally {
      setPublicDataLoading(false);
    }
  }

  useEffect(() => {
    void loadData(); void loadMoneyTrail(); void loadCases();
    void loadFraudRingBenchmark(); void loadSyntheticTrails(); void loadPortfolioQuality();
  }, []);

  useEffect(() => {
    if (active === "Real-World Intelligence Lab") void loadPublicData();
  }, [active]);
  const filteredAlerts = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return alerts;
    return alerts.filter((item) =>
      [
        item.transaction_id,
        item.account_id,
        item.counterparty_id,
        item.reasons,
        item.alert_status,
        item.channel,
      ]
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  }, [alerts, query]);


  function openAlert(alert: AlertRecord) {
    setSelected(alert);
    setActive("AI Investigator");
    setInvestigationError("");
  }
  async function runGeminiInvestigation() {
    if (!selected || investigationLoading) return;
    setInvestigationLoading(true);
    setInvestigationError("");
    setInvestigationReport(null);
    try {
      const response = await apiFetch(`${API}/api/investigate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          transaction_id: selected.transaction_id,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof data.detail === "string"
            ? data.detail
            : `Investigation failed with HTTP ${response.status}`
        );
      }
      setInvestigationReport(data as InvestigationResponse);
    } catch (err) {
      setInvestigationError(
        err instanceof Error
          ? err.message
          : "Could not complete the Gemini investigation."
      );
    } finally {
      setInvestigationLoading(false);
    }
  }
  const latestQualityReview = caseReviews.length
    ? [...caseReviews].sort((a, b) => b.id - a.id)[0]
    : null;
  const selectedCaseReviewMatches = Boolean(selected && editingCase?.transaction_id === selected.transaction_id && latestQualityReview);
  const investigationForSelected = investigationReport?.transaction_id === selected?.transaction_id ? investigationReport : null;
  const investigatorEvidenceCount = investigationForSelected?.evidence_bundle?.evidence?.length;
  const qualitySnapshot = latestQualityReview?.evidence_snapshot || null;
  const qualityEvidenceBundle = qualitySnapshot && typeof qualitySnapshot.evidence_bundle === "object" && qualitySnapshot.evidence_bundle
    ? qualitySnapshot.evidence_bundle as Record<string, unknown>
    : {};
  const qualityEvidence = Array.isArray(qualityEvidenceBundle.evidence)
    ? qualityEvidenceBundle.evidence as Record<string, unknown>[]
    : [];
  const qualityClaimLinks = qualitySnapshot && typeof qualitySnapshot.claim_links === "object" && qualitySnapshot.claim_links
    ? qualitySnapshot.claim_links as Record<string, unknown>
    : {};
  const qualityClaims = Array.isArray(qualityClaimLinks.linked_claims)
    ? qualityClaimLinks.linked_claims as Record<string, unknown>[]
    : [];
  const qualityClaimReview = qualitySnapshot && typeof qualitySnapshot.claim_review === "object" && qualitySnapshot.claim_review
    ? qualitySnapshot.claim_review as Record<string, unknown>
    : {};
  const qualityReviewer = qualitySnapshot && typeof qualitySnapshot.reviewer === "object" && qualitySnapshot.reviewer
    ? qualitySnapshot.reviewer as Record<string, unknown>
    : {};
  const availableEvidenceCount = qualityEvidence.filter((item) => item.available === true).length;
  const unavailableEvidenceCount = qualityEvidence.length - availableEvidenceCount;
  const linkedClaimCount = qualityClaims.filter((claim) => Array.isArray(claim.evidence_refs) && (claim.evidence_refs as unknown[]).length > 0).length;
  const qualityCheckCount = Number(qualityClaimReview.checks_run || 0);
  const qualityPassedCount = Number(qualityClaimReview.passed_checks || 0);
  const qualityFlagCount = Number(qualityClaimReview.flags_count || 0) + Number(qualityReviewer.flags_count || 0);
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">T</div>
          <div>
            <div className="brand-name">
              TraceForge<span> AI</span>
            </div>
            <div className="brand-subtitle">FINANCIAL INTELLIGENCE</div>
          </div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav className="navigation">
          {navigation.map((item) => (
            <button
              key={item.name}
              onClick={() => setActive(item.name)}
              className={`nav-item ${active === item.name ? "active" : ""}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.name}</span>
              {item.name === "Investigations" && (
                <span className="nav-count">{formatNumber(totalAlerts)}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="system-status">
            <span className="status-dot" />
            {error ? "API connection issue" : loading ? "Loading data" : "API connected"}
          </div>
          <div className="profile">
            <div className="avatar">TF</div>
            <div>
              <strong>Analyst workspace</strong>
              <small>Human review enabled</small>
            </div>
          </div>
        </div>
      </aside>
      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumbs">
            Workspace <span>/</span> {active}
          </div>
          <div className="topbar-right">
            <span className="environment">LOCAL WORKSPACE</span>
            <span className="user-avatar">TF</span>
          </div>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">FINANCIAL CRIME INTELLIGENCE</div>
              <h1>{active}</h1>
              <p>
                Investigate suspicious activity with traceable evidence and
                AI-assisted analysis.
              </p>
            </div>
            <button className="secondary-button" onClick={() => void loadData()}>
              ↻ Refresh data
            </button>
          </div>
          <div className="prototype-notice">
            <span className="notice-icon">i</span>
            <span>
              <strong>Historical replay mode</strong> — alerts are loaded from
              your local dataset replay. This is not a live bank feed, and an
              alert is not proof of fraud.
            </span>
          </div>
          {error && (
            <div className="prototype-notice">
              <span className="notice-icon">!</span>
              <span>
                <strong>Could not load data:</strong> {error}
              </span>
            </div>
          )}
          {loading && (
            <div className="panel-card" style={{ marginBottom: 18 }}>
              Loading historical replay data…
            </div>
          )}
          {active === "Investigation Quality" && (
            <>
              <div className="section-heading">
                <div>
                  <h2>Investigation Quality Dashboard</h2>
                  <p>Quality indicators from the most recently loaded case review snapshot.</p>
                </div>
                <button
                  className="secondary-button"
                  onClick={() => editingCase ? void loadCaseReviews(editingCase.case_key) : setCaseMessage("Open Case Management and select a case to load its review snapshot.")}
                  disabled={caseReviewsLoading}
                >
                  {caseReviewsLoading ? "Refreshing..." : "↻ Refresh selected case"}
                </button>
              </div>
              <div className="prototype-notice" style={{ marginBottom: 16 }}>
                <span className="notice-icon">i</span>
                <span>These metrics describe the latest review snapshot currently loaded in this browser. They are not portfolio-wide metrics, a fraud score, or proof that a transaction is fraudulent.</span>
              </div>
              {!latestQualityReview || !qualitySnapshot ? (
                <div className="panel-card">
                  <h3>No review snapshot loaded</h3>
                  <p className="metric-detail" style={{ marginTop: 8 }}>Go to Case Management, select a transaction-linked case, and load its Review history. Then return here to inspect its quality indicators.</p>
                  {caseError && <p className="metric-detail">{caseError}</p>}
                </div>
              ) : (
                <>
                  <div className="panel-card" style={{ marginBottom: 16 }}>
                    <div className="card-heading">
                      <div>
                        <h3>{latestQualityReview.case_key}</h3>
                        <p>Review #{latestQualityReview.id} · {latestQualityReview.created_at} · Decision: {latestQualityReview.decision}</p>
                      </div>
                      <span className="tag tag-amber">Human-entered decision</span>
                    </div>
                    <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{latestQualityReview.reason}</p>
                  </div>
                  <div className="metrics-grid">
                    <Metric label="Evidence fields available" value={`${formatNumber(availableEvidenceCount)} / ${formatNumber(qualityEvidence.length)}`} detail={`${formatNumber(unavailableEvidenceCount)} unavailable fields`} icon="▤" />
                    <Metric label="Claims with references" value={`${formatNumber(linkedClaimCount)} / ${formatNumber(qualityClaims.length)}`} detail="Selected claims only" icon="⌁" />
                    <Metric label="Claim checks passed" value={`${formatNumber(qualityPassedCount)} / ${formatNumber(qualityCheckCount)}`} detail={String(qualityClaimReview.review_status || "Status unavailable")} icon="✓" />
                    <Metric label="Reviewer flags" value={formatNumber(qualityFlagCount)} detail="Combined saved reviewer and claim-review flags" icon="!" />
                  </div>
                  <DonutPanel title="Claim reference check outcomes" source="Counts returned in the selected saved case-review snapshot; metadata integrity only, not factual correctness" values={[{ label: "Passed reference checks", value: qualityPassedCount }, { label: "Flagged reference checks", value: Math.max(0, qualityCheckCount - qualityPassedCount) }]} />
                  <div className="bottom-grid" style={{ marginTop: 18 }}>
                    <div className="panel-card">
                      <div className="card-heading"><div><h3>Evidence coverage</h3><p>Availability in this saved snapshot</p></div></div>
                      <div className="boundary-row"><span>Evidence records</span><strong>{formatNumber(qualityEvidence.length)}</strong></div>
                      <div className="boundary-row"><span>Available source values</span><strong>{formatNumber(availableEvidenceCount)}</strong></div>
                      <div className="boundary-row"><span>Unavailable source values</span><strong>{formatNumber(unavailableEvidenceCount)}</strong></div>
                      <div className="boundary-row"><span>Claims with at least one reference</span><strong>{formatNumber(linkedClaimCount)}</strong></div>
                      <div className="boundary-row"><span>Claims without references</span><strong>{formatNumber(qualityClaims.length - linkedClaimCount)}</strong></div>
                    </div>
                    <div className="panel-card">
                      <div className="card-heading"><div><h3>Validation & review</h3><p>Stored checks; not a fraud classifier</p></div></div>
                      <div className="boundary-row"><span>Evidence reviewer status</span><span className="tag tag-gray">{String(qualityReviewer.review_status || "Not available")}</span></div>
                      <div className="boundary-row"><span>Claim reviewer status</span><span className="tag tag-gray">{String(qualityClaimReview.review_status || "Not available")}</span></div>
                      <div className="boundary-row"><span>Claim checks passed</span><strong>{formatNumber(qualityPassedCount)}</strong></div>
                      <div className="boundary-row"><span>Claim checks run</span><strong>{formatNumber(qualityCheckCount)}</strong></div>
                      <div className="boundary-row"><span>Analyst decision</span><strong>{latestQualityReview.decision}</strong></div>
                    </div>
                  </div>
                  <div className="section-heading" style={{ marginTop: 22 }}>
                    <div><h2>Claim coverage</h2><p>Which selected claims have evidence references?</p></div>
                    <button className="text-button" onClick={() => { setActive("Case Management"); setSelectedSnapshotReviewId(latestQualityReview.id); }}>Open Case Management →</button>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>CLAIM</th><th>DESCRIPTION</th><th>REFERENCE COUNT</th><th>LINK STATUS</th></tr></thead>
                      <tbody>
                        {qualityClaims.map((claim) => {
                          const refs = Array.isArray(claim.evidence_refs) ? claim.evidence_refs as unknown[] : [];
                          return <tr key={String(claim.claim_id || "claim")}>
                            <td><strong>{String(claim.claim_id || "—")}</strong></td>
                            <td style={{ whiteSpace: "normal", minWidth: 220 }}>{String(claim.claim || "—")}</td>
                            <td>{formatNumber(refs.length)}</td>
                            <td><span className={refs.length ? "tag tag-green" : "tag tag-amber"}>{refs.length ? String(claim.link_status || "References linked") : "No evidence references"}</span></td>
                          </tr>;
                        })}
                        {qualityClaims.length === 0 && <tr><td colSpan={4} className="no-results">No selected claims in this snapshot.</td></tr>}
                      </tbody>
                    </table>
                  </div>
                  <div className="human-note" style={{ marginTop: 14 }}>
                    Quality interpretation: a high evidence-availability count only means fields were present in the saved record. Passing reference checks does not establish the truth of every report sentence or confirm fraud. Historical replay only; currency is unverified and counterparty IDs do not prove ownership.
                  </div>
                </>
              )}
            </>
          )}

          {active === "Fraud Ring Lab" && (
            <>
              <div className="section-heading">
                <div><h2>Fraud Ring Lab</h2><p>Explainable multi-hop tracing and controlled synthetic benchmark—not real-bank detection accuracy.</p></div>
                <button className="primary-button" onClick={() => { void loadFraudRingBenchmark(); void loadSyntheticTrails(); }}>Run benchmark</button>
              </div>
              {fraudRingError && <div className="error-banner">{fraudRingError}</div>}
              {syntheticTrailError && <div className="error-banner">{syntheticTrailError}</div>}
              {(fraudRingLoading || syntheticTrailLoading) && <div className="panel-card">Loading synthetic graph analysis…</div>}
              {fraudRingResult && (
                <>
                  <div className="metric-grid">
                    <div className="metric-card"><span>Precision</span><strong>{(Number(fraudRingResult.metrics?.precision || 0) * 100).toFixed(1)}%</strong><small>Synthetic labels only</small></div>
                    <div className="metric-card"><span>Recall</span><strong>{(Number(fraudRingResult.metrics?.recall || 0) * 100).toFixed(1)}%</strong><small>Planted ring members</small></div>
                    <div className="metric-card"><span>False-positive rate</span><strong>{(Number(fraudRingResult.metrics?.false_positive_rate || 0) * 100).toFixed(1)}%</strong><small>Legitimate decoys</small></div>
                    <div className="metric-card"><span>Paths found</span><strong>{formatNumber(fraudRingResult.detected_path_count)}</strong><small>Rule-based candidates</small></div>
                  </div>
                  <StatusBars title="Synthetic benchmark rates" unit="percent" description="Metrics returned by the synthetic fraud-ring evaluator; values converted to percent, using the labeled synthetic account set" values={{ Precision: Number(fraudRingResult.metrics?.precision || 0) * 100, Recall: Number(fraudRingResult.metrics?.recall || 0) * 100, "False-positive rate": Number(fraudRingResult.metrics?.false_positive_rate || 0) * 100 }} />
                  <div className="panel-card">
                    <div className="card-heading"><div><h3>Benchmark confusion matrix</h3><p>{fraudRingResult.accounts_evaluated} labeled synthetic accounts evaluated</p></div></div>
                    <div className="table-wrap"><table><thead><tr><th>True positive</th><th>False positive</th><th>False negative</th><th>True negative</th></tr></thead><tbody><tr><td>{fraudRingResult.confusion_matrix?.true_positive}</td><td>{fraudRingResult.confusion_matrix?.false_positive}</td><td>{fraudRingResult.confusion_matrix?.false_negative}</td><td>{fraudRingResult.confusion_matrix?.true_negative}</td></tr></tbody></table></div>
                    <p className="muted-copy">{fraudRingResult.disclaimer}</p>
                    {(fraudRingResult.limitations || []).map((item: string) => <p className="muted-copy" key={item}>• {item}</p>)}
                  </div>
                </>
              )}
              {syntheticTrails && <>
                <SyntheticTrailGraph trails={syntheticTrails.trails || []} />
                <div className="panel-card">
                <div className="card-heading"><div><h3>Multi-hop money trails from V001</h3><p>{syntheticTrails.trail_count} candidate paths · generated synthetic records</p></div></div>
                {(syntheticTrails.trails || []).slice(0, 12).map((trail: any, index: number) => <div className="list-row" key={`${trail.path?.join("-")}-${index}`}><div><strong>{(trail.path || []).join(" → ")}</strong><p className="muted-copy">{trail.hops} hops · {trail.transactions?.map((tx: any) => tx.transaction_id).join(", ")}</p></div></div>)}
                {(syntheticTrails.limitations || []).map((item: string) => <p className="muted-copy" key={item}>• {item}</p>)}
                </div>
              </>}
            </>
          )}

          {active === "Portfolio Analytics" && (
            <>
              <div className="section-heading"><div><h2>Portfolio-wide Quality Analytics</h2><p>Historical replay and saved review analytics are presented in separate sections.</p></div><button className="primary-button" onClick={() => void loadPortfolioQuality()}>Refresh metrics</button></div>
              <div className="section-heading"><div><h2>Historical replay dataset</h2><p>Backend replay summary and the currently loaded page of alert records.</p></div><span className="tag tag-gray">HISTORICAL</span></div>
              <div className="metrics-grid">
                <Metric label="Transactions processed" value={formatNumber(summary?.transactions_processed)} detail="Replay summary aggregate" icon="▤" />
                <Metric label="Accounts seen" value={formatNumber(summary?.accounts_seen)} detail="Replay summary aggregate" icon="◎" />
                <Metric label="Alerts generated" value={formatNumber(summary?.alerts_generated)} detail="Rule-based review signals" icon="⌁" />
                <Metric label="Alerts loaded" value={`${alerts.length} / ${formatNumber(totalAlerts)}`} detail="Current alert API page" icon="✳" />
              </div>
              <AlertVisualAnalytics alerts={alerts} title="Portfolio historical replay alert analytics" loading={loading} />
              <div className="section-heading"><div><h2>Saved case-review portfolio</h2><p>Backend portfolio endpoint · saved case statuses, decisions and review snapshots only.</p></div><span className="tag tag-amber">REVIEW RECORDS</span></div>
              <div className="prototype-notice" style={{ marginBottom: 16 }}><span className="notice-icon">i</span><span>Synthetic benchmark metrics stay in Fraud Ring Lab. NPCI public aggregate statistics stay in Real-World Intelligence Lab. Neither is combined with these historical replay and case-review counts.</span></div>
              {portfolioError && <div className="error-banner">{portfolioError}</div>}
              {portfolioLoading && <div className="panel-card">Loading portfolio metrics…</div>}
              {portfolioQuality && <>
                <div className="prototype-notice" style={{ marginBottom: 16 }}><span className="notice-icon">i</span><span>Portfolio charts below summarize saved historical replay case-review records only. Synthetic benchmark results and NPCI public aggregates remain in their own modules and are not combined here.</span></div>
                <div className="metric-grid">
                  <div className="metric-card"><span>Cases</span><strong>{formatNumber(portfolioQuality.case_count)}</strong><small>{formatNumber(portfolioQuality.distinct_reviewed_cases)} distinct cases reviewed</small></div>
                  <div className="metric-card"><span>Review snapshots</span><strong>{formatNumber(portfolioQuality.review_count)}</strong><small>Each saved review counts separately</small></div>
                  <div className="metric-card"><span>Evidence coverage</span><strong>{portfolioQuality.evidence?.coverage == null ? "—" : `${(portfolioQuality.evidence.coverage * 100).toFixed(1)}%`}</strong><small>{portfolioQuality.evidence?.available}/{portfolioQuality.evidence?.total} available</small></div>
                  <div className="metric-card"><span>Claim reference coverage</span><strong>{portfolioQuality.claims?.coverage == null ? "—" : `${(portfolioQuality.claims.coverage * 100).toFixed(1)}%`}</strong><small>{portfolioQuality.claims?.with_evidence_refs}/{portfolioQuality.claims?.total} claims linked</small></div>
                  <div className="metric-card"><span>Reference check pass rate</span><strong>{portfolioQuality.claim_reference_checks?.pass_rate == null ? "—" : `${(portfolioQuality.claim_reference_checks.pass_rate * 100).toFixed(1)}%`}</strong><small>{portfolioQuality.claim_reference_checks?.passed}/{portfolioQuality.claim_reference_checks?.total} checks</small></div>
                  <div className="metric-card"><span>Reported flags</span><strong>{formatNumber(Number(portfolioQuality.reported_flags?.reviewer || 0) + Number(portfolioQuality.reported_flags?.claim_reference || 0))}</strong><small>Reviewer + reference checks</small></div>
                </div>
                <div className="chart-grid" style={{ marginBottom: 16 }}>
                  <StatusBars title="Stored case status distribution" description="Backend portfolio endpoint · current saved case status counts" values={portfolioQuality.case_status_counts || {}} />
                  <StatusBars title="Saved analyst review outcomes" description="Backend portfolio endpoint · human-entered decisions in saved review snapshots" values={portfolioQuality.decision_counts || {}} />
                </div>
                <div className="panel-card">
                  <div className="card-heading"><div><h3>Case statuses</h3><p>Current stored case status counts</p></div></div>
                  {Object.entries(portfolioQuality.case_status_counts || {}).map(([status, count]) => <div className="list-row" key={status}><strong>{status}</strong><span>{formatNumber(count)}</span></div>)}
                  <div className="card-heading"><div><h3>Analyst decisions</h3><p>Human-entered decisions, not automatic bank actions</p></div></div>
                  {Object.entries(portfolioQuality.decision_counts || {}).map(([decision, count]) => <div className="list-row" key={decision}><strong>{decision}</strong><span>{formatNumber(count)}</span></div>)}
                  {(portfolioQuality.limitations || []).map((item: string) => <p className="muted-copy" key={item}>• {item}</p>)}
                </div>
              </>}
            </>
          )}

          {active === "Overview" && (
            <>
              <div className="metrics-grid">
                  <Metric
                  label="Transactions replayed"
                  value={
                    summary
                      ? formatNumber(summary.transactions_processed)
                      : "—"
                  }
                  detail="Historical transaction stream"
                  icon="▤"
                />
                <Metric
                  label="Accounts seen"
                  value={summary ? formatNumber(summary.accounts_seen) : "—"}
                  detail="Accounts in this replay"
                  icon="◎"
                />
                <Metric
                  label="Alerts generated"
                  value={
                    summary ? formatNumber(summary.alerts_generated) : "—"
                  }
                  detail="Rule-based review signals"
                  icon="⌁"
                />
                <Metric
                  label="Alert records loaded"
                  value={formatNumber(totalAlerts)}
                  detail={`Showing ${alerts.length} records from the API`}
                  icon="✳"
                />
              </div>
              <AlertVisualAnalytics alerts={alerts} title="Historical replay overview analytics" loading={loading} />
              <div className="section-heading">
                <div>
                  <h2>Investigation queue</h2>
                  <p>Actual records returned by the replay API</p>
                </div>
                <button
                  className="text-button"
                  onClick={() => setActive("Investigations")}
                >
                  View investigations →
                </button>
              </div>
              <CaseTable cases={alerts.slice(0, 8)} onSelect={openAlert} />
              <div className="bottom-grid">
                <div className="panel-card">
                  <div className="card-heading">
                    <div>
                      <h3>Investigation workflow</h3>
                      <p>Evidence-led review process</p>
                    </div>
                    <span className="small-pill">HUMAN IN LOOP</span>
                  </div>
                  <div className="workflow">
                    {[
                      "Historical replay alert",
                      "Inspect transaction evidence",
                      "Gemini investigation",
                      "Analyst validation",
                      "Record human decision",
                    ].map((step, index) => (
                      <div className="workflow-step" key={step}>
                        <span>{index + 1}</span>
                        <div>{step}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="panel-card">
                  <div className="card-heading">
                    <div>
                      <h3>Replay metadata</h3>
                      <p>Read from replay_summary.json</p>
                    </div>
                  </div>
                  <div className="boundary-row">
                    <span>Mode</span>
                    <span className="tag tag-green">
                      {summary?.mode || "Unknown"}
                    </span>
                  </div>
                  <div className="boundary-row">
                    <span>Source files</span>
                    <strong>{formatNumber(summary?.source_files)}</strong>
                  </div>
                  <div className="boundary-row">
                    <span>Incoming credits (C)</span>
                    <strong>
                      {formatNumber(summary?.transaction_types?.C)}
                    </strong>
                  </div>
                  <div className="boundary-row">
                    <span>Outgoing debits (D)</span>
                    <strong>
                      {formatNumber(summary?.transaction_types?.D)}
                    </strong>
                  </div>
                  <div className="boundary-row">
                    <span>Live bank feed</span>
                    <span className="tag tag-gray">Not connected</span>
                  </div>
                </div>
              </div>
            </>
          )}
          {active === "Investigations" && (
            <>
              <AlertVisualAnalytics alerts={filteredAlerts} title="Investigation queue analytics" loading={loading} />
              {selected && <div className="bottom-grid" style={{ marginBottom: 18 }}>
                <div className="panel-card">
                  <div className="card-heading"><div><h3>Selected alert evidence profile</h3><p>{selected.transaction_id} · Historical replay row</p></div><span className="tag tag-amber">Review signal</span></div>
                  <div className="detail-row"><span>Amount · source units (currency unverified)</span><strong>{formatAmount(selected.amount)}</strong></div>
                  <div className="detail-row"><span>Past median · source units</span><strong>{formatAmount(selected.past_median_amount)}</strong></div>
                  <div className="detail-row"><span>Baseline transactions</span><strong>{formatNumber(selected.baseline_transactions)}</strong></div>
                  <div className="detail-row"><span>Amount / past median</span><strong>{formatMultiple(selected.amount_multiple)}</strong></div>
                  <div className="detail-row"><span>History sufficient</span><strong>{String(selected.history_sufficient)}</strong></div>
                  <p className="chart-source">Source: selected alert record and its stored replay baseline fields. Missing baseline values are shown as unavailable.</p>
                </div>
                <div className="panel-card">
                  <div className="card-heading"><div><h3>Investigation activity</h3><p>Stages supported by the current browser state and saved case records</p></div></div>
                  <div className="timeline-list">
                    <TimelineItem title="Replay alert generated" detail={selected.transaction_timestamp || "Timestamp unavailable"} state="Recorded" />
                    <TimelineItem title="Alert selected for review" detail={selected.transaction_id} state="Selected" />
                    <TimelineItem title="AI investigation" detail={investigationForSelected ? "Report and returned reviewer outputs available" : investigationError || "Not run for this alert"} state={investigationForSelected ? "Complete" : investigationError ? "Error" : "Not run"} />
                    <TimelineItem title="Saved analyst review" detail="Open a linked case to load its stored decision and audit events." state="Not loaded" />
                  </div>
                  <p className="chart-source">No timestamps are inferred for stages that the API has not recorded.</p>
                </div>
              </div>}
              <div className="section-heading">
                <div>
                  <h2>Case queue</h2>
                  <p>
                    {formatNumber(totalAlerts)} alerts in replay output ·{" "}
                    {alerts.length} loaded on this page
                  </p>
                </div>
                <button
                  className="secondary-button"
                  onClick={() => void loadData()}
                >
                  ↻ Refresh
                </button>
              </div>
              <div className="search-box">
                <span>⌕</span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search transaction, account, counterparty or alert reason..."
                />
              </div>
              <CaseTable cases={filteredAlerts} onSelect={openAlert} />
              <p className="metric-detail" style={{ marginTop: 12 }}>
                The API currently loads the first 100 alerts. Search covers
                those loaded records, not all {formatNumber(totalAlerts)} alerts.
              </p>
            </>
          )}
          {active === "Case Management" && (
            <>
              <div className="section-heading">
                <div>
                  <h2>Case Management</h2>
                  <p>{savedCases.length} saved cases · Changes persist in the existing SQLite database</p>
                </div>
                <button className="secondary-button" onClick={() => void loadCases()} disabled={caseLoading}>
                  {caseLoading ? "Loading..." : "↻ Refresh cases"}
                </button>
              </div>
              <div className="prototype-notice" style={{ marginBottom: 16 }}>
                <span className="notice-icon">i</span>
                <span>Case statuses and notes are analyst workflow records. They do not independently confirm fraud.</span>
              </div>
              {savedCases.length > 0 && <div className="analytics-block" style={{ marginBottom: 16 }}><StatusBars title="Saved case status distribution" description={`Current status values from ${savedCases.length} saved case records`} values={savedCases.reduce<Record<string, number>>((counts, item) => ({ ...counts, [item.status]: (counts[item.status] || 0) + 1 }), {})} /></div>}
              {caseError && <div className="prototype-notice" style={{ marginBottom: 16 }}><span className="notice-icon">!</span><span>{caseError}</span></div>}
              {caseMessage && <div className="human-note" style={{ marginBottom: 16 }}>{caseMessage}</div>}
              <div className="search-box" style={{ marginBottom: 14 }}>
                <span>⌕</span>
                <input value={caseSearch} onChange={(event) => setCaseSearch(event.target.value)} placeholder="Search case, transaction, account or notes..." />
                <select aria-label="Filter cases by status" value={caseStatusFilter} onChange={(event) => setCaseStatusFilter(event.target.value)} style={{ maxWidth: 190 }}>
                  <option>All</option><option>New</option><option>Under Review</option><option>Escalated</option><option>Closed</option>
                </select>
              </div>
              <div className="panel-card" style={{ marginBottom: 18 }}>
                <div className="card-heading"><div><h3>Saved investigations</h3><p>Select a case to edit its status and analyst notes</p></div></div>
                <div className="table-wrap">
                  <table><thead><tr><th>CASE</th><th>TYPE</th><th>ACCOUNT</th><th>STATUS</th><th>LAST UPDATED</th><th /></tr></thead>
                    <tbody>{savedCases.filter((item) => (caseStatusFilter === "All" || item.status === caseStatusFilter) && [item.case_key, item.account_id, item.transaction_id, item.notes].join(" ").toLowerCase().includes(caseSearch.toLowerCase())).map((item) => (
                      <tr key={item.case_key}>
                        <td><button className="case-link" onClick={() => { setEditingCase({ ...item }); setCaseMessage(""); setReviewMessage(""); setReviewError(""); void loadCaseAudit(item.case_key); void loadCaseReviews(item.case_key); }}>{item.transaction_id || item.account_id || item.case_key}</button></td>
                        <td>{item.case_type}</td><td>{item.account_id || "—"}</td>
                        <td><span className={`tag ${item.status === "Escalated" ? "tag-red" : item.status === "Closed" ? "tag-green" : item.status === "Under Review" ? "tag-amber" : "tag-gray"}`}>{item.status}</span></td>
                        <td>{item.updated_at || "—"}</td>
                        <td><button className="secondary-button" onClick={() => { setEditingCase({ ...item }); setCaseMessage(""); setReviewMessage(""); setReviewError(""); void loadCaseAudit(item.case_key); void loadCaseReviews(item.case_key); }}>Edit</button></td>
                      </tr>
                    ))}
                    {!caseLoading && savedCases.filter((item) => (caseStatusFilter === "All" || item.status === caseStatusFilter) && [item.case_key, item.account_id, item.transaction_id, item.notes].join(" ").toLowerCase().includes(caseSearch.toLowerCase())).length === 0 && <tr><td colSpan={6} className="no-results">No saved cases match this filter.</td></tr>}
                  </tbody></table>
                </div>
              </div>
              {editingCase && (
                <div className="panel-card">
                  <div className="card-heading"><div><h3>Edit investigation</h3><p>{editingCase.case_key}</p></div><span className="tag tag-green">SQLite case</span></div>
                  <div className="detail-row"><span>Transaction ID</span><strong>{editingCase.transaction_id || "—"}</strong></div>
                  <div className="detail-row"><span>Account ID</span><strong>{editingCase.account_id || "—"}</strong></div>
                  <label style={{ display: "block", marginTop: 18, marginBottom: 8, fontSize: 13 }}>Case status</label>
                  <select value={editingCase.status} onChange={(event) => setEditingCase({ ...editingCase, status: event.target.value })} style={{ width: "100%", padding: 12, borderRadius: 8, marginBottom: 16 }}>
                    <option>New</option><option>Under Review</option><option>Escalated</option><option>Closed</option>
                  </select>
                  <label style={{ display: "block", marginBottom: 8, fontSize: 13 }}>Analyst notes</label>
                  <textarea value={editingCase.notes || ""} onChange={(event) => setEditingCase({ ...editingCase, notes: event.target.value })} placeholder="Record evidence reviewed, next steps, and rationale..." rows={5} style={{ width: "100%", padding: 12, borderRadius: 8, resize: "vertical", marginBottom: 16 }} />
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <button className="secondary-button" onClick={() => void saveCaseChanges()} disabled={caseSaving}>{caseSaving ? "Saving..." : "Save case changes"}</button>
                    <button className="secondary-button" onClick={() => setEditingCase(null)}>Cancel</button>
                  </div>
                  <div style={{ marginTop: 24, borderTop: "1px solid var(--border, #273244)", paddingTop: 18 }}>
                    <div className="card-heading"><div><h3>Analyst review decision</h3><p>Records a human decision with a fresh evidence snapshot</p></div><span className="tag tag-amber">Human review</span></div>
                    <div className="prototype-notice" style={{ marginBottom: 12 }}><span className="notice-icon">i</span><span>The API reruns the investigation and stores an evidence snapshot. This is not an automated fraud determination. The actor label is not authenticated in this prototype.</span></div>
                    <label style={{ display: "block", marginBottom: 8, fontSize: 13 }}>Decision</label>
                    <select value={reviewDecision} onChange={(event) => setReviewDecision(event.target.value)} style={{ width: "100%", padding: 12, borderRadius: 8, marginBottom: 14 }}>
                      <option value="Approve">Approve</option><option value="Reject">Reject</option><option value="Escalate">Escalate</option>
                    </select>
                    <label style={{ display: "block", marginBottom: 8, fontSize: 13 }}>Analyst label (not verified)</label>
                    <input value={reviewActor} onChange={(event) => setReviewActor(event.target.value)} placeholder="e.g. Analyst 1" style={{ width: "100%", padding: 12, borderRadius: 8, marginBottom: 14 }} />
                    <label style={{ display: "block", marginBottom: 8, fontSize: 13 }}>Decision rationale (minimum 10 characters)</label>
                    <textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} placeholder="Explain the evidence reviewed and why this decision was chosen..." rows={4} style={{ width: "100%", padding: 12, borderRadius: 8, resize: "vertical", marginBottom: 14 }} />
                    <button className="secondary-button" onClick={() => void submitCaseReview()} disabled={reviewSaving || !editingCase.transaction_id || reviewReason.trim().length < 10}>{reviewSaving ? "Recording decision..." : "Record analyst decision"}</button>
                    {!editingCase.transaction_id && <p className="metric-detail" style={{ marginTop: 8 }}>A transaction ID is required for this review endpoint.</p>}
                    {reviewError && <div className="prototype-notice" style={{ marginTop: 12 }}><span className="notice-icon">!</span><span>{reviewError}</span></div>}
                    {reviewMessage && <div className="human-note" style={{ marginTop: 12 }}>{reviewMessage}</div>}
                    <div style={{ marginTop: 22 }}>
                      <div className="card-heading"><div><h3>Review history</h3><p>Saved decisions and stored snapshots for this case</p></div><button className="secondary-button" onClick={() => void loadCaseReviews(editingCase.case_key)} disabled={caseReviewsLoading}>{caseReviewsLoading ? "Loading..." : "↻ Refresh reviews"}</button></div>
                      {caseReviewsLoading && <p className="metric-detail">Loading review history...</p>}
                      {!caseReviewsLoading && caseReviews.length === 0 && <p className="metric-detail">No review decisions found for this case yet.</p>}
                      <div style={{ display: "grid", gap: 10 }}>
                        {caseReviews.map((review) => <div key={review.id} style={{ border: "1px solid var(--border, #273244)", borderRadius: 10, padding: 12 }}>
                          <div style={{ display: "flex", gap: 10, justifyContent: "space-between", flexWrap: "wrap" }}><strong>{review.decision}</strong><span className="metric-detail">{review.created_at}</span></div>
                          <p style={{ margin: "8px 0", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{review.reason}</p>
                          <p className="metric-detail">Actor label: {review.actor || "Unspecified"} · Review ID: {review.id}</p>
                          <p className="metric-detail">Evidence snapshot: {review.evidence_snapshot ? "Saved" : "Not returned"}</p>
                          {review.evidence_snapshot && <button className="secondary-button" onClick={() => setSelectedSnapshotReviewId((current) => current === review.id ? null : review.id)} style={{ marginTop: 8 }}>{selectedSnapshotReviewId === review.id ? "Hide evidence snapshot" : "Inspect evidence snapshot"}</button>}
                          {selectedSnapshotReviewId === review.id && review.evidence_snapshot && <EvidenceSnapshotPanel snapshot={review.evidence_snapshot} />}
                        </div>)}
                      </div>
                    </div>
                  </div>

                  <div style={{ marginTop: 24, borderTop: "1px solid var(--border, #273244)", paddingTop: 18 }}>
                    <div className="card-heading"><div><h3>Audit trail</h3><p>Recorded case creation, status changes and notes updates</p></div><button className="secondary-button" onClick={() => void loadCaseAudit(editingCase.case_key)} disabled={caseAuditLoading}>{caseAuditLoading ? "Loading..." : "↻ Refresh activity"}</button></div>
                    <div className="prototype-notice" style={{ marginBottom: 12 }}><span className="notice-icon">i</span><span>Local activity log only. User identity is not verified because authentication is not configured. Older changes made before audit logging was added will not appear.</span></div>
                    {caseAuditError && <div className="prototype-notice"><span className="notice-icon">!</span><span>{caseAuditError}</span></div>}
                    {!caseAuditLoading && !caseAuditError && caseAudit.length === 0 && <p className="metric-detail">No recorded activity yet. Save a status or notes change to create the first event.</p>}
                    {!!caseAudit.length && <div className="timeline-list audit-timeline" aria-label="Recorded case activity timeline">{caseAudit.map((event) => <TimelineItem key={`timeline-${event.id}`} title={event.action} detail={`${event.created_at}${event.field_name ? ` · ${event.field_name}: ${event.old_value || "—"} → ${event.new_value || "—"}` : ""}`} state={event.field_name || "Case event"} />)}</div>}
                    <div style={{ display: "grid", gap: 10 }}>
                      {caseAudit.map((event) => <div key={event.id} style={{ border: "1px solid var(--border, #273244)", borderRadius: 10, padding: 12 }}>
                        <div style={{ display: "flex", gap: 10, justifyContent: "space-between", flexWrap: "wrap" }}><strong>{event.action}</strong><span className="metric-detail">{event.created_at}</span></div>
                        {event.field_name === "status" && <p style={{ margin: "8px 0 0", fontSize: 13 }}>{event.old_value || "—"} → <strong>{event.new_value || "—"}</strong></p>}
                        {event.field_name === "notes" && <p style={{ margin: "8px 0 0", fontSize: 13, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{event.old_value ? `Previous: ${event.old_value}
` : ""}Current: {event.new_value || "(empty)"}</p>}
                        <p className="metric-detail" style={{ marginTop: 8 }}>Actor label: {event.actor}</p>
                      </div>)}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
          {active === "Transaction Replay" && (
            <>
              <div className="metrics-grid">
                <Metric label="Transactions processed" value={formatNumber(summary?.transactions_processed)} detail="Backend replay summary" icon="▤" />
                <Metric label="Alerts generated" value={formatNumber(summary?.alerts_generated)} detail="Rule-based review signals" icon="⌁" />
                <Metric label="Alert rows loaded" value={`${alerts.length} / ${formatNumber(totalAlerts)}`} detail="Current paginated alert sample" icon="✳" />
                <Metric label="Replay progress" value="No progress data" detail="No incremental progress endpoint is available" icon="↻" />
              </div>
              <AlertVisualAnalytics alerts={alerts} title="Historical replay alert chronology" loading={loading} />
              <div className="panel-card" style={{ marginTop: 16 }}>
                <div className="card-heading"><div><h3>Transaction throughput</h3><p>Transactions per time interval</p></div><span className="tag tag-gray">Unavailable</span></div>
                <div className="chart-empty">The current replay API exposes aggregate transaction totals and paginated alert rows, but no transaction-level time series. The alert chronology above counts alert timestamps only and is not a transaction throughput measure.</div>
                {summary?.limitations?.map((limitation) => <div className="boundary-row" key={limitation}><span>{limitation}</span></div>)}
              </div>
            </>
          )}
          {active === "Money Trail" && (
            <div className="panel-card">
              <div className="card-heading">
                <div>
                  <h3>Money Trail Explorer</h3>
                  <p>Recorded account → transaction → counterparty associations</p>
                </div>
                <button
                  className="secondary-button"
                  onClick={() => void loadMoneyTrail()}
                  disabled={moneyTrailLoading}
                >
                  {moneyTrailLoading ? "Loading..." : "↻ Refresh graph"}
                </button>
              </div>
              <div className="prototype-notice" style={{ marginBottom: 18 }}>
                <span className="notice-icon">i</span>
                <span>
                  This graph is built from historical alert records only. It shows
                  recorded associations, not verified ownership or confirmed illicit
                  fund movement. Counterparties remain separate from accounts.
                </span>
              </div>
              {moneyTrailError && (
                <div className="prototype-notice" style={{ marginBottom: 16 }}>
                  <span className="notice-icon">!</span>
                  <span><strong>Graph error:</strong> {moneyTrailError}</span>
                </div>
              )}
              {moneyTrailLoading && !moneyTrail && (
                <div className="empty-state"><p>Loading Money Trail graph…</p></div>
              )}
              {moneyTrail && (
                <>
                  <div className="metrics-grid">
                    <Metric label="Alerts represented" value={formatNumber(moneyTrail.alerts_in_graph)} detail="Limited graph sample" icon="▤" />
                    <Metric label="Nodes" value={formatNumber(moneyTrail.node_count)} detail="Accounts, transactions, counterparties" icon="◎" />
                    <Metric label="Recorded links" value={formatNumber(moneyTrail.edge_count)} detail="Associations in alert records" icon="⌁" />
                    <Metric label="Alerts available" value={formatNumber(moneyTrail.total_alerts)} detail="Total historical replay alerts" icon="✳" />
                  </div>
                  <div className="section-heading" style={{ marginTop: 24 }}>
                    <div>
                      <h2>Relationship map</h2>
                      <p>Choose a node to inspect its available evidence</p>
                    </div>
                    <span className="tag tag-gray">Historical sample · 12 alerts</span>
                  </div>
                  <div className="chart-legend-inline graph-legend"><span><i className="legend-account" /> Account</span><span><i className="legend-transaction" /> Transaction</span><span><i className="legend-counterparty" /> Counterparty</span><span><i className="legend-edge" /> Direction follows recorded association edge</span></div>
                  <MoneyTrailGraph
                    data={moneyTrail}
                    selectedNodeId={selectedTrailNode?.id || ""}
                    onSelect={(node) => setSelectedTrailNode(node)}
                  />
                  {selectedTrailNode && (
                    <div className="panel-card" style={{ marginTop: 18 }}>
                      <div className="card-heading">
                        <div>
                          <h3>Selected node</h3>
                          <p>{selectedTrailNode.label}</p>
                        </div>
                        <span className="tag tag-green">{selectedTrailNode.type}</span>
                      </div>
                      {selectedTrailNode.type === "transaction" ? (
                        <>
                          <Detail label="Amount (source units)" value={formatAmount(selectedTrailNode.amount)} />
                          <Detail label="Transaction type" value={selectedTrailNode.txn_type || "—"} />
                          <Detail label="Timestamp" value={selectedTrailNode.timestamp || "—"} />
                          <Detail label="Channel" value={selectedTrailNode.channel || "—"} />
                          <Detail label="Amount multiple" value={formatMultiple(selectedTrailNode.amount_multiple)} />
                          <Detail label="Recorded alert reasons" value={reasonLabel(selectedTrailNode.alert_reasons || "")} />
                        </>
                      ) : (
                        <p className="metric-detail">
                          This identifier is shown as {selectedTrailNode.type === "account" ? "an account" : `a ${selectedTrailNode.type}`}. The available alert data does not establish further identity or ownership details.
                        </p>
                      )}
                    </div>
                  )}
                  <div className="human-note" style={{ marginTop: 18 }}>
                    {moneyTrail.limitations?.join(" ")}
                  </div>
                </>
              )}
            </div>
          )}

          {active === "Real-World Intelligence Lab" && (
            <>
              <div className="section-heading">
                <div>
                  <h2>Real-World Intelligence Lab</h2>
                  <p>Inspect source status, import reported monthly aggregates, and calculate clearly labeled trends.</p>
                </div>
                <button className="secondary-button" onClick={() => void refreshPublicDataNow()} disabled={publicDataLoading}>
                  {publicDataLoading ? "Fetching..." : "↻ Fetch latest NPCI data"}
                </button>
              </div>
              <div className="prototype-notice" style={{ marginBottom: 16 }}>
                <span className="notice-icon">i</span>
                <span><strong>Public aggregate data only.</strong> The app makes one automatic startup fetch. If NPCI returns HTTP 403, it records that source-specific block and does not automatically retry on later restarts. Use the button only when you want to make a new request. This is not a live bank transaction feed; the last successful data remains available as cached data.</span>
              </div>
              {publicData?.refresh_status && <div className="boundary-row" role="status" aria-live="polite" style={{ marginBottom: 16 }}>
                <span><strong>NPCI source status</strong><div className="metric-detail" style={{ marginTop: 4 }}>{publicData.refresh_status.message}</div>
                  {publicData.refresh_status.last_attempt_at && <div className="metric-detail">Last attempt: {publicData.refresh_status.last_attempt_at}</div>}
                  {publicData.refresh_status.last_success_at && <div className="metric-detail">Last successful fetch: {publicData.refresh_status.last_success_at}</div>}
                </span>
                <span className={`tag ${publicData.refresh_status.source_status === "blocked" ? "tag-red" : publicData.refresh_status.source_status === "available" ? "tag-green" : "tag-gray"}`}>{String(publicData.refresh_status.source_status).toUpperCase()}</span>
              </div>}
              <div className="panel-card" style={{ marginBottom: 18 }}>
                <div className="card-heading">
                  <div>
                    <h3>Import official monthly statistics</h3>
                    <p>Download or copy monthly aggregate figures from an official source, then paste the rows here.</p>
                  </div>
                  <span className="tag tag-gray">CSV import</span>
                </div>
                <div className="form-grid">
                  <label className="field-label">Source name
                    <input className="text-input" value={publicSourceName} onChange={(event) => setPublicSourceName(event.target.value)} placeholder="NPCI UPI monthly statistics" />
                  </label>
                  <label className="field-label">Official source URL
                    <input className="text-input" value={publicSourceUrl} onChange={(event) => setPublicSourceUrl(event.target.value)} placeholder="https://..." />
                  </label>
                </div>
                <div className="form-grid" style={{ marginTop: 12 }}>
                  <label className="field-label">Transaction volume unit
                    <input className="text-input" value={publicTransactionsUnit} onChange={(event) => setPublicTransactionsUnit(event.target.value)} maxLength={80} />
                  </label>
                  <label className="field-label">Transaction value unit
                    <input className="text-input" value={publicValueUnit} onChange={(event) => setPublicValueUnit(event.target.value)} maxLength={80} />
                  </label>
                </div>
                <label className="field-label" style={{ display: "block", marginTop: 12 }}>CSV data (headers: month,transactions,value)
                  <textarea className="text-input" style={{ width: "100%", minHeight: 150, marginTop: 6, fontFamily: "monospace" }} value={publicCsv} onChange={(event) => setPublicCsv(event.target.value)} />
                </label>
                <p className="metric-detail" style={{ marginTop: 8 }}>Manual CSV import remains available when NPCI blocks automatic access. Include only figures copied from the linked source; enter the units shown by that source. The prefilled CSV contains headers only, not sample data.</p>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
                  <button className="primary-button" onClick={() => void importPublicData()} disabled={publicDataLoading || !publicSourceName.trim() || !publicSourceUrl.trim() || !publicCsv.trim()}>
                    {publicDataLoading ? "Importing..." : "Import and calculate insights"}
                  </button>
                  <a className="text-button" href="https://www.npci.org.in/product/upi/product-statistics" target="_blank" rel="noreferrer">Open NPCI UPI statistics ↗</a>
                  <a className="text-button" href="https://www.rbi.org.in/scripts/AnnualReportPublications.aspx" target="_blank" rel="noreferrer">Open RBI annual reports ↗</a>
                </div>
                {publicDataMessage && <p className="success-copy" style={{ marginTop: 12 }}>{publicDataMessage}</p>}
                {publicDataError && <p className="error-copy" style={{ marginTop: 12 }}>{publicDataError}</p>}
              </div>
              {publicData?.status === "ready" ? (
                <>
                  <div className="boundary-row" style={{ marginBottom: 14 }}><span>Data status</span><span className={`tag ${publicData.data_status === "LIVE" ? "tag-green" : publicData.data_status === "MANUALLY_IMPORTED" ? "tag-amber" : "tag-gray"}`}>{publicData.data_status}</span></div>
                  <div className="metrics-grid">
                    <Metric label="Reporting periods" value={formatNumber(publicData.row_count)} detail={`${publicData.data_period_start || "—"} to ${publicData.data_period_end || "—"}`} icon="▤" />
                    <Metric label="Latest transaction count" value={formatNumber(publicData.rows?.[publicData.rows.length - 1]?.transactions)} detail={publicData.rows?.[publicData.rows.length - 1]?.month || "Latest period"} icon="↗" />
                    <Metric label="Latest transaction value" value={formatNumber(publicData.rows?.[publicData.rows.length - 1]?.value)} detail={publicData.value_unit || "Source-reported units"} icon="↗" />
                    <Metric label="Data imported" value={publicData.imported_at ? new Date(publicData.imported_at).toLocaleDateString("en-IN") : "—"} detail={publicData.source_name || "Public source"} icon="◷" />
                  </div>
                  <div className="bottom-grid" style={{ marginTop: 18 }}>
                    <div className="panel-card">
                      <div className="card-heading"><div><h3>Monthly transaction volume</h3><p>Source-reported values · most recent periods</p></div></div>
                      {(() => {
                        const rows = (publicData.rows || []).slice(-8);
                        const max = Math.max(1, ...rows.map((row: any) => Number(row.transactions) || 0));
                        return rows.length ? <div style={{ display: "grid", gridTemplateColumns: "repeat(8, minmax(0, 1fr))", gap: 8, alignItems: "end", minHeight: 190, paddingTop: 12 }}>
                          {rows.map((row: any, index: number) => {
                            const value = Number(row.transactions) || 0;
                            const height = Math.max(4, Math.round((value / max) * 135));
                            return <div key={`${row.month}-${index}`} title={`${row.month}: ${formatNumber(value)}`} style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "end", minWidth: 0, gap: 6 }}>
                              <span style={{ fontSize: 10, color: "var(--muted, #777)", overflowWrap: "anywhere" }}>{formatCompact(value)}</span>
                              <div style={{ width: "100%", maxWidth: 36, height, borderRadius: "5px 5px 0 0", background: "var(--accent, #4f46e5)" }} />
                              <span style={{ fontSize: 10, color: "var(--muted, #777)", textAlign: "center", overflowWrap: "anywhere" }}>{String(row.month).slice(0, 7)}</span>
                            </div>;
                          })}
                        </div> : <p className="metric-detail">No monthly rows are available to chart.</p>;
                      })()}
                    </div>
                    <div className="panel-card">
                      <div className="card-heading"><div><h3>Monthly transaction value</h3><p>Source-reported units · most recent periods</p></div></div>
                      {(() => {
                        const rows = (publicData.rows || []).slice(-8);
                        const max = Math.max(1, ...rows.map((row: any) => Number(row.value) || 0));
                        return rows.length ? <div style={{ display: "grid", gridTemplateColumns: "repeat(8, minmax(0, 1fr))", gap: 8, alignItems: "end", minHeight: 190, paddingTop: 12 }}>
                          {rows.map((row: any, index: number) => {
                            const value = Number(row.value) || 0;
                            const height = Math.max(4, Math.round((value / max) * 135));
                            return <div key={`${row.month}-${index}`} title={`${row.month}: ${formatNumber(value)}`} style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "end", minWidth: 0, gap: 6 }}>
                              <span style={{ fontSize: 10, color: "var(--muted, #777)", overflowWrap: "anywhere" }}>{formatCompact(value)}</span>
                              <div style={{ width: "100%", maxWidth: 36, height, borderRadius: "5px 5px 0 0", background: "var(--accent, #0f766e)" }} />
                              <span style={{ fontSize: 10, color: "var(--muted, #777)", textAlign: "center", overflowWrap: "anywhere" }}>{String(row.month).slice(0, 7)}</span>
                            </div>;
                          })}
                        </div> : <p className="metric-detail">No monthly rows are available to chart.</p>;
                      })()}
                    </div>
                  </div>
                  <div className="panel-card" style={{ marginTop: 18 }}>
                    <div className="card-heading"><div><h3>Calculated insights</h3><p>Computed from the imported figures, not generated statistics.</p></div></div>
                    {(publicData.insights || []).map((insight: any, index: number) => (
                      <div className="boundary-row" key={`${insight.metric}-${index}`}>
                        <span>
                          <strong>{insight.metric}{insight.latest_period ? ` · ${insight.latest_period}` : ""}</strong>
                          {insight.previous_period && <div className="metric-detail" style={{ marginTop: 3 }}>Compared {insight.previous_period} → {insight.latest_period}</div>}
                          {insight.unit_note && <div className="metric-detail" style={{ marginTop: 3 }}>{insight.unit_note}</div>}
                        </span>
                        <strong>{insight.change_percent !== undefined && insight.change_percent !== null ? `${insight.change_percent > 0 ? "+" : ""}${insight.change_percent}%` : insight.metric === "Average value per transaction" && insight.latest_value !== undefined && insight.latest_value !== null ? `₹${formatNumber(insight.latest_value)}` : insight.latest_value !== undefined && insight.latest_value !== null ? formatNumber(insight.latest_value) : "—"}</strong>
                      </div>
                    ))}
                    <div className="metric-detail" style={{ marginTop: 12 }}>Source: <a href={publicData.source_url} target="_blank" rel="noreferrer">{publicData.source_name}</a> · Imported/fetched {publicData.imported_at || "date unavailable"} · {publicData.reporting_period_start || publicData.data_period_start} to {publicData.reporting_period_end || publicData.data_period_end} · {publicData.row_count} rows · Volume: {publicData.transactions_unit} · Value: {publicData.value_unit}</div>
                    <p className="metric-detail" style={{ marginTop: 8 }}>{publicData.notice}</p>
                    <div className="table-wrap" style={{ marginTop: 14 }}>
                      <table>
                        <thead><tr><th>REPORTING PERIOD</th><th>TRANSACTIONS ({publicData.transactions_unit})</th><th>TRANSACTION VALUE ({publicData.value_unit})</th></tr></thead>
                        <tbody>
                          {(publicData.rows || []).map((row: any, index: number) => (
                            <tr key={`${row.month}-${index}`}><td>{row.month}</td><td>{formatNumber(row.transactions)}</td><td>{formatNumber(row.value)}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : (
                <div className="panel-card">
                  <h3>{publicDataLoading ? "Fetching public data…" : "No cached NPCI dataset is available"}</h3>
                  <p className="metric-detail" style={{ marginTop: 8 }}>Automated NPCI access is currently blocked. Import monthly figures copied from the official source using the CSV form above; charts appear after the backend validates and stores those figures.</p>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
                    <a className="text-button" href="https://www.npci.org.in/product/upi/product-statistics" target="_blank" rel="noreferrer">Open official source ↗</a>
                  </div>
                  {publicData?.notice && <p className="metric-detail" style={{ marginTop: 8 }}>{publicData.notice}</p>}
                </div>
              )}
            </>
          )}

          {active === "AI Investigator" && (
            <div className="investigation-layout">
              <div className="panel-card">
                <div className="card-heading">
                  <div>
                    <h3>Selected alert</h3>
                    <p>{selected?.transaction_id || "Select an alert"}</p>
                  </div>
                  {selected && (
                    <span
                      className={`tag ${
                        priorityFor(selected) === "High"
                          ? "tag-red"
                          : priorityFor(selected) === "Medium"
                            ? "tag-amber"
                            : "tag-gray"
                      }`}
                    >
                      {priorityFor(selected)}
                    </span>
                  )}
                </div>
                {selected ? (
                  <>
                    <Detail label="Transaction ID" value={selected.transaction_id} />
                    <Detail label="Account" value={selected.account_id} />
                    <Detail
                      label="Timestamp"
                      value={selected.transaction_timestamp}
                    />
                    <Detail
                      label="Amount (source units)"
                      value={formatAmount(selected.amount)}
                    />
                    <Detail label="Transaction type" value={selected.txn_type} />
                    <Detail label="Channel" value={selected.channel} />
                    <Detail label="MCC code" value={selected.mcc_code} />
                    <Detail
                      label="Counterparty ID"
                      value={selected.counterparty_id}
                    />
                    <Detail
                      label="Prior transactions"
                      value={selected.baseline_transactions}
                    />
                    <Detail
                      label="Past median"
                      value={formatAmount(selected.past_median_amount)}
                    />
                    <Detail
                      label="Amount multiple"
                      value={formatMultiple(selected.amount_multiple)}
                    />
                    <Detail
                      label="History sufficient"
                      value={selected.history_sufficient}
                    />
                    <Detail label="Review status" value={selected.alert_status} />
                    <Detail
                      label="Recorded fraud label"
                      value={selected.is_confirmed_fraud}
                    />
                    <div className="boundary-row">
                      <span>Alert reasons</span>
                      <strong>{reasonLabel(selected.reasons)}</strong>
                    </div>
                  <div className="empty-state compact">
                      <p>{selected.evidence_summary}</p>
                    </div>
                    <div className="comparison-bars" aria-label="Alert compared with available historical baseline">
                      <div className="card-heading"><div><h3>Observed amount vs baseline</h3><p>Source units · currency not verified</p></div></div>
                      {Number.isFinite(Number(selected.amount)) && selected.amount !== "" ? <div className="compare-row"><span>Current absolute amount</span><strong>{formatAmount(selected.absolute_amount || selected.amount)}</strong>{Number(selected.past_median_amount) > 0 && <i style={{ width: `${Math.max(4, Math.min(100, Math.abs(Number(selected.amount)) / Math.max(Math.abs(Number(selected.amount)), Math.abs(Number(selected.past_median_amount))) * 100))}%` }} />}</div> : <p className="chart-empty">Current amount is unavailable for this alert.</p>}
                      {Number.isFinite(Number(selected.past_median_amount)) && Number(selected.past_median_amount) > 0 ? <div className="compare-row"><span>Past median</span><strong>{formatAmount(selected.past_median_amount)}</strong><i style={{ width: `${Math.max(4, Math.min(100, Math.abs(Number(selected.past_median_amount)) / Math.max(Math.abs(Number(selected.amount)), Math.abs(Number(selected.past_median_amount))) * 100))}%` }} /></div> : <p className="chart-empty">Baseline comparison unavailable: the replay record has no past median amount.</p>}
                    </div>
                  </>
                ) : (
                  <p>
                    No alert selected. Load the API or choose an investigation.
                  </p>
                )}
              </div>
              <div className="panel-card">
                <div className="card-heading">
                  <div>
                    <h3>Gemini investigation</h3>
                    <p>AI-assisted, human-reviewed analysis</p>
                  </div>
                  <span className="tag tag-green">Gemini API</span>
                </div>
                <p className="metric-detail" style={{ marginBottom: 16 }}>
                  Generate an evidence-based investigation report for the
                  selected historical replay alert.
                </p>
                <button
                  className="secondary-button"
                  onClick={() => void runGeminiInvestigation()}
                  disabled={!selected || investigationLoading}
                >
                  {investigationLoading
                    ? "Investigating with Gemini..."
                    : "✳ Investigate with Gemini"}
                </button>
                {investigationLoading && (
                  <div className="empty-state compact" style={{ marginTop: 16 }}>
                    <p>
                      Analyzing the selected alert. Please wait…
                    </p>
                  </div>
                )}
                {investigationError && (
                  <div className="prototype-notice" style={{ marginTop: 16 }}>
                    <span className="notice-icon">!</span>
                    <span>
                      <strong>Investigation failed:</strong>{" "}
                      {investigationError}
                    </span>
                  </div>
                )}
                {investigationReport &&
                  investigationReport.transaction_id ===
                    selected?.transaction_id && (
                    <div style={{ marginTop: 20 }}>
                      <div className="section-heading">
                        <div>
                          <h2>Investigation report</h2>
                          <p>
                            {investigationReport.transaction_id} ·{" "}
                            {investigationReport.investigator}
                          </p>
                        </div>
                        <button
                          className="text-button"
                          onClick={() =>
                            void navigator.clipboard.writeText(
                              typeof investigationReport.report === "string" ? investigationReport.report : JSON.stringify(investigationReport.report, null, 2)
                            )
                          }
                        >
                          Copy report
                        </button>
                      </div>
                      <div
                        className="panel-card"
                        style={{
                          whiteSpace: "pre-wrap",
                          overflowWrap: "anywhere",
                          lineHeight: 1.75,
                        }}
                      >
                        {typeof investigationReport.report === "string" ? investigationReport.report : <div style={{ display: "grid", gap: 14 }}>
                          <section><strong>Summary</strong><p>{investigationReport.report.summary || "No summary returned."}</p></section>
                          <section><strong>Typed claims · uncertainty {investigationReport.report.uncertainty || "not stated"}</strong>{(investigationReport.report.claims || []).map((item, index) => <p key={index}><span className="tag tag-gray">{item.claim_type.replaceAll("_", " ")}</span> {item.claim} <span className="metric-detail">Refs: {item.evidence_refs?.join(", ") || "none"} · {item.uncertainty || "uncertainty not stated"}</span></p>)}</section>
                          {[ ["Alternative explanations", investigationReport.report.alternative_explanations], ["Missing information", investigationReport.report.missing_information], ["Recommended next steps", investigationReport.report.recommended_next_steps], ["Limitations", investigationReport.report.limitations] ].map(([title, values]) => <section key={String(title)}><strong>{String(title)}</strong><ul>{(values as string[] | undefined)?.map((item, index) => <li key={index}>{item}</li>)}</ul></section>)}
                        </div>}
                      </div>
                      <div className="panel-card" style={{ marginTop: 14 }}>
                        <div className="card-heading"><div><h3>Deterministic claim review</h3><p>Source consistency checks only · not semantic truth verification</p></div><span className="tag tag-amber">{investigationReport.claim_review?.review_status || "Not returned"}</span></div>
                        {(investigationReport.claim_review?.claims || []).map((item) => <div className="detail-row" key={item.claim_id} style={{ alignItems: "flex-start" }}><span style={{ minWidth: 78 }}>{item.claim_id} · {item.status}</span><strong style={{ textAlign: "left", maxWidth: "78%" }}>{item.claim}<br /><span className="metric-detail">{item.meaning}</span></strong></div>)}
                        {!(investigationReport.claim_review?.claims || []).length && <p className="metric-detail">No claim-level review results were returned.</p>}
                      </div>
                      <div className="human-note" style={{ marginTop: 12 }}>
                        {investigationReport.disclaimer ||
                          "AI findings are investigative assistance, not proof of fraud. A human analyst must validate the evidence and make the final decision."}
                      </div>
                    </div>
                  )}
                {!investigationReport && !investigationLoading && !investigationError && (
                  <div className="empty-state" style={{ marginTop: 18 }}>
                    <div className="empty-icon">✳</div>
                    <h3>Evidence ready for investigation</h3>
                    <p>
                      Select an alert and run Gemini to generate a report with
                      observed evidence, alternative explanations, recommended
                      checks, and limitations.
                    </p>
                  </div>
                )}
                <div className="human-note" style={{ marginTop: 16 }}>
                  An unusual transaction is not proof of fraud. AI findings must
                  be verified by a human analyst. No automatic account freezing
                  is performed.
                </div>
                <div className="panel-card pipeline-panel" style={{ marginTop: 16 }}>
                  <div className="card-heading"><div><h3>Investigation pipeline</h3><p>Current selected alert · API-returned and saved states only</p></div></div>
                  <div className="timeline-list">
                    <TimelineItem title="Alert" detail={selected?.transaction_id || "No alert selected"} state={selected ? "Loaded" : "Unavailable"} />
                    <TimelineItem title="Evidence bundle" detail={investigationForSelected ? `${investigatorEvidenceCount ?? "Returned"} evidence fields returned by the investigation endpoint` : "Built and returned when the investigation request completes"} state={investigationForSelected ? "Returned" : "Not run"} />
                    <TimelineItem title="Gemini report" detail={investigationError || investigationReport?.status || (investigationLoading ? "Request in progress" : "Not run")} state={investigationError ? "Error" : investigationReport ? "Returned" : investigationLoading ? "Running" : "Not run"} />
                    <TimelineItem title="Deterministic reviewer" detail={investigationForSelected?.reviewer?.review_status ? `${investigationForSelected.reviewer.review_status} · ${formatNumber(investigationForSelected.reviewer.flags_count)} flags` : "Not returned yet"} state={investigationForSelected?.reviewer?.review_status || "Not run"} />
                    <TimelineItem title="Claim-reference reviewer" detail={investigationForSelected?.claim_review?.review_status ? `${formatNumber(investigationForSelected.claim_review.passed_checks)} / ${formatNumber(investigationForSelected.claim_review.checks_run)} checks passed · integrity only` : "Not returned yet"} state={investigationForSelected?.claim_review?.review_status || "Not run"} />
                    <TimelineItem title="Analyst decision" detail={selectedCaseReviewMatches ? `${latestQualityReview?.decision} · ${latestQualityReview?.created_at}` : "No matching saved case review is loaded"} state={selectedCaseReviewMatches ? "Recorded" : "Not loaded"} />
                    <TimelineItem title="Audit history" detail={selectedCaseReviewMatches ? `${caseAudit.length} audit events loaded for ${editingCase?.case_key}` : "Select the matching transaction-linked case in Case Management"} state={selectedCaseReviewMatches ? (caseAuditError || "Case history") : "Not loaded"} />
                  </div>
                  <p className="human-note">Passing evidence-reference checks confirms reference integrity only; it does not prove a report claim is factually true or establish fraud.</p>
                </div>
              </div>
            </div>
          )}
          <footer>
            TRACEFORGE AI <span>·</span> Evidence-led financial investigations
          </footer>
        </div>
      </section>
    </main>
  );
}

function EvidenceSnapshotPanel({ snapshot }: { snapshot: Record<string, unknown> }) {
  const [selectedEvidenceId, setSelectedEvidenceId] = useState("");
  const evidenceBundle = (snapshot.evidence_bundle && typeof snapshot.evidence_bundle === "object" ? snapshot.evidence_bundle : {}) as Record<string, unknown>;
  const evidence = Array.isArray(evidenceBundle.evidence) ? evidenceBundle.evidence as Record<string, unknown>[] : [];
  const claimLinks = (snapshot.claim_links && typeof snapshot.claim_links === "object" ? snapshot.claim_links : {}) as Record<string, unknown>;
  const claims = Array.isArray(claimLinks.linked_claims) ? claimLinks.linked_claims as Record<string, unknown>[] : [];
  const claimReview = (snapshot.claim_review && typeof snapshot.claim_review === "object" ? snapshot.claim_review : {}) as Record<string, unknown>;
  const reviewer = (snapshot.reviewer && typeof snapshot.reviewer === "object" ? snapshot.reviewer : {}) as Record<string, unknown>;
  const checks = Array.isArray(claimReview.checks) ? claimReview.checks as Record<string, unknown>[] : [];
  const selectedEvidence = evidence.find((item) => item.evidence_id === selectedEvidenceId);
  const linkedEvidenceIds = (claim: Record<string, unknown>) => Array.isArray(claim.evidence_refs) ? (claim.evidence_refs as Record<string, unknown>[]).map((ref) => String(ref.evidence_id || "")) : [];
  const statusTag = String(claimReview.review_status || "Not available");
  return (
    <div style={{ marginTop: 14, padding: 14, borderRadius: 10, border: "1px solid var(--border, #273244)", background: "rgba(7, 13, 25, 0.38)" }}>
      <div className="card-heading"><div><h3>Evidence Explorer</h3><p>Claim-to-evidence links and saved validation results · read-only</p></div><span className="tag tag-green">Snapshot</span></div>
      <div className="prototype-notice" style={{ marginBottom: 12 }}><span className="notice-icon">i</span><span>Reference checks validate evidence identifiers and metadata, not whether fraud occurred. Source currency is unverified; counterparty IDs do not prove ownership.</span></div>
      <div className="metrics-grid" style={{ marginBottom: 16 }}>
        <Metric label="Evidence records" value={formatNumber(evidence.length)} detail="Saved source fields" icon="▤" />
        <Metric label="Linked claims" value={formatNumber(claims.length)} detail="Selected claims only" icon="⌁" />
        <Metric label="Claim checks passed" value={`${formatNumber(claimReview.passed_checks)} / ${formatNumber(claimReview.checks_run)}`} detail={statusTag} icon="✓" />
        <Metric label="Reviewer flags" value={formatNumber(reviewer.flags_count)} detail={String(reviewer.review_status || "Reviewer status unavailable")} icon="!" />
      </div>
      <div className="section-heading" style={{ marginTop: 12 }}><div><h2>Claim-to-evidence map</h2><p>Select an evidence ID to inspect the recorded source value</p></div></div>
      <div className="table-wrap">
        <table><thead><tr><th>CLAIM</th><th>CLAIM DESCRIPTION</th><th>SUPPORTING EVIDENCE</th><th>LINK STATUS</th></tr></thead>
          <tbody>{claims.map((claim) => {
            const refs = Array.isArray(claim.evidence_refs) ? claim.evidence_refs as Record<string, unknown>[] : [];
            return <tr key={String(claim.claim_id)}>
              <td><strong>{String(claim.claim_id || "—")}</strong></td>
              <td style={{ minWidth: 220, whiteSpace: "normal" }}>{String(claim.claim || "—")}</td>
              <td><div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{refs.map((ref) => <button key={String(ref.evidence_id)} className="text-button" onClick={() => setSelectedEvidenceId(String(ref.evidence_id))} style={{ border: "1px solid var(--border, #273244)", borderRadius: 6, padding: "4px 7px" }} title={`${String(ref.field || "field")} · ${String(ref.source || "source")}`}>{String(ref.evidence_id)}</button>)}</div></td>
              <td><span className={String(claim.link_status) === "MATCHED_TO_REPORT" ? "tag tag-green" : "tag tag-amber"}>{String(claim.link_status || "Not available")}</span></td>
            </tr>;
          })}
          {claims.length === 0 && <tr><td colSpan={4} className="no-results">No linked claims were stored in this snapshot.</td></tr>}</tbody>
        </table>
      </div>
      {selectedEvidence && <div className="panel-card" style={{ marginTop: 14 }}>
        <div className="card-heading"><div><h3>{String(selectedEvidence.evidence_id)} · {String(selectedEvidence.field || "Evidence field")}</h3><p>Source-record detail</p></div><span className={selectedEvidence.available ? "tag tag-green" : "tag tag-amber"}>{selectedEvidence.available ? "Available" : "Unavailable"}</span></div>
        <div className="detail-row"><span>Recorded value</span><strong style={{ overflowWrap: "anywhere", textAlign: "right", maxWidth: "70%" }}>{selectedEvidence.value === null || selectedEvidence.value === undefined ? "Not available" : String(selectedEvidence.value)}</strong></div>
        <div className="detail-row"><span>Source file</span><strong style={{ overflowWrap: "anywhere", textAlign: "right", maxWidth: "70%" }}>{String(selectedEvidence.source || "—")}</strong></div>
        <div className="detail-row"><span>Source record key</span><strong>{String(selectedEvidence.source_record_key || "—")}</strong></div>
        <button className="secondary-button" style={{ marginTop: 10 }} onClick={() => setSelectedEvidenceId("")}>Close evidence detail</button>
      </div>}
      <div className="section-heading" style={{ marginTop: 22 }}><div><h2>Evidence register</h2><p>{evidence.length} source-field references captured for this transaction</p></div></div>
      <div className="table-wrap"><table><thead><tr><th>ID</th><th>FIELD</th><th>VALUE</th><th>AVAILABLE</th><th>SOURCE RECORD</th></tr></thead><tbody>
        {evidence.map((item) => <tr key={String(item.evidence_id)}><td><button className="text-button" onClick={() => setSelectedEvidenceId(String(item.evidence_id))}>{String(item.evidence_id)}</button></td><td>{String(item.field || "—")}</td><td style={{ maxWidth: 300, whiteSpace: "normal", overflowWrap: "anywhere" }}>{item.value === null || item.value === undefined ? "Not available" : String(item.value)}</td><td><span className={item.available ? "tag tag-green" : "tag tag-amber"}>{item.available ? "Yes" : "No"}</span></td><td>{String(item.source_record_key || "—")}</td></tr>)}
        {evidence.length === 0 && <tr><td colSpan={5} className="no-results">No evidence records were stored in this snapshot.</td></tr>}
      </tbody></table></div>
      <div className="section-heading" style={{ marginTop: 22 }}><div><h2>Claim-reference validation</h2><p>Stored deterministic checks · not an independent fraud classifier</p></div><span className={String(claimReview.flags_count || 0) === "0" ? "tag tag-green" : "tag tag-red"}>{statusTag}</span></div>
      <div className="table-wrap"><table><thead><tr><th>CLAIM</th><th>CHECK</th><th>RESULT</th><th>DETAIL</th></tr></thead><tbody>
        {checks.map((check, index) => <tr key={`${String(check.claim_id)}-${String(check.check)}-${index}`}><td>{String(check.claim_id || "—")}</td><td>{String(check.check || "—")}</td><td><span className={String(check.status) === "PASS" ? "tag tag-green" : "tag tag-amber"}>{String(check.status || "—")}</span></td><td style={{ whiteSpace: "normal" }}>{String(check.details || "—")}</td></tr>)}
        {checks.length === 0 && <tr><td colSpan={4} className="no-results">No claim-reference checks are available in this snapshot.</td></tr>}
      </tbody></table></div>
      <div className="human-note" style={{ marginTop: 14 }}><strong>Reviewer limitations:</strong> {Array.isArray(claimReview.limitations) ? claimReview.limitations.map(String).join(" ") : "Claim-review limitations were not returned."} {Array.isArray(reviewer.limitations) ? reviewer.limitations.map(String).join(" ") : ""}</div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}><button className="secondary-button" onClick={() => void navigator.clipboard.writeText(JSON.stringify(snapshot, null, 2))}>Copy snapshot JSON</button></div>
    </div>
  );
}

function SnapshotValue({ value, depth }: { value: unknown; depth: number }) {
  if (value === null || value === undefined) return <span className="metric-detail">Not available</span>;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 13, lineHeight: 1.6 }}>{String(value)}</div>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="metric-detail">Empty list</span>;
    return <div style={{ display: "grid", gap: 8, paddingLeft: depth > 0 ? 10 : 0, borderLeft: depth > 0 ? "1px solid var(--border, #273244)" : undefined }}>
      {value.map((item, index) => <div key={index} style={{ border: "1px solid var(--border, #273244)", borderRadius: 7, padding: 9 }}>
        <div className="metric-detail" style={{ marginBottom: 5 }}>Item {index + 1}</div>
        <SnapshotValue value={item} depth={depth + 1} />
      </div>)}
    </div>;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="metric-detail">Empty object</span>;
    return <div style={{ display: "grid", gap: 8, paddingLeft: depth > 0 ? 10 : 0, borderLeft: depth > 0 ? "1px solid var(--border, #273244)" : undefined }}>
      {entries.map(([key, nested]) => <div key={key} style={{ padding: "7px 0", borderBottom: "1px solid var(--border, #273244)" }}>
        <div style={{ fontSize: 12, color: "var(--muted, #9eb2d0)", marginBottom: 4, overflowWrap: "anywhere" }}>{key.replaceAll("_", " ")}</div>
        <SnapshotValue value={nested} depth={depth + 1} />
      </div>)}
    </div>;
  }
  return <span>{String(value)}</span>;
}

function MoneyTrailGraph({
  data,
  selectedNodeId,
  onSelect,
}: {
  data: MoneyTrailData;
  selectedNodeId: string;
  onSelect: (node: MoneyTrailNode) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const columns = [
    { type: "account", title: "ACCOUNT", x: 150, fill: "#243b65", stroke: "#6f9dff" },
    { type: "transaction", title: "TRANSACTION", x: 450, fill: "#4b351c", stroke: "#f0b45a" },
    { type: "counterparty", title: "COUNTERPARTY", x: 750, fill: "#183e38", stroke: "#57d6b0" },
  ];
  const nodeById = new Map(data.nodes.map((node) => [node.id, node]));
  const positions = new Map<string, { x: number; y: number }>();
  let maxRows = 1;
  columns.forEach((column) => {
    const nodes = data.nodes.filter((node) => node.type === column.type);
    maxRows = Math.max(maxRows, nodes.length);
    nodes.forEach((node, index) => {
      positions.set(node.id, { x: column.x, y: 54 + index * 76 });
    });
  });
  const height = Math.max(220, 108 + maxRows * 76);
  return (
    <><div className="graph-toolbar"><span className="chart-source">Scroll the graph area to pan · edges are recorded alert associations</span><div><button className="secondary-button" aria-label="Zoom out graph" onClick={() => setZoom((value) => Math.max(.7, +(value - .15).toFixed(2)))}>−</button><span aria-live="polite">{Math.round(zoom * 100)}%</span><button className="secondary-button" aria-label="Zoom in graph" onClick={() => setZoom((value) => Math.min(1.75, +(value + .15).toFixed(2)))}>+</button><button className="text-button" onClick={() => setZoom(1)}>Reset</button></div></div>
    <div className="table-wrap graph-viewport" tabIndex={0} aria-label="Scrollable graph viewport" style={{ overflow: "auto", maxHeight: 650, background: "rgba(7, 13, 25, 0.45)", borderRadius: 12 }}>
      <div style={{ minWidth: 880 }}>
        <svg
          viewBox={`0 0 900 ${height}`}
          role="img"
          aria-label="Historical account transaction counterparty association graph"
          style={{ display: "block", width: `${900 * zoom}px`, minWidth: `${880 * zoom}px`, height: `${height * zoom}px` }}
        >
          <defs><marker id="money-trail-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#738da8" /></marker></defs>
          <text x="150" y="25" textAnchor="middle" fill="#9eb2d0" fontSize="12" fontWeight="700">ACCOUNT</text>
          <text x="450" y="25" textAnchor="middle" fill="#9eb2d0" fontSize="12" fontWeight="700">TRANSACTION</text>
          <text x="750" y="25" textAnchor="middle" fill="#9eb2d0" fontSize="12" fontWeight="700">COUNTERPARTY</text>
          {data.edges.map((edge) => {
            const source = positions.get(edge.source);
            const target = positions.get(edge.target);
            if (!source || !target) return null;
            return (
              <line
                key={edge.id}
                x1={source.x + 88}
                y1={source.y}
                x2={target.x - 88}
                y2={target.y}
                stroke={selectedNodeId && (edge.source === selectedNodeId || edge.target === selectedNodeId) ? "#69e2d7" : "#43536c"}
                strokeWidth={selectedNodeId && (edge.source === selectedNodeId || edge.target === selectedNodeId) ? "2.4" : "1.3"}
                opacity={selectedNodeId && edge.source !== selectedNodeId && edge.target !== selectedNodeId ? "0.25" : "0.8"}
                markerEnd="url(#money-trail-arrow)"
              ><title>{edge.relationship.replaceAll("_", " ")}</title></line>
            );
          })}
          {data.nodes.map((node) => {
            const position = positions.get(node.id);
            const column = columns.find((item) => item.type === node.type);
            if (!position || !column) return null;
            const isSelected = selectedNodeId === node.id;
            const displayLabel =
              node.label.length > 20 ? `${node.label.slice(0, 18)}…` : node.label;
            return (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`Select ${node.type} ${node.label}`}
                onClick={() => onSelect(node)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") onSelect(node);
                }}
                style={{ cursor: "pointer", outline: "none" }}
              >
                <rect
                  x={position.x - 88}
                  y={position.y - 22}
                  width="176"
                  height="44"
                  rx="10"
                  fill={column.fill}
                  stroke={isSelected ? "#ffffff" : column.stroke}
                  strokeWidth={isSelected ? 2.5 : 1.2}
                />
                <text
                  x={position.x}
                  y={position.y + 4}
                  textAnchor="middle"
                  fill="#f5f8ff"
                  fontSize="11"
                  fontWeight={isSelected ? "700" : "500"}
                >
                  {displayLabel}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div></>
  );
}
function Metric({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: string;
}) {
  return (
    <div className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-detail">{detail}</div>
    </div>
  );
}
function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      <strong>{value || "—"}</strong>
    </div>
  );
}
function CaseTable({
  cases,
  onSelect,
}: {
  cases: AlertRecord[];
  onSelect: (item: AlertRecord) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>TRANSACTION</th>
            <th>ACCOUNT</th>
            <th>AMOUNT*</th>
            <th>DEVIATION</th>
            <th>ALERT REASON</th>
            <th>PRIORITY</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cases.map((item) => {
            const priority = priorityFor(item);
            return (
              <tr key={item.transaction_id}>
                <td>
                  <button className="case-link" onClick={() => onSelect(item)}>
                    {item.transaction_id}
                  </button>
                </td>
                <td>{item.account_id}</td>
                <td>{formatAmount(item.amount)}</td>
                <td>{formatMultiple(item.amount_multiple)}</td>
                <td>{reasonLabel(item.reasons)}</td>
                <td>
                  <span
                    className={`tag ${
                      priority === "High"
                        ? "tag-red"
                        : priority === "Medium"
                          ? "tag-amber"
                          : "tag-gray"
                    }`}
                  >
                    {priority}
                  </span>
                </td>
                <td>
                  <button
                    className="row-arrow"
                    onClick={() => onSelect(item)}
                    aria-label={`Investigate ${item.transaction_id}`}
                  >
                    ↗
                  </button>
                </td>
              </tr>
            );
          })}
          {cases.length === 0 && (
            <tr>
              <td colSpan={7} className="no-results">
                No matching records. Check the search or API connection.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="table-foot">
        *Amounts are displayed in source dataset units. Currency has not been
        verified.
      </div>
    </div>
  );
}
