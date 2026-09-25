from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from backend.api.deps import get_current_user
from backend.database.models import User
from backend.schemas import AppSettingsResponse
from backend.core.config import settings

router = APIRouter(prefix="/settings", tags=["Application Settings"])

class UpdateSettingsPayload(BaseModel):
    # Ordinary user settings (e.g. notifications, preferences)
    # Cannot enable live UPI or alter payment mode
    notifications_enabled: Optional[bool] = True
    theme: Optional[str] = "light"
    live_upi_enabled: Optional[bool] = None

@router.get("", response_model=AppSettingsResponse)
def get_app_settings(current_user: User = Depends(get_current_user)):
    """
    Returns public application operational settings.
    PAYMENT_MODE is hardcoded to simulation.
    """
    return AppSettingsResponse(
        payment_mode=settings.PAYMENT_MODE,
        live_upi_enabled=settings.LIVE_UPI_ENABLED,
        risk_thresholds={
            "LOW": "0–29 (Allow simulated payment)",
            "MEDIUM": "30–59 (Warning + Demo verification)",
            "HIGH": "60–84 (Strong warning + Demo verification)",
            "VERY_HIGH": "85–100 (Block simulated payment)"
        },
        max_payment_limit=100000.0,
        environment=settings.APP_ENV
    )

@router.patch("")
def update_app_settings(
    payload: UpdateSettingsPayload,
    current_user: User = Depends(get_current_user)
):
    """
    Updates user settings.
    Enforces invariant: An ordinary user CANNOT enable live UPI or change payment mode.
    """
    if payload.live_upi_enabled is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Permission denied: Ordinary users cannot enable live UPI. "
                "Yogii requires approved Sponsor-Bank onboarding, NPCI TPAP certification, "
                "and production PSP authorization."
            )
        )
    return {
        "status": "success",
        "message": "User settings updated.",
        "preferences": {
            "notifications_enabled": payload.notifications_enabled,
            "theme": payload.theme
        }
    }
