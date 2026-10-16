
from pathlib import Path

import joblib
import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)

ROOT = Path(__file__).resolve().parents[1]

DATA_PATH = ROOT / "data" / "features" / "account_features.csv"
MODEL_PATH = ROOT / "models" / "mule_baseline.joblib"

df = pd.read_csv(DATA_PATH)
df = df[df["is_mule"].notna()].copy()
df["is_mule"] = df["is_mule"].astype(int)

excluded = [
    "account_id",
    "is_mule",
    "branch_code",
    "branch_pin",
    "account_opening_date",
    "last_mobile_update_date",
    "last_kyc_date",
    "first_transaction",
    "last_transaction",
]

X = df.drop(columns=excluded, errors="ignore")
y = df["is_mule"]

# Must match the original training split exactly.
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.25,
    random_state=42,
    stratify=y,
)

pipeline = joblib.load(MODEL_PATH)
probabilities = pipeline.predict_proba(X_test)[:, 1]

print("\nTRACEFORGE AI — THRESHOLD COMPARISON")
print(f"Test accounts: {len(y_test):,}")
print(f"Mule-labelled test accounts: {int(y_test.sum())}")
print(f"PR-AUC (threshold-independent): "
      f"{average_precision_score(y_test, probabilities):.4f}")

print("\nThreshold | Precision | Recall | F1     | TP | FP | FN")
print("-" * 59)

results = []

for threshold in [0.50, 0.30, 0.20, 0.10, 0.05]:
    predictions = (probabilities >= threshold).astype(int)

    precision = precision_score(
        y_test, predictions, zero_division=0
    )
    recall = recall_score(
        y_test, predictions, zero_division=0
    )
    f1 = f1_score(
        y_test, predictions, zero_division=0
    )

    tn, fp, fn, tp = confusion_matrix(
        y_test, predictions, labels=[0, 1]
    ).ravel()

    results.append({
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
    })

    print(
        f"{threshold:9.2f} | {precision:9.3f} | "
        f"{recall:6.3f} | {f1:6.3f} | "
        f"{tp:2d} | {fp:2d} | {fn:2d}"
    )

output_path = ROOT / "data" / "reports" / "threshold_comparison.csv"
pd.DataFrame(results).to_csv(output_path, index=False)

print(f"\nSaved comparison: {output_path}")
