"""Train the Yogii prototype fraud-risk model on SYNTHETIC data.

    python -m backend.ml.train [--version 2.0.0-synthetic] [--seed 42] [--export-data path.csv]

Steps:
1. Generate a synthetic, time-ordered transaction stream (backend/ml/synthetic_data.py).
2. Time-based split: train 65% / early-stopping 7% / calibration 13% / test 15%.
   Features only use earlier events, and no row from a later period is used to fit an
   earlier stage, so there is no look-ahead leakage.
3. Train XGBoost (binary:logistic, hist) with scale_pos_weight for class imbalance.
4. Calibrate with isotonic regression on the calibration slice, so the reported
   score is a calibrated probability (on synthetic data) rather than a raw margin.
5. Report precision, recall, F1, PR-AUC, ROC-AUC, Brier score, confusion matrices,
   band statistics and gain-based feature importance on the untouched test slice.
6. Save a versioned artifact directory: backend/model/<version>/{model.json,
   calibration.json, metadata.json}.

The metrics describe how well the model recovers labels we generated ourselves.
They are not evidence of real-world fraud detection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover - exercised manually
    sys.exit("ERROR: XGBoost is not installed. Install backend requirements: pip install -r backend/requirements.txt")

from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, f1_score, precision_score, recall_score,
    roc_auc_score,
)

from backend.core.config import settings
from backend.ml.features import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION
from backend.ml.synthetic_data import generate_synthetic_dataset

PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "tree_method": "hist",
    "max_depth": 4,
    "eta": 0.05,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "min_child_weight": 2.0,
    "lambda": 1.0,
    "nthread": 1,  # single thread: reproducible trees
}
MAX_ROUNDS = 400
EARLY_STOPPING = 50


def _band_stats(scores: np.ndarray, labels: np.ndarray, thresholds: dict) -> dict:
    edges = [("LOW", 0, thresholds["MEDIUM"]), ("MEDIUM", thresholds["MEDIUM"], thresholds["HIGH"]),
             ("HIGH", thresholds["HIGH"], thresholds["VERY_HIGH"]), ("VERY_HIGH", thresholds["VERY_HIGH"], 101)]
    out = {}
    for name, lo, hi in edges:
        mask = (scores >= lo) & (scores < hi)
        out[name] = {"count": int(mask.sum()),
                     "synthetic_fraud_rate": round(float(labels[mask].mean()), 4) if mask.any() else None}
    return out


def _operating_point(labels: np.ndarray, scores: np.ndarray, cutoff: int) -> dict:
    pred = (scores >= cutoff).astype(int)
    tn, fp, fn, tp = confusion_matrix(labels, pred, labels=[0, 1]).ravel()
    return {
        "score_cutoff": cutoff,
        "precision": round(float(precision_score(labels, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(labels, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(labels, pred, zero_division=0)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def train_and_evaluate(output_dir: str | None = None, version: str | None = None, seed: int = 42,
                       export_data: str | None = None, quiet: bool = False) -> dict:
    version = version or settings.MODEL_VERSION
    out = Path(output_dir or settings.MODEL_DIR) / version
    log = (lambda *a: None) if quiet else print

    log(f"[train] generating SYNTHETIC transaction stream (seed={seed}) ...")
    df = generate_synthetic_dataset(seed=seed, graph_depth=settings.GRAPH_MAX_DEPTH,
                                    window_days=settings.FEATURE_HISTORY_DAYS)
    if export_data:
        df.to_csv(export_data, index=False)
        log(f"[train] synthetic data written to {export_data}")

    n = len(df)
    cut_train, cut_es, cut_cal = int(n * 0.65), int(n * 0.72), int(n * 0.85)
    parts = {"train": df.iloc[:cut_train], "early_stopping": df.iloc[cut_train:cut_es],
             "calibration": df.iloc[cut_es:cut_cal], "test": df.iloc[cut_cal:]}
    for name, part in parts.items():
        log(f"[train] {name:<15} {len(part):>6} rows, synthetic fraud rate {part.label.mean():.3f}, "
            f"{part.timestamp.min():%Y-%m-%d} .. {part.timestamp.max():%Y-%m-%d}")

    def dm(part):
        return xgb.DMatrix(part[FEATURE_COLUMNS].astype(float), label=part["label"].values, feature_names=FEATURE_COLUMNS)

    y_train = parts["train"]["label"].values
    spw = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))
    params = dict(PARAMS, scale_pos_weight=spw, seed=seed)
    d_train, d_es = dm(parts["train"]), dm(parts["early_stopping"])
    booster = xgb.train(params, d_train, num_boost_round=MAX_ROUNDS, evals=[(d_es, "early_stopping")],
                        early_stopping_rounds=EARLY_STOPPING, verbose_eval=False)
    best_rounds = booster.best_iteration + 1
    booster = xgb.train(params, d_train, num_boost_round=best_rounds)  # refit to exactly best_rounds trees
    log(f"[train] XGBoost trained: {best_rounds} trees, scale_pos_weight={spw:.2f}")

    raw_cal = booster.predict(dm(parts["calibration"]))
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw_cal, parts["calibration"]["label"].values)

    test = parts["test"]
    y_test = test["label"].values
    raw_test = booster.predict(dm(test))
    cal_test = np.interp(raw_test, iso.X_thresholds_, iso.y_thresholds_)
    scores = np.rint(cal_test * 100).astype(int)

    gain = booster.get_score(importance_type="gain")
    total = sum(gain.values()) or 1.0
    importance = dict(sorted(((f, round(gain.get(f, 0.0) / total, 4)) for f in FEATURE_COLUMNS),
                             key=lambda kv: -kv[1]))
    thresholds = settings.risk_thresholds
    per_scenario = (test.assign(score=scores).groupby("scenario")
                    .agg(rows=("score", "size"), mean_score=("score", "mean"),
                         share_high_or_above=("score", lambda s: float((s >= thresholds["HIGH"]).mean())))
                    .round(3).to_dict(orient="index"))

    metrics = {
        "WARNING": "Synthetic data only. These numbers show how well the model recovers labels we generated; "
                   "they are not real-world fraud performance.",
        "test_rows": int(len(test)),
        "test_synthetic_fraud_rate": round(float(y_test.mean()), 4),
        "pr_auc": round(float(average_precision_score(y_test, cal_test)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, cal_test)), 4),
        "brier_raw": round(float(brier_score_loss(y_test, raw_test)), 4),
        "brier_calibrated": round(float(brier_score_loss(y_test, cal_test)), 4),
        "at_high_threshold": _operating_point(y_test, scores, thresholds["HIGH"]),
        "at_block_threshold": _operating_point(y_test, scores, thresholds["VERY_HIGH"]),
        "at_verification_threshold": _operating_point(y_test, scores, thresholds["MEDIUM"]),
        "bands": _band_stats(scores, y_test, thresholds),
        "per_scenario_test": per_scenario,
    }
    # Headline numbers at the HIGH threshold (strong warning + verification).
    metrics.update({k: metrics["at_high_threshold"][k] for k in ("precision", "recall", "f1")})

    out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out / "model.json"))
    with open(out / "calibration.json", "w") as fh:
        json.dump({"method": "isotonic", "x": [float(v) for v in iso.X_thresholds_],
                   "y": [float(v) for v in iso.y_thresholds_]}, fh)
    model_sha = hashlib.sha256((out / "model.json").read_bytes()).hexdigest()
    metadata = {
        "model_version": version,
        "training_date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "XGBoost (binary:logistic, hist) + isotonic calibration",
        "score_kind": "calibrated_probability_synthetic",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": FEATURE_COLUMNS,
        "history_window_days": settings.FEATURE_HISTORY_DAYS,
        "graph_depth": settings.GRAPH_MAX_DEPTH,
        "seed": seed,
        "rows": {k: int(len(v)) for k, v in parts.items()},
        "split": "time-based: train 65%, early stopping 7%, calibration 13%, test 15%",
        "params": dict(params, num_boost_round=best_rounds),
        "model_sha256": model_sha,
        "metrics": metrics,
        "feature_importance_gain": importance,
        "is_synthetic": True,
        "disclaimer": ("Trained only on synthetic, fictional data for the Yogii simulation. Not validated on real "
                       "payments and not suitable for real risk decisions."),
    }
    with open(out / "metadata.json", "w") as fh:
        json.dump(metadata, fh, indent=2, default=str)

    log(f"[train] test PR-AUC {metrics['pr_auc']}, ROC-AUC {metrics['roc_auc']}, "
        f"Brier raw {metrics['brier_raw']} -> calibrated {metrics['brier_calibrated']}")
    log(f"[train] at score >= {thresholds['HIGH']}: precision {metrics['precision']}, recall {metrics['recall']}, "
        f"F1 {metrics['f1']}")
    log(f"[train] bands: {metrics['bands']}")
    log(f"[train] top features: {list(importance.items())[:8]}")
    log(f"[train] artifacts written to {out}")
    return metadata


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=None, help="model version (default: MODEL_VERSION setting)")
    ap.add_argument("--output-dir", default=None, help="artifact root (default: MODEL_DIR setting)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--export-data", default=None, help="also write the synthetic dataset to this CSV")
    args = ap.parse_args()
    train_and_evaluate(args.output_dir, args.version, args.seed, args.export_data)


if __name__ == "__main__":
    main()
