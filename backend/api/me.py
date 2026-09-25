from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.api.deps import get_current_user
from backend.database.database import get_db
from backend.database.models import User, DemoPaymentAccount
from backend.schemas import UserProfileResponse

router = APIRouter(tags=["User Profile"])

@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns the authenticated user's profile and simulated balance.
    All data is decrypted safely on-the-fly for the authorized owner.
    """
    profile = current_user.get_decrypted_profile()
    account = (
        db.query(DemoPaymentAccount)
        .filter(DemoPaymentAccount.user_id == current_user.id)
        .first()
    )
    balance = account.simulated_balance if account else 0.0

    return UserProfileResponse(
        id=current_user.id,
        full_name=profile["full_name"],
        phone=profile["phone"],
        email=profile["email"],
        upi_id=profile["upi_id"],
        status=current_user.status,
        simulated_balance=balance,
        currency="INR",
        is_simulated_environment=True,
        created_at=profile["created_at"]
    )
