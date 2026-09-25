from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.database.database import get_db
from backend.database.models import User, Recipient
from backend.schemas import RecipientResponse
from backend.core.encryption import encryption_service
from backend.core.rate_limit import rate_limit

router = APIRouter(prefix="/recipients", tags=["Recipients"])

@router.get("", response_model=List[RecipientResponse])
def list_recipients(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists fictional demo recipients and saved contacts."""
    recipients = db.query(Recipient).all()
    out = []
    for r in recipients:
        dec = r.get_decrypted()
        out.append(RecipientResponse(
            id=r.id,
            name=dec["name"],
            upi_id=dec["upi_id"],
            phone=dec["phone"],
            recipient_type=r.recipient_type,
            merchant_category=r.merchant_category,
            trust_level=r.trust_level,
            is_fictional_demo=r.is_fictional_demo
        ))
    return out

@router.get("/lookup", response_model=RecipientResponse)
def lookup_recipient(
    q: str = Query(..., min_length=2, description="Lookup recipient by UPI ID or phone"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _limiter: bool = Depends(rate_limit("recipient_lookup", max_requests=20, window_seconds=60))
):
    """
    Search recipient using blind index lookup (never scans plaintext PII).
    Returns fictional recipient record or constructs an ad-hoc unverified recipient record for demo.
    """
    lookup_hash = encryption_service.blind_index(q)
    recipient = (
        db.query(Recipient)
        .filter(
            (Recipient.upi_id_lookup_hash == lookup_hash) |
            (Recipient.phone_lookup_hash == lookup_hash)
        )
        .first()
    )

    if recipient:
        dec = recipient.get_decrypted()
        return RecipientResponse(
            id=recipient.id,
            name=dec["name"],
            upi_id=dec["upi_id"],
            phone=dec["phone"],
            recipient_type=recipient.recipient_type,
            merchant_category=recipient.merchant_category,
            trust_level=recipient.trust_level,
            is_fictional_demo=recipient.is_fictional_demo
        )

    # If recipient not already saved in address book, provide formatted mock resolution
    clean_q = q.strip()
    return RecipientResponse(
        id=0,
        name=clean_q.split("@")[0].replace(".", " ").title(),
        upi_id=clean_q if "@" in clean_q else f"{clean_q}@simulated.upi",
        phone=clean_q if clean_q.isdigit() else None,
        recipient_type="P2P",
        merchant_category=None,
        trust_level="unknown",
        is_fictional_demo=True
    )
