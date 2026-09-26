from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.config import mode_label, settings
from backend.database.database import get_db
from backend.ml.inference import inference_service

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    """Liveness. Reveals no configuration beyond the payment mode."""
    return {"status": "ok", "mode": mode_label()}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: database reachable and risk model loaded."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable.")
    if not inference_service.is_loaded:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Risk model not loaded.")
    return {"status": "ready", "mode": mode_label(), "model_version": settings.MODEL_VERSION}
