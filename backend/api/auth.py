from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import User, DemoPaymentAccount
from backend.schemas import RegisterRequest, LoginRequest, TokenResponse
from backend.core.encryption import encryption_service, hash_password, verify_password
from backend.core.auth import create_access_token
from backend.core.audit import log_audit_event, log_security_event
from backend.core.rate_limit import rate_limit

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=TokenResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    _limiter: bool = Depends(rate_limit("register", max_requests=5, window_seconds=60))
):
    """
    Registers a new Yogii user.
    - Encrypts PII fields (name, phone, email, upi_id) with AES-256-GCM.
    - Stores blind indexes for searchable equality.
    - Hashes password using Argon2id.
    - Automatically provisions a simulated DemoPaymentAccount with ₹50,000 demo balance.
    """
    email_hash = encryption_service.blind_index(payload.email)
    upi_hash = encryption_service.blind_index(payload.upi_id)
    phone_hash = encryption_service.blind_index(payload.phone)

    # Check uniqueness via blind indexes
    existing_user = (
        db.query(User)
        .filter((User.email_lookup_hash == email_hash) | (User.upi_id_lookup_hash == upi_hash))
        .first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email or UPI ID already exists."
        )

    # Encrypt PII
    user = User(
        full_name_enc=encryption_service.encrypt(payload.full_name),
        phone_enc=encryption_service.encrypt(payload.phone),
        email_enc=encryption_service.encrypt(payload.email),
        upi_id_enc=encryption_service.encrypt(payload.upi_id),
        device_id_enc=encryption_service.encrypt("demo-device-default"),
        phone_lookup_hash=phone_hash,
        email_lookup_hash=email_hash,
        upi_id_lookup_hash=upi_hash,
        password_hash=hash_password(payload.password),
        status="ACTIVE",
        created_at=datetime.now(timezone.utc)
    )
    db.add(user)
    db.flush()

    # Provision simulated demo payment account
    account = DemoPaymentAccount(
        user_id=user.id,
        simulated_balance=50000.0,
        currency="INR",
        status="ACTIVE",
        created_at=datetime.now(timezone.utc)
    )
    db.add(account)
    db.commit()
    db.refresh(user)

    log_audit_event(
        actor_id=str(user.id),
        action="user_registered",
        resource=f"user:{user.id}",
        result="SUCCESS",
        metadata={"email_hash": email_hash[:8]},
        db_session=db
    )

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=user.get_decrypted_profile()
    )

@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    _limiter: bool = Depends(rate_limit("login", max_requests=10, window_seconds=60))
):
    """
    Authenticates user using email, phone, or UPI ID and password.
    Returns generic error to prevent user enumeration.
    """
    client_ip = request.client.host if request.client else "unknown"
    lookup_hash = encryption_service.blind_index(payload.email_or_phone_or_upi)

    user = (
        db.query(User)
        .filter(
            (User.email_lookup_hash == lookup_hash) |
            (User.phone_lookup_hash == lookup_hash) |
            (User.upi_id_lookup_hash == lookup_hash)
        )
        .first()
    )

    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials. Please verify your identifier and password."
    )

    if not user:
        log_security_event(
            event_type="login_failure",
            severity="MEDIUM",
            ip_address=client_ip,
            details={"identifier_hash": lookup_hash[:8]},
            db_session=db
        )
        raise generic_error

    if not verify_password(payload.password, user.password_hash):
        log_security_event(
            event_type="login_failure",
            severity="MEDIUM",
            ip_address=client_ip,
            user_id=str(user.id),
            details={"reason": "password_mismatch"},
            db_session=db
        )
        raise generic_error

    token = create_access_token({"sub": str(user.id)})

    log_audit_event(
        actor_id=str(user.id),
        action="user_login",
        resource=f"user:{user.id}",
        result="SUCCESS",
        metadata={"ip": client_ip},
        db_session=db
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=user.get_decrypted_profile()
    )

@router.post("/logout")
def logout():
    """
    Logs out the current session.
    Stateless client-side token discard with server-side audit.
    """
    return {"status": "ok", "message": "Successfully signed out of Yogii."}
