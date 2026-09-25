import pytest
import uuid
from backend.database.database import SessionLocal, Base, engine
from backend.database.models import User, DemoPaymentAccount, PaymentAttempt
from backend.core.encryption import encryption_service, hash_password
from backend.domain.payment_service import PaymentService
from backend.domain.mock_provider import MockPaymentProvider
from backend.domain.payment_state import PaymentState

@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    # Create test user and demo account
    unique_id = uuid.uuid4().hex[:6]
    user = User(
        full_name_enc=encryption_service.encrypt("Test Invariant User"),
        phone_enc=encryption_service.encrypt("9999888877"),
        email_enc=encryption_service.encrypt(f"test_{unique_id}@test.com"),
        upi_id_enc=encryption_service.encrypt(f"test_{unique_id}@yogii"),
        phone_lookup_hash=encryption_service.blind_index("9999888877"),
        email_lookup_hash=encryption_service.blind_index(f"test_{unique_id}@test.com"),
        upi_id_lookup_hash=encryption_service.blind_index(f"test_{unique_id}@yogii"),
        password_hash=hash_password("Password123!"),
        status="ACTIVE"
    )
    session.add(user)
    session.flush()

    account = DemoPaymentAccount(
        user_id=user.id,
        simulated_balance=10000.0,
        currency="INR",
        status="ACTIVE"
    )
    session.add(account)
    session.commit()
    session.refresh(user)
    session.refresh(account)

    yield session, user, account
    session.close()

def test_completed_payment_debits_balance_exactly_once(db_session):
    session, user, account = db_session
    initial_balance = account.simulated_balance

    service = PaymentService(provider=MockPaymentProvider(default_outcome="SUCCESS"))
    key = str(uuid.uuid4())
    attempt = service.assess_and_create_attempt(
        db=session,
        sender_user_id=user.id,
        recipient_upi="familiar@upi",
        amount=500.0,
        idempotency_key=key
    )

    assert attempt.state == PaymentState.COMPLETED.value
    session.refresh(account)
    assert account.simulated_balance == initial_balance - 500.0

def test_blocked_payment_does_not_change_balance(db_session):
    session, user, account = db_session
    initial_balance = account.simulated_balance

    # Recipient with high-risk crypto keywords triggering very high risk
    service = PaymentService(provider=MockPaymentProvider())
    key = str(uuid.uuid4())
    attempt = service.assess_and_create_attempt(
        db=session,
        sender_user_id=user.id,
        recipient_upi="crypto_drain@drainer.unknown",
        amount=9500.0,  # 95% of entire balance in one shot
        idempotency_key=key,
        device_id="untrusted-device-vpn",
        location="UnknownCountry"
    )

    # Invariant: If blocked, state must be BLOCKED and balance must NOT change
    if attempt.state == PaymentState.BLOCKED.value:
        session.refresh(account)
        assert account.simulated_balance == initial_balance

def test_failed_payment_does_not_change_balance(db_session):
    session, user, account = db_session
    initial_balance = account.simulated_balance

    # Forced failure via provider
    service = PaymentService(provider=MockPaymentProvider(default_outcome="FAILURE"))
    key = str(uuid.uuid4())
    attempt = service.assess_and_create_attempt(
        db=session,
        sender_user_id=user.id,
        recipient_upi="merchant@fail.demo",
        amount=1200.0,
        idempotency_key=key
    )

    assert attempt.state == PaymentState.FAILED.value
    session.refresh(account)
    assert account.simulated_balance == initial_balance

def test_duplicate_idempotency_key_does_not_debit_twice(db_session):
    session, user, account = db_session
    initial_balance = account.simulated_balance

    service = PaymentService(provider=MockPaymentProvider(default_outcome="SUCCESS"))
    key = "IDEMPOTENT-KEY-" + uuid.uuid4().hex

    attempt1 = service.assess_and_create_attempt(
        db=session,
        sender_user_id=user.id,
        recipient_upi="familiar@upi",
        amount=750.0,
        idempotency_key=key
    )
    session.refresh(account)
    balance_after_first = account.simulated_balance
    assert balance_after_first == initial_balance - 750.0

    # Second call with the same idempotency key (simulating retry)
    attempt2 = service.assess_and_create_attempt(
        db=session,
        sender_user_id=user.id,
        recipient_upi="familiar@upi",
        amount=750.0,
        idempotency_key=key
    )

    assert attempt1.id == attempt2.id
    session.refresh(account)
    # INVARIANT: Balance must not be debited a second time!
    assert account.simulated_balance == balance_after_first
