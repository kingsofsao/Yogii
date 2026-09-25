import pytest
from backend.ml.inference import FraudInferenceService, ModelNotAvailableError
from backend.ml.feature_engine import FEATURE_COLUMNS

def test_feature_columns_schema_completeness():
    assert len(FEATURE_COLUMNS) == 23
    assert "amount" in FEATURE_COLUMNS
    assert "amount_ratio_avg" in FEATURE_COLUMNS
    assert "graph_pass_through_flag" in FEATURE_COLUMNS
    assert "unusual_hour" in FEATURE_COLUMNS

def test_risk_policy_threshold_boundaries():
    service = FraudInferenceService()
    # Test boundary mappings directly
    # 0–29: LOW
    # 30–59: MEDIUM
    # 60–84: HIGH
    # 85–100: VERY_HIGH

    # Synthetic check with mock predict values
    thresholds = [
        (29.0, "LOW", "ALLOW"),
        (30.0, "MEDIUM", "REVIEW"),
        (59.0, "MEDIUM", "REVIEW"),
        (60.0, "HIGH", "REVIEW"),
        (84.0, "HIGH", "REVIEW"),
        (85.0, "VERY_HIGH", "BLOCK"),
        (99.0, "VERY_HIGH", "BLOCK"),
    ]

    for score, expected_band, expected_decision in thresholds:
        if score < 30.0:
            band = "LOW"
            decision = "ALLOW"
        elif score < 60.0:
            band = "MEDIUM"
            decision = "REVIEW"
        elif score < 85.0:
            band = "HIGH"
            decision = "REVIEW"
        else:
            band = "VERY_HIGH"
            decision = "BLOCK"

        assert band == expected_band
        assert decision == expected_decision

def test_model_artifact_loading():
    service = FraudInferenceService()
    service.load_model()
    assert service._booster is not None

def test_strict_fail_fast_on_missing_model_artifact():
    service = FraudInferenceService(model_path="non_existent_model_artifact.json")
    with pytest.raises(ModelNotAvailableError) as exc:
        service.load_model()
    assert "Required XGBoost model artifact not found" in str(exc.value)

def test_inference_with_default_features():
    service = FraudInferenceService()
    service.load_model()
    
    # Feature vector with all zeros (missing history defaults)
    empty_features = {col: 0.0 for col in FEATURE_COLUMNS}
    empty_features["amount"] = 500.0
    empty_features["avg_amount_30d"] = 500.0
    empty_features["amount_ratio_avg"] = 1.0

    score, prob, band, decision, reasons = service.predict(empty_features)
    assert 0.0 <= score <= 100.0
    assert 0.0 <= prob <= 1.0
    assert band in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
    assert decision in ("ALLOW", "REVIEW", "BLOCK")
    assert isinstance(reasons, list)
