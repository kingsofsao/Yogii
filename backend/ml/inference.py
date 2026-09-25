from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import json
import numpy as np
import pandas as pd
import xgboost as xgb
from backend.ml.feature_engine import FEATURE_COLUMNS
from backend.core.config import settings

class ModelNotAvailableError(RuntimeError):
    """
    Raised when the XGBoost model artifact is missing or corrupt.
    Strict Requirement: FAIL CLEARLY. Never silently fall back to rules or other models.
    """
    pass

class FraudInferenceService:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = Path(model_path or settings.MODEL_PATH)
        self._booster: Optional[xgb.Booster] = None
        self._metadata: Optional[Dict[str, Any]] = None

    def load_model(self) -> None:
        """Loads the XGBoost booster from the designated artifact path."""
        if not self.model_path.exists():
            raise ModelNotAvailableError(
                f"Required XGBoost model artifact not found at '{self.model_path}'. "
                "Silent fallback to heuristics or alternative models is strictly prohibited. "
                "Please run 'python -m backend.ml.train' to generate the model artifact."
            )

        try:
            self._booster = xgb.Booster()
            self._booster.load_model(str(self.model_path))
        except Exception as exc:
            raise ModelNotAvailableError(f"Failed to load XGBoost model from '{self.model_path}': {exc}") from exc

        meta_path = self.model_path.parent / "model_metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    self._metadata = json.load(f)
            except Exception:
                self._metadata = {}

    def predict(self, features: Dict[str, float]) -> Tuple[float, float, str, str, List[Dict[str, str]]]:
        """
        Executes inference using the loaded XGBoost model.
        
        Returns:
            raw_risk_score (0.0 to 100.0)
            calibrated_probability (0.0 to 1.0)
            risk_band (LOW, MEDIUM, HIGH, VERY_HIGH)
            decision (ALLOW, REVIEW, BLOCK)
            reason_codes (List of dicts with 'code' and 'description')
        """
        if self._booster is None:
            self.load_model()

        # Strict feature alignment
        row = {col: features.get(col, 0.0) for col in FEATURE_COLUMNS}
        df = pd.DataFrame([row], columns=FEATURE_COLUMNS).astype(float)
        dmatrix = xgb.DMatrix(df, feature_names=FEATURE_COLUMNS)

        try:
            raw_prob = float(self._booster.predict(dmatrix)[0])
        except Exception as exc:
            raise ModelNotAvailableError(f"XGBoost inference execution failed: {exc}") from exc

        prob = max(0.0, min(1.0, raw_prob))
        risk_score = round(prob * 100.0, 1)

        # Prototype Risk Band Thresholds:
        # 0–29: LOW
        # 30–59: MEDIUM
        # 60–84: HIGH
        # 85–100: VERY_HIGH
        if risk_score < 30.0:
            risk_band = "LOW"
            decision = "ALLOW"
        elif risk_score < 60.0:
            risk_band = "MEDIUM"
            decision = "REVIEW"
        elif risk_score < 85.0:
            risk_band = "HIGH"
            decision = "REVIEW"
        else:
            risk_band = "VERY_HIGH"
            decision = "BLOCK"

        reasons = self._derive_reasons(features, risk_band, prob)
        return risk_score, prob, risk_band, decision, reasons

    def _derive_reasons(
        self,
        features: Dict[str, float],
        risk_band: str,
        prob: float
    ) -> List[Dict[str, str]]:
        """
        Generates safe, privacy-conscious reason codes with user-friendly explanations.
        Never reveals receiver private history or internal bypass rules.
        """
        reasons: List[Dict[str, str]] = []

        amt = features.get("amount", 0.0)
        ratio = features.get("amount_ratio_avg", 1.0)
        dev_score = features.get("amount_deviation_score", 0.0)
        is_new = features.get("is_new_recipient", 0.0)
        tx_30m = features.get("tx_count_30m", 0.0)
        tx_24h = features.get("tx_count_24h", 0.0)
        unusual_hr = features.get("unusual_hour", 0.0)
        loc_novelty = features.get("simulated_location_novelty", 0.0)
        dev_novelty = features.get("simulated_device_novelty", 0.0)
        pass_through = features.get("graph_pass_through_flag", 0.0)

        if ratio >= 2.5 or dev_score >= 2.0:
            reasons.append({
                "code": "AMOUNT_ABOVE_USUAL",
                "description": f"Rs. {amt:,.0f} is significantly higher than your recent payment amounts."
            })

        if is_new == 1.0:
            reasons.append({
                "code": "NEW_RECIPIENT",
                "description": "First-time transfer to an unverified recipient identifier."
            })

        if tx_30m >= 3 or tx_24h >= 8:
            reasons.append({
                "code": "HIGH_RECENT_VELOCITY",
                "description": "Unusually high payment frequency detected on your account today."
            })

        if unusual_hr == 1.0:
            reasons.append({
                "code": "UNUSUAL_TIME",
                "description": "Payment initiated during an unusual time window for your profile."
            })

        if loc_novelty == 1.0 or dev_novelty == 1.0:
            reasons.append({
                "code": "DEVICE_OR_LOCATION_CHANGE",
                "description": "Unfamiliar simulated access point or device fingerprint."
            })

        if pass_through == 1.0:
            reasons.append({
                "code": "POSSIBLE_PASS_THROUGH_PATTERN",
                "description": "Transaction network graph identified a multi-hop flow pattern."
            })

        if not reasons:
            if risk_band in ("HIGH", "VERY_HIGH"):
                reasons.append({
                    "code": "UNUSUAL_TRANSACTION_PATTERN",
                    "description": "Multiple combined contextual signals deviate from your standard profile."
                })
            elif risk_band == "MEDIUM":
                reasons.append({
                    "code": "MODERATE_ANOMALY",
                    "description": "Transaction details vary moderately from historical account patterns."
                })
            else:
                reasons.append({
                    "code": "ROUTINE_TRANSACTION",
                    "description": "Transaction parameters align with your established account history."
                })

        return reasons

inference_service = FraudInferenceService()
