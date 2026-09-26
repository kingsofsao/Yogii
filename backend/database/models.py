"""SQLAlchemy models for Yogii.

Privacy rules applied throughout:
* Personal identifiers (name, email, phone, UPI ID) are stored encrypted with
  AES-256-GCM. Equality lookups use keyed HMAC "blind indexes".
* Graph nodes and device/location signals are keyed hashes, never plaintext.
* No UPI PIN, OTP, bank password or card detail is ever stored. There is no
  column for one.
* Every money value is NUMERIC(14, 2) and every balance, account and payment
  in this build is SIMULATED.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.core.encryption import encryption_service
from backend.database.database import Base

Money = Numeric(14, 2, asdecimal=True)


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # Encrypted fields (AES-256-GCM)
    full_name_enc = Column(Text, nullable=False)
    phone_enc = Column(Text, nullable=False)
    email_enc = Column(Text, nullable=False)
    upi_id_enc = Column(Text, nullable=False)
    device_id_enc = Column(Text, nullable=True)

    # Blind indexes (HMAC-SHA-256 of normalised values)
    phone_lookup_hash = Column(String(64), index=True, nullable=False, unique=True)
    email_lookup_hash = Column(String(64), index=True, nullable=False, unique=True)
    upi_id_lookup_hash = Column(String(64), index=True, nullable=False, unique=True)

    password_hash = Column(String(255), nullable=False)
    key_version = Column(String(10), default="v1", nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False)  # ACTIVE, SUSPENDED
    # Incremented on "sign out everywhere"; tokens carrying an older value are rejected.
    token_version = Column(Integer, default=0, nullable=False)
    is_fictional_demo = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    accounts = relationship("DemoPaymentAccount", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("PaymentAttempt", back_populates="user", foreign_keys="PaymentAttempt.sender_user_id")
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")

    def get_decrypted_profile(self) -> dict:
        return {
            "id": self.id,
            "full_name": encryption_service.decrypt(self.full_name_enc),
            "phone": encryption_service.decrypt(self.phone_enc),
            "email": encryption_service.decrypt(self.email_enc),
            "upi_id": encryption_service.decrypt(self.upi_id_enc),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @property
    def graph_node(self) -> str:
        return graph_node_for(self.upi_id_lookup_hash)


def graph_node_for(upi_lookup_hash: str) -> str:
    """Transaction-graph node id for a UPI ID: a truncated keyed hash, never plaintext."""
    return f"acct:{upi_lookup_hash[:24]}"


class DemoPaymentAccount(Base):
    """A SIMULATED account. The balance is demo money, not a bank balance."""
    __tablename__ = "demo_payment_accounts"
    __table_args__ = (CheckConstraint("simulated_balance >= 0", name="ck_demo_account_balance_nonnegative"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_number_enc = Column(Text, nullable=True)
    simulated_balance = Column(Money, default=0, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(String(20), default="ACTIVE", nullable=False)  # ACTIVE, FROZEN
    is_simulated = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="accounts")
    payment_attempts = relationship("PaymentAttempt", back_populates="account")


class Recipient(Base):
    """Directory of fictional demo payees (people and merchants) that are not Yogii users."""
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    name_enc = Column(Text, nullable=False)
    upi_id_enc = Column(Text, nullable=False)
    phone_enc = Column(Text, nullable=True)

    upi_id_lookup_hash = Column(String(64), index=True, nullable=False, unique=True)
    phone_lookup_hash = Column(String(64), index=True, nullable=True)

    recipient_type = Column(String(20), default="P2P", nullable=False)  # P2P, P2M
    merchant_category = Column(String(50), nullable=True)
    trust_level = Column(String(20), default="unknown", nullable=False)  # informational only
    # Demo watchlist (stand-in for a bank's negative list). Used as a model feature.
    on_watchlist = Column(Boolean, default=False, nullable=False)
    is_fictional_demo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    def get_decrypted(self) -> dict:
        return {
            "id": self.id,
            "name": encryption_service.decrypt(self.name_enc),
            "upi_id": encryption_service.decrypt(self.upi_id_enc),
            "phone": encryption_service.decrypt(self.phone_enc) if self.phone_enc else None,
            "recipient_type": self.recipient_type,
            "merchant_category": self.merchant_category,
            "is_fictional_demo": self.is_fictional_demo,
        }


class PaymentAttempt(Base):
    """Every attempt is recorded, including blocked, cancelled and failed ones."""
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint("sender_user_id", "idempotency_key", name="uq_payment_sender_idempotency"),
        UniqueConstraint("sender_user_id", "authorization_idempotency_key", name="uq_payment_sender_auth_idempotency"),
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        Index("ix_payment_sender_created", "sender_user_id", "created_at"),
        Index("ix_payment_recipient_created", "recipient_upi_lookup_hash", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(50), unique=True, index=True, nullable=False)  # YOGII-SIM-XXXX
    mode = Column(String(12), default="SIMULATION", nullable=False)
    sender_account_id = Column(Integer, ForeignKey("demo_payment_accounts.id"), nullable=False, index=True)
    sender_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=True)
    recipient_user_id = Column(Integer, ForeignKey("users.id", name="fk_payment_recipient_user"), nullable=True, index=True)

    recipient_upi_lookup_hash = Column(String(64), index=True, nullable=False)
    recipient_upi_masked = Column(String(100), nullable=False)
    recipient_upi_enc = Column(Text, nullable=True)
    recipient_name_enc = Column(Text, nullable=True)

    payment_type = Column(String(10), default="P2P", nullable=False)  # P2P, P2M
    amount = Column(Money, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    note_enc = Column(Text, nullable=True)

    # DRAFT, ASSESSING, NEEDS_VERIFICATION, BLOCKED, PENDING, COMPLETED, FAILED, REVERSED
    state = Column(String(30), default="DRAFT", nullable=False, index=True)
    decision = Column(String(20), nullable=True)  # ALLOW, VERIFY, BLOCK (prototype policy)
    provider = Column(String(50), default="MockPaymentProvider", nullable=False)
    provider_reference = Column(String(80), unique=True, nullable=True, index=True)
    idempotency_key = Column(String(100), index=True, nullable=False)
    authorization_idempotency_key = Column(String(100), nullable=True)
    simulated_outcome = Column(String(10), nullable=True)  # SUCCESS, FAILURE, PENDING (demo only)
    verification_completed_at = Column(DateTime(timezone=True), nullable=True)
    # Exactly-once guards for the simulated ledger.
    balance_applied = Column(Boolean, default=False, nullable=False)
    balance_reversed = Column(Boolean, default=False, nullable=False)
    failure_reason = Column(Text, nullable=True)

    # Simulated context signals, stored only as keyed hashes (never raw device ids).
    device_hash = Column(String(64), nullable=True)
    location_hash = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="payments", foreign_keys=[sender_user_id])
    account = relationship("DemoPaymentAccount", back_populates="payment_attempts")
    recipient = relationship("Recipient")
    risk_assessment = relationship("RiskAssessment", back_populates="payment_attempt", uselist=False,
                                   cascade="all, delete-orphan")
    feature_snapshot = relationship("FeatureSnapshot", back_populates="payment_attempt", uselist=False,
                                    cascade="all, delete-orphan")
    transitions = relationship("PaymentStateTransition", back_populates="payment_attempt",
                               order_by="PaymentStateTransition.id", cascade="all, delete-orphan")

    @property
    def is_simulated(self) -> bool:
        return self.mode == "SIMULATION"


class PaymentStateTransition(Base):
    """Append-only audit trail of every state change of a payment attempt."""
    __tablename__ = "payment_state_transitions"

    id = Column(Integer, primary_key=True)
    payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id", ondelete="CASCADE", name="fk_transition_payment"),
                                nullable=False, index=True)
    from_state = Column(String(30), nullable=True)
    to_state = Column(String(30), nullable=False)
    reason = Column(String(255), nullable=True)
    actor = Column(String(50), nullable=False)  # user:<id>, system, provider
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    payment_attempt = relationship("PaymentAttempt", back_populates="transitions")


class RiskAssessment(Base):
    """Output of the fraud-risk pipeline for one attempt. Signals, not verdicts."""
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id", ondelete="CASCADE"), unique=True, nullable=False)

    risk_score = Column(Integer, nullable=False)                    # 0-100, from the calibrated probability
    raw_risk_score = Column(Numeric(7, 3), nullable=False)          # uncalibrated model output x 100
    calibrated_probability = Column(Numeric(7, 5), nullable=False)  # isotonic-calibrated on synthetic data
    score_kind = Column(String(40), nullable=False, default="calibrated_probability_synthetic")
    risk_band = Column(String(20), nullable=False)                   # LOW, MEDIUM, HIGH, VERY_HIGH
    decision = Column(String(20), nullable=False)                    # ALLOW, VERIFY, BLOCK
    reason_codes_json = Column(Text, nullable=False)
    model_version = Column(String(50), nullable=False)
    policy_version = Column(String(50), nullable=False, default="yogii-prototype-policy-v1")
    thresholds_json = Column(Text, nullable=False, default="{}")
    graph_depth = Column(Integer, nullable=False, default=2)
    history_window_days = Column(Integer, nullable=False, default=30)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    payment_attempt = relationship("PaymentAttempt", back_populates="risk_assessment")


class FeatureSnapshot(Base):
    """Model inputs at assessment time. Numeric signals only: no PII, no credentials."""
    __tablename__ = "feature_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id", ondelete="CASCADE"), unique=True, nullable=False)
    feature_schema_version = Column(String(20), nullable=False, default="v2")
    features_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    payment_attempt = relationship("PaymentAttempt", back_populates="feature_snapshot")


class TransactionGraphEdge(Base):
    """Directed edge per completed simulated payment. Nodes are keyed hashes of UPI IDs."""
    __tablename__ = "transaction_graph_edges"
    __table_args__ = (
        Index("ix_graph_receiver_time", "receiver_node", "timestamp"),
        Index("ix_graph_sender_time", "sender_node", "timestamp"),
        UniqueConstraint("payment_id", name="uq_graph_edge_payment"),
    )

    id = Column(Integer, primary_key=True, index=True)
    sender_node = Column(String(100), index=True, nullable=False)
    receiver_node = Column(String(100), index=True, nullable=False)
    payment_id = Column(Integer, ForeignKey("payment_attempts.id", ondelete="CASCADE", name="fk_graph_edge_payment"),
                        nullable=False)
    amount = Column(Money, nullable=False)
    payment_type = Column(String(10), default="P2P", nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class ProviderCallbackEvent(Base):
    """Every callback received from a payment rail, verified or not, for audit and replay protection."""
    __tablename__ = "provider_callback_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_provider_callback_event"),)

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), nullable=False)
    event_id = Column(String(100), nullable=True)
    provider_reference = Column(String(80), nullable=True, index=True)
    reported_status = Column(String(20), nullable=True)
    signature_valid = Column(Boolean, nullable=False, default=False)
    outcome = Column(String(30), nullable=False)  # APPLIED, IGNORED, REJECTED, DUPLICATE
    detail = Column(String(255), nullable=True)
    payload_sha256 = Column(String(64), nullable=False)
    received_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserPreference(Base):
    """Per-user security and privacy preferences. None of these can enable live payments."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE", name="fk_user_preferences_user"),
                     nullable=False, unique=True)
    hide_balance = Column(Boolean, default=False, nullable=False)
    notify_on_high_risk = Column(Boolean, default=True, nullable=False)
    theme = Column(String(10), default="system", nullable=False)  # system, light, dark
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="preferences")


class ModelMetadata(Base):
    __tablename__ = "model_metadata"

    id = Column(Integer, primary_key=True, index=True)
    model_version = Column(String(50), unique=True, nullable=False)
    training_date = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    artifact_location = Column(String(255), nullable=False)
    metrics_json = Column(Text, nullable=False)
    feature_schema_version = Column(String(20), nullable=False)
    is_synthetic = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String(50), index=True, nullable=False)
    severity = Column(String(20), nullable=False)
    ip_address = Column(String(45), nullable=False)
    user_id = Column(String(50), nullable=True, index=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id = Column(String(50), index=True, nullable=False)
    action = Column(String(50), index=True, nullable=False)
    resource = Column(String(100), nullable=False)
    result = Column(String(30), nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class AppConfiguration(Base):
    """Non-secret operational metadata (for example the active policy version).

    This table is informational. It is never consulted for the payment mode or
    the live-payment flag, which come only from the server environment.
    """
    __tablename__ = "app_configurations"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    is_secret = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
