"""XGBoost inference with calibration and safe explanations.

There is no fallback. If XGBoost is not installed, or the versioned artifact
is missing or does not match this code's feature schema, the service raises
ModelNotAvailableError with setup instructions, and payment assessment is
refused. It never substitutes rules or another model.

Explanations use XGBoost's per-feature contributions (pred_contribs). The
contributions are grouped into user-safe reason codes, which describe what
looked unusual without revealing internal rules, thresholds or anything about
the receiver's private history.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from backend.core.config import settings
from backend.ml.features import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION

SETUP_HINT = "Run `python -m backend.ml.train` to create it (synthetic data only)."


class ModelNotAvailableError(RuntimeError):
    """The risk model cannot be used. Payments must not be assessed without it."""


# Reason code -> (features whose contributions count towards it, gating condition, safe text)
REASONS = {
    "AMOUNT_ABOVE_USUAL": (
        ("amount", "amount_log", "amount_ratio_avg", "amount_ratio_median", "amount_zscore",
         "sender_avg_amount", "sender_median_amount"),
        lambda f: f["amount_ratio_median"] >= 2.0 or f["amount_zscore"] >= 2.0,
        "This amount is much higher than what you usually send."),
    "NEW_RECIPIENT": (
        ("is_new_recipient", "prior_pair_count", "is_p2m"),
        lambda f: f["is_new_recipient"] == 1.0,
        "You haven't paid this recipient before."),
    "HIGH_RECENT_VELOCITY": (
        ("tx_count_30m", "tx_value_30m_ratio", "tx_count_24h", "tx_value_24h_ratio", "velocity_ratio_24h"),
        lambda f: f["tx_count_30m"] >= 2 or f["velocity_ratio_24h"] >= 3,
        "You've made several payments in a short time."),
    "UNUSUAL_TIME": (
        ("hour_deviation", "unusual_hour"),
        lambda f: f["unusual_hour"] == 1.0 or f["hour_deviation"] >= 5,
        "This is an unusual time of day for you to pay."),
    "DEVICE_OR_LOCATION_CHANGE": (
        ("device_novelty", "location_novelty"),
        lambda f: f["device_novelty"] == 1.0 or f["location_novelty"] == 1.0,
        "This payment comes from a device or location we haven't seen for your account (simulated signal)."),
    "POSSIBLE_PASS_THROUGH_PATTERN": (
        ("graph_hop_count", "graph_amount_similarity", "graph_time_gap_minutes", "graph_pass_through_flag"),
        lambda f: f["graph_pass_through_flag"] == 1.0,
        "Money you received recently appears to be moving on in a similar amount. This is a pattern, not proof."),
    "INDIRECT_TRANSACTION_LINK": (
        ("graph_indirect_link",),
        lambda f: f["graph_indirect_link"] == 1.0,
        "You're linked to this recipient only through an intermediary in the transaction graph."),
    "RECEIVER_RISK_SIGNAL": (
        ("receiver_is_registered", "receiver_on_watchlist", "receiver_account_age_days",
         "receiver_distinct_senders_24h", "receiver_inflow_count_24h", "receiver_outflow_ratio_24h"),
        lambda f: (f["receiver_on_watchlist"] == 1.0 or f["receiver_is_registered"] == 0.0
                   or 0 <= f["receiver_account_age_days"] < 30 or f["receiver_distinct_senders_24h"] >= 3
                   or f["receiver_outflow_ratio_24h"] >= 0.7),
        "The receiving account shows risk signals. For privacy we can't share details."),
    "LIMITED_HISTORY": (
        ("history_missing", "sender_history_count"),
        lambda f: f["history_missing"] == 1.0,
        "Your account has little payment history, so there is less to compare against."),
}
MIN_CONTRIBUTION = 0.05  # margin units; tiny pushes are not worth explaining


@dataclass
class RiskResult:
    risk_score: int                       # 0-100, from the calibrated probability
    calibrated_probability: float
    raw_probability: float
    reason_codes: List[Dict[str, str]]
    model_version: str
    score_kind: str = "calibrated_probability_synthetic"
    top_contributions: Dict[str, float] = field(default_factory=dict)


class FraudInferenceService:
    def __init__(self, model_dir: Optional[str] = None, version: Optional[str] = None):
        self.model_dir = Path(model_dir or settings.MODEL_DIR)
        self.version = version or settings.MODEL_VERSION
        self._booster = None
        self._cal_x: Optional[np.ndarray] = None
        self._cal_y: Optional[np.ndarray] = None
        self.metadata: Dict = {}
        self._lock = threading.Lock()

    @property
    def artifact_dir(self) -> Path:
        return self.model_dir / self.version

    @property
    def is_loaded(self) -> bool:
        return self._booster is not None

    def load_model(self) -> None:
        try:
            import xgboost as xgb
        except ImportError as exc:
            raise ModelNotAvailableError(
                "XGBoost is not installed, so the risk model cannot run. "
                "Install the backend requirements: pip install -r backend/requirements.txt") from exc
        d = self.artifact_dir
        needed = [d / "model.json", d / "calibration.json", d / "metadata.json"]
        missing = [p.name for p in needed if not p.exists()]
        if missing:
            raise ModelNotAvailableError(
                f"Risk model version '{self.version}' is missing {', '.join(missing)} in '{d}'. {SETUP_HINT}")
        try:
            metadata = json.loads((d / "metadata.json").read_text())
            cal = json.loads((d / "calibration.json").read_text())
            booster = xgb.Booster()
            booster.load_model(str(d / "model.json"))
        except Exception as exc:
            raise ModelNotAvailableError(f"Risk model in '{d}' could not be loaded: {exc}. {SETUP_HINT}") from exc
        if metadata.get("feature_columns") != FEATURE_COLUMNS or \
                metadata.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            raise ModelNotAvailableError(
                f"Risk model '{self.version}' was trained for a different feature schema. Retrain it. {SETUP_HINT}")
        if cal.get("method") != "isotonic" or not cal.get("x"):
            raise ModelNotAvailableError(f"Risk model '{self.version}' has no valid calibration. {SETUP_HINT}")
        with self._lock:
            self._booster = booster
            self._cal_x = np.asarray(cal["x"], dtype=float)
            self._cal_y = np.asarray(cal["y"], dtype=float)
            self.metadata = metadata

    def _require(self):
        if self._booster is None:
            self.load_model()
        return self._booster

    def predict(self, features: Dict[str, float]) -> RiskResult:
        booster = self._require()
        import xgboost as xgb

        missing = [c for c in FEATURE_COLUMNS if c not in features]
        if missing:
            raise ValueError(f"Feature vector is missing {missing}")
        row = np.asarray([[float(features[c]) for c in FEATURE_COLUMNS]], dtype=float)
        dm = xgb.DMatrix(row, feature_names=FEATURE_COLUMNS)
        raw = float(booster.predict(dm)[0])
        contribs = booster.predict(dm, pred_contribs=True)[0][:-1]  # last column is the bias
        calibrated = float(np.interp(raw, self._cal_x, self._cal_y))
        score = int(min(100, max(0, round(calibrated * 100))))
        contrib_map = {c: float(v) for c, v in zip(FEATURE_COLUMNS, contribs)}
        reasons = self.explain(features, contrib_map)
        top = dict(sorted(contrib_map.items(), key=lambda kv: -abs(kv[1]))[:8])
        return RiskResult(score, calibrated, raw, reasons, self.version,
                          top_contributions={k: round(v, 4) for k, v in top.items()})

    @staticmethod
    def explain(features: Dict[str, float], contributions: Dict[str, float]) -> List[Dict[str, str]]:
        scored = []
        for code, (cols, condition, text) in REASONS.items():
            total = sum(contributions.get(c, 0.0) for c in cols)
            if total >= MIN_CONTRIBUTION and condition(features):
                scored.append((total, {"code": code, "description": text}))
        scored.sort(key=lambda item: -item[0])
        return [r for _, r in scored]

    def info(self) -> Dict:
        meta = self.metadata or {}
        return {
            "model_version": self.version,
            "loaded": self.is_loaded,
            "algorithm": meta.get("algorithm"),
            "training_date": meta.get("training_date"),
            "score_kind": meta.get("score_kind"),
            "feature_schema_version": meta.get("feature_schema_version"),
            "feature_columns": meta.get("feature_columns", FEATURE_COLUMNS),
            "history_window_days": meta.get("history_window_days"),
            "graph_depth": meta.get("graph_depth"),
            "metrics": meta.get("metrics", {}),
            "feature_importance_gain": meta.get("feature_importance_gain", {}),
            "is_synthetic": True,
        }


inference_service = FraudInferenceService()
