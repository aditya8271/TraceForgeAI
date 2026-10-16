
import csv
from collections import defaultdict
from pathlib import Path

import networkx as nx


class FraudGraphEngine:
    """Build an evidence-backed graph from transaction CSV data."""

    def __init__(self, data_dir="data/generated"):
        self.data_dir = Path(data_dir)
        self.graph = nx.DiGraph()
        self.transactions = []

    def load_data(self):
        accounts_file = self.data_dir / "accounts.csv"
        transactions_file = self.data_dir / "transactions.csv"

        if not accounts_file.exists():
            raise FileNotFoundError(f"Missing file: {accounts_file}")

        if not transactions_file.exists():
            raise FileNotFoundError(f"Missing file: {transactions_file}")

        with accounts_file.open(encoding="utf-8", newline="") as file:
            for account in csv.DictReader(file):
                self.graph.add_node(
                    account["account_id"],
                    account_type=account["account_type"],
                    created_at=account["created_at"],
                )

        with transactions_file.open(
            encoding="utf-8", newline=""
        ) as file:
            self.transactions = list(csv.DictReader(file))

        for tx in self.transactions:
            sender = tx["from_account"]
            recipient = tx["to_account"]

            if sender not in self.graph:
                raise ValueError(
                    f"{tx['transaction_id']}: unknown sender {sender}"
                )

            if recipient not in self.graph:
                raise ValueError(
                    f"{tx['transaction_id']}: unknown recipient {recipient}"
                )

            amount = float(tx["amount"])
            if amount <= 0:
                raise ValueError(
                    f"{tx['transaction_id']}: amount must be positive"
                )

            # Keep every transaction as evidence. Multiple payments
            # between the same accounts must not overwrite one another.
            if not self.graph.has_edge(sender, recipient):
                self.graph.add_edge(
                    sender, recipient, transactions=[]
                )

            self.graph[sender][recipient]["transactions"].append({
                "transaction_id": tx["transaction_id"],
                "timestamp": tx["timestamp"],
                "amount": amount,
                "channel": tx["channel"],
            })

        return self.graph

    def find_money_trails(
        self, source_account, max_hops=4, min_amount=0
    ):
        """
        Return directed paths from a source account.

        Each hop must have at least one transaction meeting min_amount.
        The result includes the transaction IDs supporting every hop.
        """
        if source_account not in self.graph:
            raise ValueError(
                f"Unknown source account: {source_account}"
            )

        if max_hops < 1:
            raise ValueError("max_hops must be at least 1")

        trails = []

        def walk(current, path, evidence, hop_amounts):
            hops = len(path) - 1

            if hops >= max_hops:
                return

            for neighbor in sorted(self.graph.successors(current)):
                if neighbor in path:
                    continue

                edge_data = self.graph[current][neighbor]
                qualifying = [
                    tx for tx in edge_data["transactions"]
                    if tx["amount"] >= min_amount
                ]

                if not qualifying:
                    continue

                # Keep transaction-level evidence for this exact hop.
                for tx in sorted(
                    qualifying,
                    key=lambda item: item["transaction_id"],
                ):
                    next_path = path + [neighbor]
                    next_evidence = evidence + [{
                        "from_account": current,
                        "to_account": neighbor,
                        "transaction_id": tx["transaction_id"],
                        "amount": tx["amount"],
                        "timestamp": tx["timestamp"],
                    }]
                    next_amounts = hop_amounts + [tx["amount"]]

                    trails.append({
                        "source_account": source_account,
                        "destination_account": neighbor,
                        "path": next_path,
                        "hops": len(next_path) - 1,
                        "transactions": next_evidence,
                        "amounts_by_hop": next_amounts,
                    })

                    walk(
                        neighbor,
                        next_path,
                        next_evidence,
                        next_amounts,
                    )

        walk(source_account, [source_account], [], [])
        return trails

    def find_shared_devices(self):
        """Find accounts sharing a device, with observation evidence."""
        observations_file = self.data_dir / "entity_observations.csv"

        if not observations_file.exists():
            raise FileNotFoundError(
                f"Missing file: {observations_file}"
            )

        by_device = defaultdict(list)

        with observations_file.open(
            encoding="utf-8", newline=""
        ) as file:
            for row in csv.DictReader(file):
                by_device[row["device_id"]].append({
                    "account_id": row["account_id"],
                    "observation_id": row["observation_id"],
                    "observed_at": row["observed_at"],
                })

        findings = []

        for device_id, observations in sorted(by_device.items()):
            unique_accounts = sorted({
                item["account_id"] for item in observations
            })

            if len(unique_accounts) < 2:
                continue

            findings.append({
                "device_id": device_id,
                "accounts": unique_accounts,
                "observations": observations,
                "evidence_count": len(observations),
            })

        return findings

    def summary(self):
        """Return basic graph metrics; these are not fraud verdicts."""
        if self.graph.number_of_nodes() == 0:
            raise RuntimeError("Load data before requesting a summary")

        return {
            "accounts": self.graph.number_of_nodes(),
            "unique_account_pairs": self.graph.number_of_edges(),
            "transactions": len(self.transactions),
            "weakly_connected_components": (
                nx.number_weakly_connected_components(self.graph)
            ),
        }


if __name__ == "__main__":
    engine = FraudGraphEngine()
    engine.load_data()

    print("TRACEFORGE AI — GRAPH SUMMARY")
    print(engine.summary())

    print("\nMONEY TRAILS FROM V001")
    trails = engine.find_money_trails(
        source_account="V001",
        max_hops=4,
        min_amount=1000,
    )

    for trail in trails:
        print(
            f"Path: {' -> '.join(trail['path'])} | "
            f"Hops: {trail['hops']}"
        )
        for tx in trail["transactions"]:
            print(
                f"  Evidence: {tx['transaction_id']} | "
                f"{tx['from_account']} -> {tx['to_account']} | "
                f"Amount: {tx['amount']:.2f}"
            )

    print("\nSHARED DEVICE FINDINGS")
    for finding in engine.find_shared_devices():
        print(
            f"Device: {finding['device_id']} | "
            f"Accounts: {', '.join(finding['accounts'])} | "
            f"Observations: {finding['evidence_count']}"
        )
