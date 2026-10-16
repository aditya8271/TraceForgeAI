
import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def generate_dataset(output_dir="data/generated", seed=42, rings=5):
    if rings < 1:
        raise ValueError("rings must be at least 1")

    rng = random.Random(seed)
    out = Path(output_dir)
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)

    accounts, transactions, observations, ground_truth = [], [], [], []
    tx_num = 1
    obs_num = 1

    def add_account(account_id, account_type, age_days):
        accounts.append({
            "account_id": account_id,
            "account_type": account_type,
            "created_at": (base - timedelta(days=age_days)).isoformat(),
        })

    def add_transaction(tx_id, sender, recipient, amount, minutes):
        transactions.append({
            "transaction_id": tx_id,
            "timestamp": (base + timedelta(minutes=minutes)).isoformat(),
            "from_account": sender,
            "to_account": recipient,
            "amount": f"{amount:.2f}",
            "channel": "synthetic_upi",
        })

    def add_observation(obs_id, account_id, device_id, octet, minutes):
        observations.append({
            "observation_id": obs_id,
            "account_id": account_id,
            "device_id": device_id,
            "ip_address": f"192.0.2.{octet}",
            "observed_at": (base + timedelta(minutes=minutes)).isoformat(),
        })

    # Planted synthetic transaction rings
    for i in range(1, rings + 1):
        victim = f"V{i:03d}"
        mule_a = f"M{i:03d}A"
        mule_b = f"M{i:03d}B"
        mule_c = f"M{i:03d}C"

        add_account(victim, "victim", 400)
        add_account(mule_a, "intermediary", 15)
        add_account(mule_b, "intermediary", 10)
        add_account(mule_c, "intermediary", 5)

        start = i * 100
        amount = rng.randint(20000, 80000)

        transfers = [
            (victim, mule_a, amount, start),
            (mule_a, mule_b, round(amount * 0.80, 2), start + 3),
            (mule_b, mule_c, round(amount * 0.56, 2), start + 6),
        ]

        for sender, recipient, value, minute in transfers:
            add_transaction(
                f"TX{tx_num:05d}", sender, recipient, value, minute
            )
            tx_num += 1

        shared_device = f"DEV-RING-{i:03d}"
        for account in (mule_a, mule_b):
            add_observation(
                f"OBS{obs_num:05d}", account, shared_device, i, start
            )
            obs_num += 1

        for account in (victim, mule_a, mule_b, mule_c):
            ground_truth.append({
                "ring_id": f"RING-{i:03d}",
                "account_id": account,
                "label": "planted_ring_member",
            })

    # Legitimate family accounts sharing a device (decoy)
    for i in range(1, 4):
        account = f"FAM{i:03d}"
        add_account(account, "ordinary", 200)
        add_observation(
            f"OBS{obs_num:05d}", account, "DEV-FAMILY-001", 250 + i, i * 10
        )
        obs_num += 1
        ground_truth.append({
            "ring_id": "DECOY-FAMILY",
            "account_id": account,
            "label": "legitimate_decoy",
        })

    # Legitimate shop with ordinary customer payments (decoy)
    merchant = "SHOP001"
    add_account(merchant, "merchant", 800)

    for i in range(1, 6):
        customer = f"CUS{i:03d}"
        add_account(customer, "ordinary", 120 + i)
        add_transaction(
            f"TX{tx_num:05d}", customer, merchant,
            rng.randint(100, 1500), 200 + i * 5,
        )
        tx_num += 1
        ground_truth.append({
            "ring_id": "DECOY-MERCHANT",
            "account_id": customer,
            "label": "legitimate_decoy",
        })

    ground_truth.append({
        "ring_id": "DECOY-MERCHANT",
        "account_id": merchant,
        "label": "legitimate_decoy",
    })

    write_csv(out / "accounts.csv", accounts,
              ["account_id", "account_type", "created_at"])
    write_csv(out / "transactions.csv", transactions,
              ["transaction_id", "timestamp", "from_account",
               "to_account", "amount", "channel"])
    write_csv(out / "entity_observations.csv", observations,
              ["observation_id", "account_id", "device_id",
               "ip_address", "observed_at"])
    write_csv(out / "ground_truth.csv", ground_truth,
              ["ring_id", "account_id", "label"])

    return {
        "accounts": len(accounts),
        "transactions": len(transactions),
        "observations": len(observations),
        "ground_truth_rows": len(ground_truth),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/generated")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rings", type=int, default=5)
    args = parser.parse_args()

    result = generate_dataset(args.output_dir, args.seed, args.rings)
    print("TraceForge AI dataset generated:")
    for name, count in result.items():
        print(f"{name}: {count}")
