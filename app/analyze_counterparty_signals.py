
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "reports" / "counterparty_signal_validation.csv"

df = pd.read_csv(DATA)
df = df.dropna(subset=["is_mule"]).copy()
df["is_mule"] = df["is_mule"].astype(int)

features = [
    "txn_count",
    "distinct_counterparties",
    "distinct_channels",
    "debit_count",
    "credit_count",
    "debit_counterparties",
    "credit_counterparties",
    "total_abs_amount",
]

print("\nTRACEFORGE AI — SINGLE-FEATURE EVALUATION")
print("Rows:", len(df))
print("Mule-labelled:", int(df["is_mule"].sum()))

results = []

for feature in features:
    valid = df[[feature, "is_mule"]].dropna()

    if valid[feature].nunique() < 2:
        continue

    auc = roc_auc_score(valid["is_mule"], valid[feature])

    # AUC below 0.5 means lower values tend to correspond
    # to the positive class; show direction-independent separation.
    separation_auc = max(auc, 1 - auc)

    mule_median = valid.loc[
        valid["is_mule"] == 1, feature
    ].median()

    legit_median = valid.loc[
        valid["is_mule"] == 0, feature
    ].median()

    results.append({
        "feature": feature,
        "legitimate_median": legit_median,
        "mule_median": mule_median,
        "roc_auc": auc,
        "separation_auc": separation_auc,
    })

result_df = pd.DataFrame(results).sort_values(
    "separation_auc", ascending=False
)

print("\n=== FEATURE SEPARATION ===")
print(result_df.round(4).to_string(index=False))

output = ROOT / "data" / "reports" / "counterparty_signal_auc.csv"
result_df.to_csv(output, index=False)

print("\nSaved:", output)
