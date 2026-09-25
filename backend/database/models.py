import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, Index
)
from sqlalchemy.orm import relationship
from backend.database.database import Base
from backend.core.encryption import encryption_service

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    """
    User model storing zero plaintext reversible PII.
    Sensitive profile attributes are encrypted with AES-256-GCM.
    Equality lookups use HMAC-SHA-256 blind indexes.
    Passwords use Argon2id.
    NEVER stores UPI PIN, banking passwords, OTP, or CVV.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    
    # Encrypted fields (AES-256-GCM)
    full_name_enc = Column(Text, nullable=False)
    phone_enc = Column(Text, nullable=False)
    email_enc = Column(Text, nullable=False)
    upi_id_enc = Column(Text, nullable=False)
    device_id_enc = Column(Text, nullable=True)

    # Blind Indexes (HMAC-SHA-256 of normalized values)
    phone_lookup_hash = Column(String(64), index=True, nullable=False)
    email_lookup_hash = Column(String(64), index=True, nullable=False, unique=True)
    upi_id_lookup_hash = Column(String(64), index=True, nullable=False, unique=True)

    # Security
    password_hash = Column(String(255), nullable=False)
    key_version = Column(String(10), default="v1", nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False)  # ACTIVE, SUSPENDED, PENDING
    
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    accounts = relationship("DemoPaymentAccount", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("PaymentAttempt", back_populates="user")

    def get_decrypted_profile(self) -> dict:
        """Helper to decrypt user's own profile for authorized view."""
        return {
            "id": self.id,
            "full_name": encryption_service.decrypt(self.full_name_enc),
            "phone": encryption_service.decrypt(self.phone_enc),
            "email": encryption_service.decrypt(self.email_enc),
            "upi_id": encryption_service.decrypt(self.upi_id_enc),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class DemoPaymentAccount(Base):
    """
    Simulated demo account tracking strictly simulated balances.
    All payments are in SIMULATION MODE.
    """
    __tablename__ = "demo_payment_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_number_enc = Column(Text, nullable=True)
    simulated_balance = Column(Float, default=25000.0, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(String(20), default="ACTIVE", nullable=False)  # ACTIVE, FROZEN
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="accounts")
    payment_attempts = relationship("PaymentAttempt", back_populates="account")


class Recipient(Base):
    """
    Recipient information for demo contacts and simulated merchants.
    Sensitive identifiers are encrypted.
    """
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    name_enc = Column(Text, nullable=False)
    upi_id_enc = Column(Text, nullable=False)
    phone_enc = Column(Text, nullable=True)

    # Lookup hashes
    upi_id_lookup_hash = Column(String(64), index=True, nullable=False)
    phone_lookup_hash = Column(String(64), index=True, nullable=True)

    recipient_type = Column(String(20), default="P2P", nullable=False)  # P2P, P2M
    merchant_category = Column(String(50), nullable=True)  # e.g., 'Retail', 'Dining', 'Digital'
    trust_level = Column(String(20), default="unknown", nullable=False)  # 'trusted', 'neutral', 'suspicious'
    is_fictional_demo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    def get_decrypted(self) -> dict:
        return {
            "id": self.id,
            "name": encryption_service.decrypt(self.name_enc),
            "upi_id": encryption_service.decrypt(self.upi_id_enc),
            "phone": encryption_service.decrypt(self.phone_enc) if self.phone_enc else None,
            "recipient_type": self.recipient_type,
            "merchant_category": self.merchant_category,
            "trust_level": self.trust_level,
            "is_fictional_demo": self.is_fictional_demo
        }


class PaymentAttempt(Base):
    """
    Represents a payment attempt through Yogii's simulated rails.
    Enforces strict payment state machine and idempotency guarantees.
    """
    __tablename__ = "payment_attempts"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(50), unique=True, index=True, nullable=False)  # YOGII-SIM-XXXXXX
    sender_account_id = Column(Integer, ForeignKey("demo_payment_accounts.id"), nullable=False, index=True)
    sender_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("recipients.id"), nullable=True)

    # Search & display
    recipient_upi_lookup_hash = Column(String(64), index=True, nullable=False)
    recipient_upi_masked = Column(String(100), nullable=False)

    payment_type = Column(String(10), default="P2P", nullable=False)  # P2P, P2M
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)

    # State machine: DRAFT, ASSESSING, NEEDS_VERIFICATION, BLOCKED, PENDING, COMPLETED, FAILED, REVERSED
    state = Column(String(30), default="DRAFT", nullable=False, index=True)
    provider = Column(String(50), default="MockPaymentProvider", nullable=False)
    idempotency_key = Column(String(100), unique=True, index=True, nullable=False)
    failure_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    user = relationship("User", back_populates="payments")
    account = relationship("DemoPaymentAccount", back_populates="payment_attempts")
    recipient = relationship("Recipient")
    risk_assessment = relationship("RiskAssessment", back_populates="payment_attempt", uselist=False)
    feature_snapshot = relationship("FeatureSnapshot", back_populates="payment_attempt", uselist=False)


