"""Recipient lookup. Returns only what a sender needs to confirm who they are paying:
display name, UPI ID and whether it is a person or a merchant. Never the
receiver's history, balance or risk data."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.deps import user_rate_limit
from backend.core.encryption import encryption_service
from backend.core.validation import InvalidInput, normalize_recipient_query
from backend.database.database import get_db
from backend.database.models import PaymentAttempt, Recipient, User
from backend.schemas import RecipientResponse

router = APIRouter(prefix="/recipients", tags=["Recipients"])

UNVERIFIED_NOTICE = ("This UPI ID isn't in the Yogii demo directory, so we can't show a verified name. "
                     "Double-check it with the person you're paying.")


def _from_user(u: User) -> RecipientResponse:
    p = u.get_decrypted_profile()
    return RecipientResponse(name=p["full_name"], upi_id=p["upi_id"], payment_type="P2P", kind="yogii_user",
                             is_fictional_demo=u.is_fictional_demo)


def _from_directory(r: Recipient) -> RecipientResponse:
    d = r.get_decrypted()
    return RecipientResponse(name=d["name"], upi_id=d["upi_id"], payment_type=r.recipient_type,
                             kind="merchant" if r.recipient_type == "P2M" else "contact",
                             merchant_category=r.merchant_category, is_fictional_demo=r.is_fictional_demo)


@router.get("", response_model=List[RecipientResponse])
def list_recipients(user: User = Depends(user_rate_limit("recipients", 60, 60)), db: Session = Depends(get_db)):
    """Saved payees: people you have paid before, other demo users and demo merchants."""
    out, seen = [], set()
    paid = (db.query(PaymentAttempt.recipient_upi_lookup_hash)
            .filter(PaymentAttempt.sender_user_id == user.id, PaymentAttempt.state == "COMPLETED").distinct().all())
    paid_hashes = {h for (h,) in paid}
    for u in db.query(User).filter(User.id != user.id).all():
        if u.is_fictional_demo or u.upi_id_lookup_hash in paid_hashes:
            out.append(_from_user(u)); seen.add(u.upi_id_lookup_hash)
    for r in db.query(Recipient).filter(Recipient.on_watchlist.is_(False)).order_by(Recipient.id).all():
        if r.upi_id_lookup_hash not in seen:
            out.append(_from_directory(r)); seen.add(r.upi_id_lookup_hash)
    return out


@router.get("/lookup", response_model=RecipientResponse)
def lookup_recipient(q: str = Query(..., min_length=3, max_length=60, description="UPI ID or 10-digit mobile number"),
                     user: User = Depends(user_rate_limit("recipient_lookup", 30, 60)), db: Session = Depends(get_db)):
    try:
        kind, value = normalize_recipient_query(q)
    except InvalidInput as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    h = encryption_service.blind_index(value)
    if kind == "phone":
        u = db.query(User).filter(User.phone_lookup_hash == h).first()
        r = None if u else db.query(Recipient).filter(Recipient.phone_lookup_hash == h).first()
    else:
        u = db.query(User).filter(User.upi_id_lookup_hash == h).first()
        r = None if u else db.query(Recipient).filter(Recipient.upi_id_lookup_hash == h).first()
    if u is not None:
        if u.id == user.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That's your own UPI ID.")
        return _from_user(u)
    if r is not None:
        return _from_directory(r)
    if kind == "phone":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No demo payee uses this mobile number. Try their UPI ID.")
    return RecipientResponse(name="Unverified UPI ID", upi_id=value, payment_type="P2P", kind="unverified",
                             notice=UNVERIFIED_NOTICE)
