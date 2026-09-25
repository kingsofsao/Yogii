import json
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from backend.ml.feature_engine import FEATURE_COLUMNS
from backend.ml.synthetic_data import generate_synthetic_fraud_dataset
from backend.ml.train import compute_binary_metrics

def evaluate_saved_model(model_path: str = "backend/model/fraud_model.json", n_eval: int = 2000):
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model artifact not found at {path}. Fail clearly: no silent fallbacks.")

    booster = xgb.Booster()
    booster.load_model(str(path))

    df = generate_synthetic_fraud_dataset(n_samples=n_eval, seed=99)
    X = df[FEATURE_COLUMNS]
    y = df["label"].values

    dmat = xgb.DMatrix(X, feature_names=FEATURE_COLUMNS)
    preds = booster.predict(dmat)

    metrics = compute_binary_metrics(y, preds, threshold=0.5)

    print("=== Model Evaluation Report ===")
    print(f"Precision: {metrics['precision']}")
    print(f"Recall:    {metrics['recall']}")
    print(f"F1 Score:  {metrics['f1']}")
    print(f"PR-AUC:    {metrics['pr_auc']}")
    print(f"Confusion Matrix: {metrics['confusion_matrix']}")
    return metrics

if __name__ == "__main__":
    evaluate_saved_model()
