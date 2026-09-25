import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.api.deps import get_current_user
from backend.database.database import get_db
from backend.database.models import User, PaymentAttempt, RiskAssessment
from backend.schemas import (
    PaymentAssessRequest, PaymentVerifyRequest, PaymentAttemptResponse, RiskAssessmentResponse
)
from backend.domain.payment_service import payment_service, PaymentExecutionError
from backend.core.rate_limit import rate_limit

router = APIRouter(prefix="/payments", tags=["Payments"])

def _format_payment_response(p: PaymentAttempt) -> PaymentAttemptResponse:
    risk_resp = None
    if p.risk_assessment:
        ra = p.risk_assessment
        reasons = []
        try:
            raw = json.loads(ra.reason_codes_json)
            reasons = raw if isinstance(raw, list) else []
        except Exception:
            reasons = []

        risk_resp = RiskAssessmentResponse(
            raw_risk_score=ra.raw_risk_score,
            calibrated_probability=ra.calibrated_probability,
            risk_band=ra.risk_band,
            decision=ra.decision,
            reason_codes=reasons,
            model_version=ra.model_version
        )

    return PaymentAttemptResponse(
        id=p.id,
        reference=p.reference,
        sender_user_id=p.sender_user_id,
        recipient_upi=p.recipient_upi_masked,
        amount=p.amount,
        currency=p.currency,
        state=p.state,
        provider=p.provider,
        idempotency_key=p.idempotency_key,
        failure_reason=p.failure_reason,
        risk_assessment=risk_resp,
        is_simulated=True,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat()
    )

@router.post("/assess", response_model=PaymentAttemptResponse)
@router.post("", response_model=PaymentAttemptResponse)
def initiate_or_assess_payment(
    payload: PaymentAssessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _limiter: bool = Depends(rate_limit("payment_assess", max_requests=15, window_seconds=60))
):
    """
    Initiates payment assessment and state machine progression:
    - Verifies idempotency key
    - Performs XGBoost fraud risk assessment
    - LOW risk: executes payment through MockPaymentProvider immediately -> COMPLETED
    - MEDIUM/HIGH risk: transitions to NEEDS_VERIFICATION awaiting demo verification
    - VERY_HIGH risk: transitions to BLOCKED without altering balances
    """
    try:
        attempt = payment_service.assess_and_create_attempt(
            db=db,
            sender_user_id=current_user.id,
            recipient_upi=payload.recipient_upi,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
            payment_type=payload.payment_type,
            device_id=payload.device_id or "demo-device",
            location=payload.location or "Chennai"
        )
        return _format_payment_response(attempt)
    except PaymentExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

@router.post("/{payment_id}/verify", response_model=PaymentAttemptResponse)
def verify_payment(
    payment_id: int,
    payload: PaymentVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _limiter: bool = Depends(rate_limit("payment_verify", max_requests=10, window_seconds=60))
):
    """
    Submits Demo Verification for MEDIUM or HIGH risk transactions.
    Explicitly labeled as DEMO VERIFICATION. Never collects UPI PIN, OTP, or passwords.
    """
    try:
        attempt = payment_service.verify_and_continue_payment(
            db=db,
            payment_id=payment_id,
            sender_user_id=current_user.id,
            demo_verification_confirmed=payload.demo_verification_confirmed
        )
        return _format_payment_response(attempt)
    except PaymentExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

@router.get("", response_model=List[PaymentAttemptResponse])
def get_payment_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns paginated payment history for the authenticated user with risk metadata."""
    query = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.sender_user_id == current_user.id)
    )
    if status_filter:
        query = query.filter(PaymentAttempt.state == status_filter)

    payments = (
        query.order_by(desc(PaymentAttempt.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_format_payment_response(p) for p in payments]

@router.get("/{payment_id}", response_model=PaymentAttemptResponse)
def get_payment_detail(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns details of a specific payment attempt."""
    payment = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.id == payment_id, PaymentAttempt.sender_user_id == current_user.id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment attempt not found.")
    return _format_payment_response(payment)

@router.get("/{payment_id}/status")
def get_payment_status(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns current state and provider execution status of a payment."""
    payment = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.id == payment_id, PaymentAttempt.sender_user_id == current_user.id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment attempt not found.")
    return {
        "payment_id": payment.id,
        "reference": payment.reference,
        "state": payment.state,
        "provider": payment.provider,
        "is_simulated": True,
        "updated_at": payment.updated_at.isoformat()
    }
