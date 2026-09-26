from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.api.presenters import user_profile
from backend.core.audit import log_audit_event, log_security_event
from backend.core.auth import clear_session_cookies, create_session_token, set_session_cookies
from backend.core.config import mode_label, settings
from backend.core.encryption import (
    DUMMY_PASSWORD_HASH, encryption_service, hash_password, password_needs_rehash, verify_password,
)
from backend.core.rate_limit import (
    clear_login_failures, client_ip, login_locked, rate_limit, record_login_failure,
)
from backend.core.validation import InvalidInput, normalize_email, normalize_phone, normalize_upi_id
from backend.database.database import get_db
from backend.database.models import DemoPaymentAccount, User, UserPreference
from backend.schemas import LoginRequest, RegisterRequest, SessionResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

GENERIC_LOGIN_ERROR = "The details you entered don't match an account. Check them and try again."


def _start_session(response: Response, user: User) -> SessionResponse:
    token, csrf, expires = create_session_token(user.id, user.token_version)
    set_session_cookies(response, token, csrf, expires)
    return SessionResponse(user=user_profile(user), csrf_token=csrf, expires_at=expires.isoformat(),
                           mode=mode_label())


def _identifier_hash(identifier: str) -> str:
    """Normalise email / phone / UPI ID the same way registration did, then blind-index it."""
    raw = identifier.strip()
    for fn in (normalize_upi_id, normalize_email, normalize_phone) if "@" in raw else (normalize_phone,):
        try:
            return encryption_service.blind_index(fn(raw))
        except InvalidInput:
            continue
    return encryption_service.blind_index(raw.lower())


@router.post("/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("register", 5, 60))])
def register(payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Create a demo user with a SIMULATED account and starting demo balance."""
    hashes = {k: encryption_service.blind_index(getattr(payload, k)) for k in ("email", "phone", "upi_id")}
    conflict = db.query(User).filter(
        (User.email_lookup_hash == hashes["email"]) | (User.phone_lookup_hash == hashes["phone"])
        | (User.upi_id_lookup_hash == hashes["upi_id"])).first()
    if conflict:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "An account already uses this email, mobile number or UPI ID.")
    now = datetime.now(timezone.utc)
    user = User(full_name_enc=encryption_service.encrypt(payload.full_name),
                phone_enc=encryption_service.encrypt(payload.phone),
                email_enc=encryption_service.encrypt(payload.email),
                upi_id_enc=encryption_service.encrypt(payload.upi_id),
                phone_lookup_hash=hashes["phone"], email_lookup_hash=hashes["email"],
                upi_id_lookup_hash=hashes["upi_id"], password_hash=hash_password(payload.password),
                status="ACTIVE", created_at=now, last_login_at=now)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already uses this email, mobile number or UPI ID.")
    db.add(DemoPaymentAccount(user_id=user.id, simulated_balance=Decimal(settings.DEMO_STARTING_BALANCE),
                              currency="INR", status="ACTIVE", is_simulated=True, created_at=now))
    db.add(UserPreference(user_id=user.id))
    log_audit_event(str(user.id), "user_registered", f"user:{user.id}", "SUCCESS", db_session=db)
    db.commit()
    return _start_session(response, user)


@router.post("/login", response_model=SessionResponse, dependencies=[Depends(rate_limit("login", 10, 60))])
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Sign in with email, mobile number or UPI ID. Errors never reveal which part was wrong."""
    ip = client_ip(request)
    ident = _identifier_hash(payload.identifier)
    if login_locked(ident):
        log_security_event("login_locked", "MEDIUM", ip_address=ip, details={"id": ident[:8]}, db_session=db)
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many failed sign-in attempts. Try again in a few minutes.")
    user = db.query(User).filter((User.email_lookup_hash == ident) | (User.phone_lookup_hash == ident)
                                 | (User.upi_id_lookup_hash == ident)).first()
    # Verify against a dummy hash when the user doesn't exist, so timing doesn't leak it.
    ok = verify_password(payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not ok or user.status != "ACTIVE":
        record_login_failure(ident)
        log_security_event("login_failure", "MEDIUM", ip_address=ip, user_id=str(user.id) if user else None,
                           details={"id": ident[:8]}, db_session=db)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)
    clear_login_failures(ident)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = datetime.now(timezone.utc)
    log_audit_event(str(user.id), "user_login", f"user:{user.id}", "SUCCESS", {"ip": ip}, db_session=db)
    db.commit()
    return _start_session(response, user)


@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user)):
    """End this browser's session."""
    clear_session_cookies(response)
    return {"status": "signed_out"}


@router.post("/logout-all")
def logout_all(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """End every session for this account by bumping the token version."""
    user.token_version += 1
    log_audit_event(str(user.id), "sessions_revoked", f"user:{user.id}", "SUCCESS", db_session=db)
    db.commit()
    clear_session_cookies(response)
    return {"status": "signed_out_everywhere"}
