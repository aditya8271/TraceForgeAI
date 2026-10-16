"""Synthetic fraud-ring detection and measurable benchmark for TraceForge AI.

This module only evaluates the controlled synthetic dataset produced by
generate_data.py. Its metrics must not be presented as performance on real
banking data.
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required synthetic dataset file is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def evaluate_synthetic_rings(data_dir: str | Path, max_hops: int = 4) -> dict[str, Any]:
    root = Path(data_dir)
    accounts = read_csv(root / "accounts.csv")
    txns = read_csv(root / "transactions.csv")
    observations = read_csv(root / "entity_observations.csv")
    truth_rows = read_csv(root / "ground_truth.csv")

    account_ids = {r["account_id"] for r in accounts}
    truth: dict[str, str] = {}
    for row in truth_rows:
        truth[row["account_id"]] = row["label"]

    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tx in txns:
        if tx["from_account"] in account_ids and tx["to_account"] in account_ids:
            try:
                amount = float(tx["amount"])
            except (ValueError, TypeError):
                continue
            adjacency[tx["from_account"]].append({
                "to": tx["to_account"], "id": tx["transaction_id"],
                "amount": amount, "timestamp": tx.get("timestamp", ""),
            })

    # Explainable heuristic: flag nodes participating in a multi-hop path
    # with decreasing transfers and flag endpoints of such paths.
    predicted: set[str] = set()
    detected_paths: list[dict[str, Any]] = []
    max_paths = 5000
    def walk(start: str, current: str, path: list[str], evidence: list[dict[str, Any]]) -> None:
        if len(evidence) >= max_hops or len(detected_paths) >= max_paths:
            return
        for edge in adjacency.get(current, []):
            nxt = edge["to"]
            if nxt in path:
                continue
            next_path = path + [nxt]
            next_evidence = evidence + [{
                "transaction_id": edge["id"], "from_account": current,
                "to_account": nxt, "amount": edge["amount"],
                "timestamp": edge["timestamp"],
            }]
            if len(next_evidence) >= 2:
                amounts = [x["amount"] for x in next_evidence]
                decreasing = all(amounts[i+1] < amounts[i] for i in range(len(amounts)-1))
                if decreasing and amounts[0] >= 10000:
                    predicted.update(next_path)
                    detected_paths.append({
                        "path": next_path, "hops": len(next_evidence),
                        "transactions": next_evidence,
                        "signal": "decreasing_multi_hop_transfers",
                        "evidence_status": "synthetic_transaction_records",
                    })
            walk(start, nxt, next_path, next_evidence)
    for account_id in sorted(account_ids):
        walk(account_id, account_id, [account_id], [])
        if len(detected_paths) >= max_paths:
            break

    # Shared-device is corroborating context only, not sufficient to label fraud.
    by_device: dict[str, set[str]] = defaultdict(set)
    for obs in observations:
        by_device[obs["device_id"]].add(obs["account_id"])
    shared_device_groups = [
        {"device_id": device, "accounts": sorted(ids), "account_count": len(ids),
         "signal": "shared_device_observation_not_proof_of_fraud"}
        for device, ids in sorted(by_device.items()) if len(ids) >= 2
    ]

    evaluated = [a for a in account_ids if truth.get(a) in {"planted_ring_member", "legitimate_decoy"}]
    positive = {a for a in evaluated if truth.get(a) == "planted_ring_member"}
    negative = {a for a in evaluated if truth.get(a) == "legitimate_decoy"}
    tp = len(predicted & positive)
    fp = len(predicted & negative)
    fn = len(positive - predicted)
    tn = len(negative - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {
        "mode": "controlled_synthetic_benchmark",
        "disclaimer": "Metrics apply only to this generated toy dataset, not real-world bank fraud.",
        "accounts_evaluated": len(evaluated),
        "ground_truth_positive_accounts": len(positive),
        "ground_truth_legitimate_decoys": len(negative),
        "predicted_suspicious_accounts": len(predicted & set(evaluated)),
        "confusion_matrix": {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn},
        "metrics": {"precision": round(precision, 4), "recall": round(recall, 4), "false_positive_rate": round(fpr, 4)},
        "detected_path_count": len(detected_paths),
        "detected_paths": detected_paths[:100],
        "shared_device_groups": shared_device_groups,
        "limitations": [
            "Rule-based heuristic, not a trained classifier.",
            "Synthetic planted patterns may be easier than real financial crime.",
            "Shared devices and graph paths are signals, not proof of criminality.",
            "The generator's ground-truth labels define the benchmark target.",
            "Predictions are evaluated at account level; unlabeled accounts are excluded.",
        ],
    }
