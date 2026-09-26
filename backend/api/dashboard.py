from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.api.presenters import incoming_view, money, payment_view, user_profile
from backend.core.config import mode_label, settings
from backend.core.encryption import encryption_service
from backend.database.database import get_db
from backend.database.models import DemoPaymentAccount, PaymentAttempt, User, UserPreference
from backend.schemas import DashboardResponse

router = APIRouter(tags=["Dashboard"])

SIMULATION_NOTICE = ("Simulation mode: balances, accounts and payments are simulated. No real money moves and "
                     "Yogii is not connected to UPI, NPCI or any bank.")


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.query(DemoPaymentAccount).filter(DemoPaymentAccount.user_id == user.id).first()
    recent = (db.query(PaymentAttempt).filter(PaymentAttempt.sender_user_id == user.id)
              .order_by(PaymentAttempt.created_at.desc()).limit(6).all())
    incoming = (db.query(PaymentAttempt)
                .filter(PaymentAttempt.recipient_user_id == user.id, PaymentAttempt.state == "COMPLETED")
                .order_by(PaymentAttempt.created_at.desc()).limit(5).all())
    counts = dict(db.query(PaymentAttempt.state, func.count()).filter(PaymentAttempt.sender_user_id == user.id)
                  .group_by(PaymentAttempt.state).all())
    senders = {u.id: encryption_service.decrypt(u.full_name_enc)
               for u in db.query(User).filter(User.id.in_({p.sender_user_id for p in incoming})).all()} if incoming else {}
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    return DashboardResponse(
        user=user_profile(user), simulated_balance=money(account.simulated_balance if account else 0),
        currency="INR", mode=mode_label(), is_simulated=settings.is_simulation,
        notice=SIMULATION_NOTICE,
        stats={"completed": counts.get("COMPLETED", 0), "blocked": counts.get("BLOCKED", 0),
               "failed": counts.get("FAILED", 0), "pending": counts.get("PENDING", 0),
               "awaiting_action": counts.get("ASSESSING", 0) + counts.get("NEEDS_VERIFICATION", 0)},
        recent_payments=[payment_view(p) for p in recent],
        recent_incoming=[incoming_view(p, senders.get(p.sender_user_id, "A Yogii user")) for p in incoming],
        hide_balance=bool(prefs and prefs.hide_balance),
    )
