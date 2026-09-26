from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.api.presenters import iso, money, user_profile
from backend.core.config import mode_label
from backend.database.database import get_db
from backend.database.models import DemoPaymentAccount, SecurityEvent, User
from backend.schemas import MeResponse, SecurityEventView

router = APIRouter(tags=["Profile"])


@router.get("/me", response_model=MeResponse)
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.query(DemoPaymentAccount).filter(DemoPaymentAccount.user_id == user.id).first()
    return MeResponse(**user_profile(user).model_dump(),
                      simulated_balance=money(account.simulated_balance if account else 0), mode=mode_label())


@router.get("/me/security-events", response_model=List[SecurityEventView])
def my_security_events(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user's own recent security events (sign-in failures, blocked payments)."""
    rows = (db.query(SecurityEvent).filter(SecurityEvent.user_id == str(user.id))
            .order_by(SecurityEvent.created_at.desc()).limit(20).all())
    return [SecurityEventView(event_type=r.event_type, severity=r.severity, created_at=iso(r.created_at)) for r in rows]
