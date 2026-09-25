from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    upi_id = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=False)
    balance = Column(Float, default=25000.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Recipient(Base):
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True)
    upi_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    trust_level = Column(String, default="unknown")
    created_at = Column(DateTime, default=datetime.utcnow)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_upi = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    device_id = Column(String, default="demo-device")
    location = Column(String, default="Chennai")
    status = Column(String, nullable=False)  # SUCCESS / REVIEW / BLOCKED
    fraud_probability = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    decision = Column(String, nullable=False)
    reasons = Column(String, default="")

class FraudEvent(Base):
    __tablename__ = "fraud_events"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    risk_score = Column(Float, nullable=False)
    severity = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
