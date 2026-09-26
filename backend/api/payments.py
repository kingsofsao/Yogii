"""Payment endpoints.

Flow: POST /payments/assess -> (demo verification in the UI) -> POST /payments.
Both take an `Idempotency-Key` header: retrying with the same key returns the
same attempt and never creates or submits a second payment.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user, user_rate_limit
from backend.api.presenters import iso, payment_view
from backend.core.services import get_payment_service
from backend.database.database import get_db
from backend.database.models import PaymentAttempt, RiskAssessment, User
from backend.domain.payment_service import PaymentError
from backend.schemas import (
    AssessRequest, AuthorizeRequest, PaymentListResponse, PaymentStatusResponse, PaymentView,
)

router = APIRouter(prefix="/payments", tags=["Payments"])

STATES = {"DRAFT", "ASSESSING", "NEEDS_VERIFICATION", "BLOCKED", "PENDING", "COMPLETED", "FAILED", "REVERSED"}
IDEMPOTENCY_HEADER = Header(..., alias="Idempotency-Key", min_length=8, max_length=100)


@router.post("/assess", response_model=PaymentView, status_code=201)
def assess_payment(payload: AssessRequest, idempotency_key: str = IDEMPOTENCY_HEADER,
                   user: User = Depends(user_rate_limit("payment_assess", 20, 60)), db: Session = Depends(get_db)):
    """Create a payment attempt and return its fraud-risk assessment.

    VERY_HIGH risk attempts are recorded as BLOCKED. MEDIUM and HIGH need demo
    verification before authorisation. Balances do not change here.
    """
    attempt = get_payment_service().assess(
        db, user, payload.recipient_upi, payload.amount, idempotency_key, note=payload.note,
        simulated_device=payload.simulated_context.device, simulated_location=payload.simulated_context.location)
    return payment_view(attempt, include_timeline=True)


@router.post("", response_model=PaymentView)
def authorize_payment(payload: AuthorizeRequest, idempotency_key: str = IDEMPOTENCY_HEADER,
                      user: User = Depends(user_rate_limit("payment_authorize", 20, 60)),
                      db: Session = Depends(get_db)):
    """Authorise an assessed attempt and submit it to the payment rail (the mock rail in simulation).

    Yogii never asks for a UPI PIN. In a future live integration, the sponsor
    bank's own authentication journey would handle that step.
    """
    attempt = get_payment_service().authorize(
        db, user, payload.payment_id, idempotency_key, payload.demo_verification_confirmed, payload.simulated_outcome)
    return payment_view(attempt, include_timeline=True)


@router.get("", response_model=PaymentListResponse)
def list_payments(state: Optional[str] = Query(None), band: Optional[str] = Query(None),
                  limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(PaymentAttempt).filter(PaymentAttempt.sender_user_id == user.id)
    if state:
        if state not in STATES:
            raise PaymentError("Unknown state filter.", 422, "invalid_filter")
        q = q.filter(PaymentAttempt.state == state)
    if band:
        if band not in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH"):
            raise PaymentError("Unknown risk band filter.", 422, "invalid_filter")
        q = q.join(RiskAssessment).filter(RiskAssessment.risk_band == band)
    total = q.count()
    rows = q.order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc()).offset(offset).limit(limit).all()
    return PaymentListResponse(items=[payment_view(p) for p in rows], total=total, limit=limit, offset=offset)


@router.get("/{payment_id}", response_model=PaymentView)
def get_payment(payment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    attempt = get_payment_service()._get_owned(db, payment_id, user.id)
    return payment_view(attempt, include_timeline=True)


@router.get("/{payment_id}/status", response_model=PaymentStatusResponse)
def payment_status(payment_id: int, user: User = Depends(user_rate_limit("payment_status", 60, 60)),
                   db: Session = Depends(get_db)):
    """Current state. For PENDING payments this asks the rail for the authoritative status."""
    attempt = get_payment_service().refresh_status(db, user, payment_id)
    return PaymentStatusResponse(id=attempt.id, reference=attempt.reference, state=attempt.state,
                                 provider=attempt.provider, is_simulated=attempt.is_simulated,
                                 updated_at=iso(attempt.updated_at))


@router.post("/{payment_id}/cancel", response_model=PaymentView)
def cancel_payment(payment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cancel an assessed payment before authorisation. It is kept for audit as FAILED."""
    return payment_view(get_payment_service().cancel(db, user, payment_id), include_timeline=True)
