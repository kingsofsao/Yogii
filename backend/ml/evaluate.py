"""Re-evaluate the saved model on a fresh synthetic stream (different seed).

    python -m backend.ml.evaluate [--seed 99]

SYNTHETIC DATA ONLY: this checks the artifact loads and behaves consistently,
not that it detects real fraud.
"""

import argparse

import numpy as np
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score

from backend.core.config import settings
from backend.ml.features import FEATURE_COLUMNS
from backend.ml.inference import inference_service
from backend.ml.synthetic_data import generate_synthetic_dataset


def evaluate(seed: int = 99) -> dict:
    inference_service.load_model()
    df = generate_synthetic_dataset(seed=seed, n_users=200, days=40)
    scores = np.array([inference_service.predict({c: float(row[c]) for c in FEATURE_COLUMNS}).risk_score
                       for _, row in df.iterrows()])
    y = df["label"].values
    pred = scores >= settings.RISK_THRESHOLD_HIGH
    out = {"rows": int(len(df)), "pr_auc": round(float(average_precision_score(y, scores)), 4),
           "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
           "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
           "f1": round(float(f1_score(y, pred, zero_division=0)), 4)}
    print("Synthetic re-evaluation (not real-world performance):", out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=99)
    evaluate(ap.parse_args().seed)
