"""User settings.

Only personal preferences can be changed here. The payment mode and the
live-payments flag are read-only facts about the deployment: they come from
the server environment, and the request schema rejects any attempt to send them.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.core.config import mode_label, settings
from backend.core.services import get_provider
from backend.database.database import get_db
from backend.database.models import User, UserPreference
from backend.domain.risk_policy import RiskPolicy
from backend.schemas import PreferencesView, SettingsResponse, UpdatePreferencesRequest

router = APIRouter(prefix="/settings", tags=["Settings"])


def _prefs(db: Session, user: User) -> UserPreference:
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if prefs is None:
        prefs = UserPreference(user_id=user.id)
        db.add(prefs)
        db.flush()
    return prefs


def _response(prefs: UserPreference) -> SettingsResponse:
    policy = RiskPolicy()
    return SettingsResponse(
        mode=mode_label(),
        live_payments_enabled=bool(settings.LIVE_PAYMENTS_ENABLED and not settings.is_simulation),
        live_payments_note=("Live payments are disabled. They can only be enabled by the server deployment after "
                            "sponsor-bank onboarding and the required approvals, never from this app."),
        provider=get_provider().name,
        risk_policy_version=policy.version,
        risk_bands=policy.describe(),
        thresholds_note="Yogii prototype thresholds. Not RBI, NPCI or bank standards.",
        max_payment_amount=settings.MAX_PAYMENT_AMOUNT,
        history_window_days=settings.FEATURE_HISTORY_DAYS,
        graph_depth=settings.GRAPH_MAX_DEPTH,
        data_retention_days={"feature_snapshots": settings.RETENTION_FEATURE_SNAPSHOT_DAYS,
                             "security_events": settings.RETENTION_SECURITY_EVENT_DAYS,
                             "transaction_graph_edges": settings.RETENTION_GRAPH_EDGE_DAYS},
        preferences=PreferencesView(hide_balance=prefs.hide_balance, notify_on_high_risk=prefs.notify_on_high_risk,
                                    theme=prefs.theme),
    )


@router.get("", response_model=SettingsResponse)
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = _prefs(db, user)
    db.commit()
    return _response(prefs)


@router.patch("", response_model=SettingsResponse)
def update_settings(payload: UpdatePreferencesRequest, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    prefs = _prefs(db, user)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(prefs, field, value)
    db.commit()
    return _response(prefs)
