from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from feature_engine import FEATURE_COLUMNS


MODEL_PATH = (
    Path(__file__).resolve().parent
    / "model"
    / "fraud_model.json"
)

_model = None


def load_model():
    global _model

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Fraud model not found: {MODEL_PATH}"
        )

    _model = xgb.Booster()

    _model.load_model(str(MODEL_PATH))

    print(
        f"Fraud model loaded successfully: {MODEL_PATH}"
    )


def predict(features):
    """
    Run XGBoost inference using the live transaction features.
    """

    global _model

    if _model is None:
        load_model()

    # Keep exactly the same feature order used during training.
    row = {
        column: features.get(column, 0)
        for column in FEATURE_COLUMNS
    }

    df = pd.DataFrame(
        [row],
        columns=FEATURE_COLUMNS,
    )

    df = df.apply(
        pd.to_numeric,
        errors="coerce",
    ).fillna(0)

    dmatrix = xgb.DMatrix(
        df,
        feature_names=FEATURE_COLUMNS,
    )

    prediction = _model.predict(dmatrix)

    probability = float(
        np.asarray(prediction).reshape(-1)[0]
    )

    probability = max(
        0.0,
        min(1.0, probability),
    )

    return probability


def get_shap_contributions(features):
    """
    Compute Tree SHAP contribution values natively using XGBoost's C++ explainer.
    """
    global _model
    if _model is None:
        load_model()

    row = {
        column: features.get(column, 0)
        for column in FEATURE_COLUMNS
    }
    df = pd.DataFrame([row], columns=FEATURE_COLUMNS).apply(
        pd.to_numeric, errors="coerce"
    ).fillna(0)

    dmatrix = xgb.DMatrix(df, feature_names=FEATURE_COLUMNS)
    try:
        contribs = _model.predict(dmatrix, pred_contribs=True)
        vals = contribs[0]
        shap_dict = {
            FEATURE_COLUMNS[i]: round(float(vals[i]), 4)
            for i in range(len(FEATURE_COLUMNS))
        }
        shap_dict["bias"] = round(float(vals[-1]), 4)
        return shap_dict
    except Exception as exc:
        print(f"SHAP contribution warning: {exc}")
        return {col: 0.0 for col in FEATURE_COLUMNS}


def explain(features, probability=None):
    """
    Generate XAI-style explanations from SHAP tree contributions
    and behavioural/contextual indicators. Returns (reasons, shap_values).
    """
    if probability is None:
        probability = predict(features)

    shap_values = get_shap_contributions(features)
    reasons = []

    amount = float(features.get("amount", 0))
    amount_ratio = float(features.get("amount_ratio", 0))
    max_ratio = float(features.get("max_ratio", 0))
    transactions_1h = int(features.get("transactions_1h", 0))
    transactions_today = int(features.get("transactions_today", 0))
    new_recipient = int(features.get("new_recipient", 0))
    unusual_hour = int(features.get("unusual_hour", 0))
    high_velocity = int(features.get("high_velocity", 0))
    recipient_seen = int(features.get("recipient_seen", 0))
    graph_degree = int(features.get("graph_degree", 0))

    if amount_ratio >= 3:
        reasons.append(
            f"Transaction amount ₹{amount:,.0f} is "
            f"significantly higher ({amount_ratio:.1f}x) than the user's normal average."
        )

    if max_ratio >= 1.5:
        reasons.append(
            "Transaction amount is unusually high "
            "compared with the user's historical maximum."
        )

    if new_recipient:
        reasons.append(
            "First-time transfer to an unverified recipient."
        )

    if unusual_hour:
        reasons.append(
            "Transaction initiated during high-risk unusual hour window."
        )

    if transactions_1h >= 5 or high_velocity:
        reasons.append(
            f"High transaction velocity detected: "
            f"{transactions_1h} transactions within the last hour."
        )

    if transactions_today >= 10:
        reasons.append(
            f"Unusually high daily activity: "
            f"{transactions_today} transactions today."
        )

    if not recipient_seen and not new_recipient:
        reasons.append(
            "Recipient has limited historical interaction with this account."
        )

    if graph_degree >= 5:
        reasons.append(
            "Transaction network graph reveals elevated connectivity dispersion."
        )

    # If SHAP identified a dominant positive risk driver not covered above:
    top_shap_features = sorted(
        [(k, v) for k, v in shap_values.items() if k != "bias" and v > 0.15],
        key=lambda x: x[1],
        reverse=True
    )
    for feat, impact in top_shap_features[:2]:
        readable_feat = feat.replace("_", " ").title()
        note = f"SHAP XAI: {readable_feat} contributed +{impact:.2f} towards risk score."
        if note not in reasons and len(reasons) < 4:
            reasons.append(note)

    if not reasons:
        if probability >= 0.75:
            reasons.append(
                "Multiple combined behavioural and graph indicators produce high risk."
            )
        elif probability >= 0.40:
            reasons.append(
                "Transaction pattern deviates moderately from baseline account profile."
            )
        else:
            reasons.append(
                "Transaction behaviour matches trusted historical profile."
            )

    return reasons, shap_values


def decision_for(probability):
    """
    Convert fraud probability into a transaction decision.
    """
    if probability >= 0.75:
        return "BLOCK"
    if probability >= 0.40:
        return "REVIEW"
    return "ALLOW"