class RiskAssessment(Base):
    """
    Fraud risk scoring results produced by the XGBoost fraud pipeline.
    """
    __tablename__ = "risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    raw_risk_score = Column(Float, nullable=False)  # 0.0 - 100.0
    calibrated_probability = Column(Float, nullable=False)  # 0.0 - 1.0
    risk_band = Column(String(20), nullable=False)  # LOW, MEDIUM, HIGH, VERY_HIGH
    decision = Column(String(20), nullable=False)  # ALLOW, REVIEW, BLOCK
    reason_codes_json = Column(Text, nullable=False)  # JSON array of safe reason codes & descriptions
    model_version = Column(String(50), nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    payment_attempt = relationship("PaymentAttempt", back_populates="risk_assessment")


class FeatureSnapshot(Base):
    """
    Privacy-conscious snapshot of behavioral & network features evaluated at assessment time.
    Does NOT contain plaintext PII or authentication credentials.
    """
    __tablename__ = "feature_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id", ondelete="CASCADE"), unique=True, nullable=False)
    features_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    payment_attempt = relationship("PaymentAttempt", back_populates="feature_snapshot")


class TransactionGraphEdge(Base):
    """
    Directed transaction relationships for the NetworkX graph engine.
    Nodes represent users (e.g. 'user:1') and recipient endpoints (e.g. 'upi:rahul@upi').
    """
    __tablename__ = "transaction_graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    sender_node = Column(String(100), index=True, nullable=False)
    receiver_node = Column(String(100), index=True, nullable=False)
    payment_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=utc_now, nullable=False)


class ModelMetadata(Base):
    """
    Track versions, training runs, and evaluation metrics of the XGBoost fraud model.
    """
    __tablename__ = "model_metadata"

    id = Column(Integer, primary_key=True, index=True)
    model_version = Column(String(50), unique=True, nullable=False)
    training_date = Column(DateTime, default=utc_now, nullable=False)
    artifact_location = Column(String(255), nullable=False)
    metrics_json = Column(Text, nullable=False)
    feature_schema_version = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class SecurityEvent(Base):
    """
    Security events log (login attempts, suspicious requests, blocks, rate limits).
    """
    __tablename__ = "security_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String(50), index=True, nullable=False)
    severity = Column(String(20), nullable=False)
    ip_address = Column(String(45), nullable=False)
    user_id = Column(String(50), nullable=True, index=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class AuditEvent(Base):
    """
    Immutable compliance audit trail for high-impact actions.
    """
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id = Column(String(50), index=True, nullable=False)
    action = Column(String(50), index=True, nullable=False)
    resource = Column(String(100), nullable=False)
    result = Column(String(30), nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class AppConfiguration(Base):
    """
    Backend-controlled operational parameters.
    Never exposes internal secrets or fraud bypass rules to the public client.
    """
    __tablename__ = "app_configurations"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    is_secret = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
