import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.api.deps import get_current_user
from backend.database.database import get_db
from backend.database.models import User, DemoPaymentAccount, PaymentAttempt, Recipient, RiskAssessment
from backend.schemas import DashboardSummaryResponse, PaymentAttemptResponse, RecipientResponse, RiskAssessmentResponse

router = APIRouter(tags=["Dashboard"])

@router.get("/dashboard", response_model=DashboardSummaryResponse)
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns aggregated dashboard data for the authenticated user:
    - Simulated balance (explicitly labelled)
    - Recent payment attempts with risk scores & reason codes
    - Saved / demo recipients
    - Risk engine statistics
    """
    profile = current_user.get_decrypted_profile()
    account = (
        db.query(DemoPaymentAccount)
        .filter(DemoPaymentAccount.user_id == current_user.id)
        .first()
    )
    balance = account.simulated_balance if account else 0.0

    # Fetch recent payments for this user
    payments = (
        db.query(PaymentAttempt)
        .filter(PaymentAttempt.sender_user_id == current_user.id)
        .order_by(desc(PaymentAttempt.created_at))
        .limit(20)
        .all()
    )

    recent_list = []
    for p in payments:
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

        recent_list.append(PaymentAttemptResponse(
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
        ))

    # Fetch demo recipients
    all_recipients = db.query(Recipient).order_by(Recipient.id).limit(10).all()
    recipient_list = []
    for r in all_recipients:
        rec_dec = r.get_decrypted()
        recipient_list.append(RecipientResponse(
            id=r.id,
            name=rec_dec["name"],
            upi_id=rec_dec["upi_id"],
            phone=rec_dec["phone"],
            recipient_type=r.recipient_type,
            merchant_category=r.merchant_category,
            trust_level=r.trust_level,
            is_fictional_demo=r.is_fictional_demo
        ))

    # Compute risk & payment stats
    total_tx = len(recent_list)
    completed_tx = sum(1 for p in recent_list if p.state == "COMPLETED")
    blocked_tx = sum(1 for p in recent_list if p.state == "BLOCKED")
    verified_tx = sum(1 for p in recent_list if p.state in ("NEEDS_VERIFICATION", "COMPLETED") and p.risk_assessment and p.risk_assessment.risk_band in ("MEDIUM", "HIGH"))

    return DashboardSummaryResponse(
        user={
            "id": current_user.id,
            "full_name": profile["full_name"],
            "phone": profile["phone"],
            "email": profile["email"],
            "upi_id": profile["upi_id"],
            "status": current_user.status,
            "simulated_balance": balance,
            "currency": "INR",
            "is_simulated_environment": True,
            "created_at": profile["created_at"]
        },
        simulated_balance=balance,
        currency="INR",
        is_simulation_mode=True,
        disclaimer="ALL BALANCES AND PAYMENTS ARE STRICTLY SIMULATED FOR DEMONSTRATION PURPOSES.",
        stats={
            "total_transactions": total_tx,
            "completed": completed_tx,
            "blocked_by_risk_policy": blocked_tx,
            "verified_reviews": verified_tx
        },
        recent_payments=recent_list,
        recipients=recipient_list
    )
