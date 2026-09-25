import json
from pathlib import Path
from fastapi import APIRouter
from backend.schemas import ModelInfoResponse
from backend.ml.feature_engine import FEATURE_COLUMNS
from backend.core.config import settings

router = APIRouter(prefix="/model", tags=["Model Information"])

@router.get("/info", response_model=ModelInfoResponse)
def get_model_info():
    """
    Returns public inspection metadata for the Yogii fraud risk model.
    Includes model version, feature columns, and evaluation metrics on synthetic data.
    """
    meta_path = Path("backend/model/model_metadata.json")
    metrics = {}
    training_date = None

    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                data = json.load(f)
                metrics = data.get("metrics", {})
                training_date = data.get("training_date")
        except Exception:
            metrics = {}

    return ModelInfoResponse(
        model_version=settings.MODEL_VERSION,
        algorithm="XGBoost Classifier",
        training_date=training_date,
        metrics=metrics,
        feature_schema_version="v1",
        feature_columns=FEATURE_COLUMNS,
        is_synthetic=True,
        disclaimer=(
            "The synthetic XGBoost model does NOT establish real-world fraud performance. "
            "All predictions and risk scores are strictly prototype demonstrations."
        )
    )
