
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
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "features" / "account_features.csv"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "data" / "reports"

# Keep the original baseline model and report untouched.
MODEL_FILE = MODEL_DIR / "mule_counterparty_model.joblib"
REPORT_FILE = REPORT_DIR / "counterparty_model_metrics.json"
BASELINE_REPORT = REPORT_DIR / "validated_baseline_metrics.json"

MODEL_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    if not DATA.exists():
        raise FileNotFoundError(
            f"Feature file not found: {DATA}\n"
            "Run: py app\\feature_engine.py"
        )

    df = pd.read_csv(DATA)
    df = df[df["is_mule"].notna()].copy()
    df["is_mule"] = df["is_mule"].astype(int)

    new_features = [
        "debit_counterparties",
        "credit_counterparties",
    ]

    missing_features = [
        feature for feature in new_features
        if feature not in df.columns
    ]

    if missing_features:
        raise ValueError(
            f"Missing new features: {missing_features}. "
            "Regenerate account_features.csv first."
        )

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

    # Same deterministic 60/20/20 stratified split as baseline.
    X_train, X_temp, y_train, y_temp = train_test_split(
        X,
        y,
        test_size=0.40,
        stratify=y,
        random_state=42,
    )

    X_val, X_test, y_val, y_test = train_test_split(
        X_temp,
        y_temp,
        test_size=0.50,
        stratify=y_temp,
        random_state=42,
    )

    cat_cols = X.select_dtypes(
        include=["object", "category", "str"]
    ).columns.tolist()

    num_cols = X.select_dtypes(
        include=["number"]
    ).columns.tolist()

    preprocessor = ColumnTransformer([
        (
            "num",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]),
            num_cols,
        ),
        (
            "cat",
            Pipeline([
                (
                    "imputer",
                    SimpleImputer(strategy="most_frequent"),
                ),
                (
                    "encoder",
                    OneHotEncoder(handle_unknown="ignore"),
                ),
            ]),
            cat_cols,
        ),
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

    print("Training model with counterparty features...")
    print("Features:", X.shape[1])
    print("New features included:", new_features)

    pipeline.fit(X_train, y_train)

    # Select threshold on validation data only.
    val_scores = pipeline.predict_proba(X_val)[:, 1]

    minimum_precision = 0.20
    candidates = []

    for threshold in np.arange(0.01, 1.00, 0.01):
        preds = (val_scores >= threshold).astype(int)

        precision = precision_score(
            y_val, preds, zero_division=0
        )
        recall = recall_score(
            y_val, preds, zero_division=0
        )
        f1 = f1_score(
            y_val, preds, zero_division=0
        )

        if precision >= minimum_precision:
            candidates.append(
                (recall, f1, threshold, precision)
            )

    if candidates:
        # Maximize recall, then F1, subject to validation precision target.
        _, _, selected_threshold, _ = max(candidates)
    else:
        # Fallback if no threshold reaches the precision target.
        fallback = []

        for threshold in np.arange(0.01, 1.00, 0.01):
            preds = (val_scores >= threshold).astype(int)

            fallback.append((
                f1_score(y_val, preds, zero_division=0),
                threshold,
                precision_score(y_val, preds, zero_division=0),
            ))

        _, selected_threshold, _ = max(fallback)

    val_preds = (
        val_scores >= selected_threshold
    ).astype(int)

    # Final test evaluation: do not tune the threshold on this set.
    test_scores = pipeline.predict_proba(X_test)[:, 1]
    test_preds = (
        test_scores >= selected_threshold
    ).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_test,
        test_preds,
        labels=[0, 1],
    ).ravel()

    report = {
        "experiment": "random_forest_counterparty_features_v1",
        "feature_count": int(X.shape[1]),
        "new_features": new_features,
        "split_sizes": {
            "train": int(len(y_train)),
            "validation": int(len(y_val)),
            "test": int(len(y_test)),
        },
        "positive_counts": {
            "train": int(y_train.sum()),
            "validation": int(y_val.sum()),
            "test": int(y_test.sum()),
        },
        "minimum_validation_precision_target": minimum_precision,
        "selected_threshold": float(selected_threshold),
        "validation_precision": float(
            precision_score(y_val, val_preds, zero_division=0)
        ),
        "validation_recall": float(
            recall_score(y_val, val_preds, zero_division=0)
        ),
        "test_pr_auc": float(
            average_precision_score(y_test, test_scores)
        ),
        "test_precision": float(
            precision_score(y_test, test_preds, zero_division=0)
        ),
        "test_recall": float(
            recall_score(y_test, test_preds, zero_division=0)
        ),
        "test_f1": float(
            f1_score(y_test, test_preds, zero_division=0)
        ),
        "test_confusion_matrix_tn_fp_fn_tp": [
            int(tn), int(fp), int(fn), int(tp)
        ],
    }

    joblib.dump(
        {
            "pipeline": pipeline,
            "threshold": float(selected_threshold),
            "features": X.columns.tolist(),
        },
        MODEL_FILE,
    )

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\nTRACEFORGE AI — COUNTERPARTY MODEL RESULTS")
    print("Split sizes:", report["split_sizes"])
    print("Positive counts:", report["positive_counts"])
    print(f"Selected threshold: {selected_threshold:.2f}")
    print(
        f"Validation precision: "
        f"{report['validation_precision']:.3f}"
    )
    print(
        f"Validation recall: "
        f"{report['validation_recall']:.3f}"
    )
    print(f"Test PR-AUC: {report['test_pr_auc']:.4f}")
    print(f"Test precision: {report['test_precision']:.3f}")
    print(f"Test recall: {report['test_recall']:.3f}")
    print(f"Test F1: {report['test_f1']:.3f}")
    print(
        "Test confusion matrix [TN, FP, FN, TP]:",
        report["test_confusion_matrix_tn_fp_fn_tp"],
    )

    # Compare with the saved baseline report, if available.
    if BASELINE_REPORT.exists():
        with open(BASELINE_REPORT, "r", encoding="utf-8") as f:
            baseline = json.load(f)

        print("\n=== BASELINE COMPARISON ===")
        for metric in (
            "test_pr_auc",
            "test_precision",
            "test_recall",
            "test_f1",
        ):
            old_value = baseline.get(metric)
            new_value = report.get(metric)

            if old_value is not None and new_value is not None:
                delta = new_value - old_value
                print(
                    f"{metric}: baseline={old_value:.4f}, "
                    f"updated={new_value:.4f}, "
                    f"change={delta:+.4f}"
                )

        print(
            "Note: threshold-based precision, recall and F1 "
            "can change with the newly selected threshold."
        )
    else:
        print("\nBaseline report not found; comparison skipped.")

    print("\nSaved model:", MODEL_FILE)
    print("Saved report:", REPORT_FILE)


if __name__ == "__main__":
    main()
