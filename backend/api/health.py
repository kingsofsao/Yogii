from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.database.database import get_db
from backend.core.config import settings

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check():
    """Liveness probe returning application metadata and simulation mode status."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "payment_mode": settings.PAYMENT_MODE,
        "live_upi_enabled": settings.LIVE_UPI_ENABLED,
        "simulation_notice": "Yogii operates strictly in SIMULATION MODE. No real money or real UPI transactions."
    }

@router.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe checking database connectivity and XGBoost model availability."""
    # 1. Check Database
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connectivity check failed: {exc}"
        )

    # 2. Check XGBoost Model Artifact
    model_file = Path(settings.MODEL_PATH)
    if not model_file.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"XGBoost model artifact missing at '{model_file}'. Model training required."
        )

    return {
        "status": "ready",
        "database": "connected",
        "model": "loaded",
        "model_version": settings.MODEL_VERSION
    }
