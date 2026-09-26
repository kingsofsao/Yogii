"""Risk bands, the decision policy, and the model artifact contract (no silent fallback)."""

import json
import shutil

import pytest

from backend.domain.risk_policy import RiskPolicy
from backend.ml.features import FEATURE_COLUMNS, GraphSignals, PaymentContext, ReceiverStats, compute_features
from backend.ml.inference import REASONS, FraudInferenceService, ModelNotAvailableError, inference_service
from backend.ml.synthetic_data import generate_synthetic_dataset


@pytest.mark.parametrize("score,band,decision", [
    (0, "LOW", "ALLOW"), (29, "LOW", "ALLOW"), (30, "MEDIUM", "VERIFY"), (59, "MEDIUM", "VERIFY"),
    (60, "HIGH", "VERIFY"), (84, "HIGH", "VERIFY"), (85, "VERY_HIGH", "BLOCK"), (100, "VERY_HIGH", "BLOCK"),
])
def test_band_boundaries(score, band, decision):
    d = RiskPolicy().decide(score)
    assert (d.band, d.decision) == (band, decision)
    assert d.blocked == (band == "VERY_HIGH")
    assert d.requires_verification == (band in ("MEDIUM", "HIGH"))


def test_thresholds_are_configurable_and_validated():
    p = RiskPolicy({"MEDIUM": 20, "HIGH": 50, "VERY_HIGH": 90})
    assert p.decide(25).band == "MEDIUM" and p.decide(89).band == "HIGH" and p.decide(90).blocked
    with pytest.raises(ValueError):
        RiskPolicy({"MEDIUM": 50, "HIGH": 40, "VERY_HIGH": 90})
    with pytest.raises(ValueError):
        RiskPolicy().decide(101)


def test_graph_signal_alone_never_blocks():
    p = RiskPolicy()
    only_graph = p.decide(95, ["POSSIBLE_PASS_THROUGH_PATTERN"])
    assert not only_graph.blocked and only_graph.decision == "VERIFY" and only_graph.band == "HIGH"
    assert p.decide(95, ["POSSIBLE_PASS_THROUGH_PATTERN", "NEW_RECIPIENT"]).blocked


def test_missing_artifact_fails_clearly(tmp_path):
    svc = FraudInferenceService(model_dir=str(tmp_path), version="does-not-exist")
    with pytest.raises(ModelNotAvailableError, match="python -m backend.ml.train"):
        svc.load_model()
    with pytest.raises(ModelNotAvailableError):
        svc.predict({c: 0.0 for c in FEATURE_COLUMNS})  # lazy load also refuses; no fallback score


def test_schema_mismatch_fails_clearly(tmp_path):
    src = inference_service.artifact_dir
    dst = tmp_path / "v-test"
    shutil.copytree(src, dst)
    meta = json.loads((dst / "metadata.json").read_text())
    meta["feature_columns"] = meta["feature_columns"][:-1]
    (dst / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ModelNotAvailableError, match="different feature schema"):
        FraudInferenceService(model_dir=str(tmp_path), version="v-test").load_model()


def test_metadata_reports_required_metrics():
    m = inference_service.metadata
    assert m["is_synthetic"] is True and m["feature_columns"] == FEATURE_COLUMNS
    for key in ("precision", "recall", "f1", "pr_auc", "brier_calibrated"):
        assert key in m["metrics"]
    assert m["metrics"]["brier_calibrated"] <= m["metrics"]["brier_raw"]
    assert sum(m["feature_importance_gain"].values()) == pytest.approx(1.0, abs=0.01)
    assert "time-based" in m["split"]


def _features(**over):
    from datetime import datetime, timezone
    ctx = PaymentContext(500.0, datetime(2026, 3, 1, 8, tzinfo=timezone.utc), "acct:r", "P2P", "d", "l")
    f = compute_features(ctx, [], ReceiverStats(is_registered=True, account_age_days=400), GraphSignals())
    f.update(over)
    return f


def test_prediction_is_bounded_and_explained_safely():
    r = inference_service.predict(_features())
    assert 0 <= r.risk_score <= 100 and 0.0 <= r.calibrated_probability <= 1.0
    risky = inference_service.predict(_features(receiver_on_watchlist=1.0, receiver_is_registered=0.0,
                                                receiver_account_age_days=-1.0, amount=40000.0,
                                                amount_ratio_avg=40.0, amount_ratio_median=40.0, amount_zscore=30.0,
                                                device_novelty=1.0, history_missing=0.0))
    assert risky.risk_score > r.risk_score
    codes = {x["code"] for x in risky.reason_codes}
    assert codes <= set(REASONS)
    assert "RECEIVER_RISK_SIGNAL" in codes
    for reason in risky.reason_codes:
        assert not any(ch.isdigit() for ch in reason["description"]), "no thresholds or numbers leak to users"


def test_synthetic_generator_is_deterministic_and_time_ordered():
    a = generate_synthetic_dataset(seed=7, n_users=40, days=20)
    b = generate_synthetic_dataset(seed=7, n_users=40, days=20)
    assert a[FEATURE_COLUMNS + ["label"]].equals(b[FEATURE_COLUMNS + ["label"]])
    assert a["timestamp"].is_monotonic_increasing
    assert 0 < a["label"].mean() < 0.2
