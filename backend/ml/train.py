import os
import json
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import xgboost as xgb
from backend.ml.feature_engine import FEATURE_COLUMNS
from backend.ml.synthetic_data import generate_synthetic_fraud_dataset
from backend.core.config import settings

def compute_binary_metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.5) -> dict:
    """
    Pure NumPy implementation of classification metrics:
    Precision, Recall, F1, PR-AUC, and Confusion Matrix.
    Avoids blocked DLL issues with third-party libraries on restricted host environments.
    """
    y_pred = (y_prob >= threshold).astype(int)
    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))

    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    f1 = (2 * prec * rec) / max(prec + rec, 1e-9)

    # Compute PR-AUC over 50 thresholds
    thresholds = np.linspace(0.01, 0.99, 50)
    precs = []
    recs = []
    for th in thresholds:
        yp = (y_prob >= th).astype(int)
        t_p = int(np.sum((y_true == 1) & (yp == 1)))
        f_p = int(np.sum((y_true == 0) & (yp == 1)))
        f_n = int(np.sum((y_true == 1) & (yp == 0)))
        precs.append(t_p / max(t_p + f_p, 1))
        recs.append(t_p / max(t_p + f_n, 1))

    # Sort by recall
    sorted_pairs = sorted(zip(recs, precs))
    r_sorted = [p[0] for p in sorted_pairs]
    p_sorted = [p[1] for p in sorted_pairs]
    pr_auc = float(np.trapezoid(p_sorted, r_sorted)) if hasattr(np, "trapezoid") else float(np.trapz(p_sorted, r_sorted))
    pr_auc = max(0.0, min(1.0, abs(pr_auc)))

    cm = [[tn, fp], [fn, tp]]

    return {
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "pr_auc": round(pr_auc, 4),
        "confusion_matrix": cm
    }

def train_and_evaluate(
    output_dir: str = "backend/model",
    model_version: str = "1.0.0-synthetic",
    n_samples: int = 8000
) -> dict:
    """
    Trains a production-grade XGBoost classifier on synthetic data.
    Computes PR-AUC, F1, precision, recall, confusion matrix, and feature importances.
    Saves model artifact and comprehensive metadata JSON.
    """
    print(f"Generating synthetic training dataset ({n_samples} records)...")
    df = generate_synthetic_fraud_dataset(n_samples=n_samples, seed=42)

    # Train (70%), Validation (15%), Test (15%) splits
    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    train_df = df.iloc[:train_end]
    val_df = df.iloc[train_end:val_end]
    test_df = df.iloc[val_end:]

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df["label"].values

    X_val = val_df[FEATURE_COLUMNS]
    y_val = val_df["label"].values

    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df["label"].values

    # Class imbalance weight
    num_neg = int((y_train == 0).sum())
    num_pos = int((y_train == 1).sum())
    scale_pos_weight = float(num_neg / max(num_pos, 1))

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLUMNS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=FEATURE_COLUMNS)

    params = {
        "objective": "binary:logistic",
        "eval_metric": ["logloss", "aucpr"],
        "max_depth": 5,
        "eta": 0.05,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "scale_pos_weight": scale_pos_weight,
        "seed": 42
    }

    evals = [(dtrain, "train"), (dval, "val")]
    print("Training XGBoost fraud model...")
    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=300,
        evals=evals,
        verbose_eval=False
    )

    # Evaluate on held-out test set
    preds_prob = booster.predict(dtest)
    metrics = compute_binary_metrics(y_test, preds_prob, threshold=0.5)

    # Feature importance
    importance_scores = booster.get_score(importance_type="gain")
    total_gain = sum(importance_scores.values()) if importance_scores else 1.0
    normalized_importance = {
        feat: round(importance_scores.get(feat, 0.0) / total_gain, 4)
        for feat in FEATURE_COLUMNS
    }
    metrics["feature_importance"] = normalized_importance
    metrics["test_sample_count"] = len(y_test)
    metrics["positive_rate_pct"] = round(float(y_test.mean() * 100), 2)

    print("\n=== XGBoost Fraud Model Evaluation Metrics ===")
    print(f"PR-AUC: {metrics['pr_auc']:.4f}")
    print(f"F1 Score: {metrics['f1']:.4f}")
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall: {metrics['recall']:.4f}")
    print(f"Confusion Matrix: {metrics['confusion_matrix']}")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    model_file = out_path / "fraud_model.json"
    meta_file = out_path / "model_metadata.json"

    booster.save_model(str(model_file))

    metadata = {
        "model_version": model_version,
        "training_date": datetime.now(timezone.utc).isoformat(),
        "algorithm": "XGBoost",
        "objective": "binary:logistic",
        "feature_schema_version": "v1",
        "feature_columns": FEATURE_COLUMNS,
        "metrics": metrics,
        "is_synthetic": True,
        "disclaimer": (
            "Model trained strictly on synthetic demo data for Yogii simulation testing. "
            "Not certified or representative of real-world banking fraud."
        )
    }

    with open(meta_file, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Model saved to: {model_file}")
    print(f"Metadata saved to: {meta_file}")
    return metadata

if __name__ == "__main__":
    train_and_evaluate()
