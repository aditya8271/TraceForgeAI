
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "features" / "account_features.csv"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "data" / "reports"

MODEL_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(DATA_PATH)

# Only accounts with known labels can be used for supervised training.
df = df[df["is_mule"].notna()].copy()
df["is_mule"] = df["is_mule"].astype(int)

# Exclude IDs, raw dates, branch identifiers, and the target.
# Raw dates are excluded until we define a valid prediction cutoff.
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

if y.nunique() != 2 or y.value_counts().min() < 2:
    raise ValueError("Both classes need at least two labelled examples.")

# Infer categorical and numerical columns.
categorical_cols = X.select_dtypes(
    include=["object", "category", "bool"]
).columns.tolist()

numeric_cols = X.select_dtypes(
    include=["number"]
).columns.tolist()

numeric_pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler()),
])

categorical_pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="most_frequent")),
    ("encoder", OneHotEncoder(handle_unknown="ignore")),
])

preprocessor = ColumnTransformer([
    ("numeric", numeric_pipeline, numeric_cols),
    ("categorical", categorical_pipeline, categorical_cols),
])

model = RandomForestClassifier(
    n_estimators=300,
    class_weight="balanced",
    min_samples_leaf=2,
    random_state=42,
    n_jobs=-1,
)

pipeline = Pipeline([
    ("preprocessor", preprocessor),
    ("model", model),
])

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.25,
    random_state=42,
    stratify=y,
)

pipeline.fit(X_train, y_train)

probabilities = pipeline.predict_proba(X_test)[:, 1]

# Initial operating threshold; it will be tuned after evaluation.
threshold = 0.50
predictions = (probabilities >= threshold).astype(int)

report = {
    "experiment": "random_forest_baseline_v1",
    "labelled_accounts": int(len(df)),
    "mule_accounts": int(y.sum()),
    "legitimate_accounts": int((y == 0).sum()),
    "train_rows": int(len(X_train)),
    "test_rows": int(len(X_test)),
    "features_before_encoding": int(X.shape[1]),
    "threshold": threshold,
    "average_precision_pr_auc": float(
        average_precision_score(y_test, probabilities)
    ),
    "precision": float(precision_score(
        y_test, predictions, zero_division=0
    )),
    "recall": float(recall_score(
        y_test, predictions, zero_division=0
    )),
    "f1": float(f1_score(
        y_test, predictions, zero_division=0
    )),
    "confusion_matrix_tn_fp_fn_tp": confusion_matrix(
        y_test, predictions, labels=[0, 1]
    ).ravel().tolist(),
    "classification_report": classification_report(
        y_test,
        predictions,
        labels=[0, 1],
        target_names=["legitimate", "mule"],
        zero_division=0,
        output_dict=True,
    ),
    "excluded_columns": excluded,
    "categorical_features": categorical_cols,
    "numeric_features": numeric_cols,
}

joblib.dump(pipeline, MODEL_DIR / "mule_baseline.joblib")

with open(REPORT_DIR / "baseline_metrics.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print("\nTRACEFORGE AI — BASELINE RESULTS")
print(f"Labelled accounts: {len(df):,}")
print(f"Training rows:     {len(X_train):,}")
print(f"Test rows:         {len(X_test):,}")
print(f"Mule prevalence:   {y.mean():.2%}")
print(f"PR-AUC:            {report['average_precision_pr_auc']:.4f}")
print(f"Precision:         {report['precision']:.4f}")
print(f"Recall:            {report['recall']:.4f}")
print(f"F1:                {report['f1']:.4f}")
print("Confusion matrix [TN, FP, FN, TP]:",
      report["confusion_matrix_tn_fp_fn_tp"])
print("\nSaved model:", MODEL_DIR / "mule_baseline.joblib")
print("Saved report:", REPORT_DIR / "baseline_metrics.json")
