from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr, model_validator

# --- Auth Schemas ---
class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(..., pattern=r"^[0-9]{10,15}$")
    upi_id: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @model_validator(mode="before")
    def reject_forbidden_secrets(cls, values: Any) -> Any:
        if isinstance(values, dict):
            forbidden = {"pin", "upi_pin", "otp", "cvv", "bank_password", "card_pin"}
            for key in values.keys():
                if key.lower() in forbidden:
                    raise ValueError(f"Forbidden security credential '{key}' must never be submitted to Yogii.")
        return values

class LoginRequest(BaseModel):
    email_or_phone_or_upi: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)

    @model_validator(mode="before")
    def reject_forbidden_secrets(cls, values: Any) -> Any:
        if isinstance(values, dict):
            forbidden = {"pin", "upi_pin", "otp", "cvv", "bank_password", "card_pin"}
            for key in values.keys():
                if key.lower() in forbidden:
                    raise ValueError(f"Forbidden security credential '{key}' must never be submitted to Yogii.")
        return values

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class UserProfileResponse(BaseModel):
    id: int
    full_name: str
    phone: str
    email: str
    upi_id: str
    status: str
    simulated_balance: float
    currency: str = "INR"
    is_simulated_environment: bool = True
    created_at: Optional[str] = None

# --- Recipient Schemas ---
class RecipientResponse(BaseModel):
    id: int
    name: str
    upi_id: str
    phone: Optional[str] = None
    recipient_type: str  # P2P, P2M
    merchant_category: Optional[str] = None
    trust_level: str
    is_fictional_demo: bool = True

class RecipientLookupQuery(BaseModel):
    query: str = Field(..., min_length=2)

# --- Payment Schemas ---
class PaymentAssessRequest(BaseModel):
    recipient_upi: str = Field(..., min_length=3)
    amount: float = Field(..., gt=0, le=100000)
    idempotency_key: str = Field(..., min_length=8)
    payment_type: str = Field(default="P2P")
    device_id: Optional[str] = "demo-device"
    location: Optional[str] = "Chennai"

    @model_validator(mode="before")
    def reject_forbidden_secrets(cls, values: Any) -> Any:
        if isinstance(values, dict):
            forbidden = {"pin", "upi_pin", "otp", "cvv", "bank_password", "card_pin"}
            for key in values.keys():
                if key.lower() in forbidden:
                    raise ValueError(f"Forbidden security credential '{key}' must never be submitted to Yogii.")
        return values

class PaymentVerifyRequest(BaseModel):
    demo_verification_confirmed: bool = Field(...)

    @model_validator(mode="before")
    def reject_forbidden_secrets(cls, values: Any) -> Any:
        if isinstance(values, dict):
            forbidden = {"pin", "upi_pin", "otp", "cvv", "bank_password", "card_pin"}
            for key in values.keys():
                if key.lower() in forbidden:
                    raise ValueError(f"Forbidden security credential '{key}' must never be submitted to Yogii.")
        return values

class ReasonCodeItem(BaseModel):
    code: str
    description: str

class RiskAssessmentResponse(BaseModel):
    raw_risk_score: float
    calibrated_probability: float
    risk_band: str  # LOW, MEDIUM, HIGH, VERY_HIGH
    decision: str   # ALLOW, REVIEW, BLOCK
    reason_codes: List[ReasonCodeItem]
    model_version: str

class PaymentAttemptResponse(BaseModel):
    id: int
    reference: str
    sender_user_id: int
    recipient_upi: str
    amount: float
    currency: str = "INR"
    state: str
    provider: str
    idempotency_key: str
    failure_reason: Optional[str] = None
    risk_assessment: Optional[RiskAssessmentResponse] = None
    is_simulated: bool = True
    created_at: str
    updated_at: str

# --- Dashboard & Info Schemas ---
class DashboardSummaryResponse(BaseModel):
    user: UserProfileResponse
    simulated_balance: float
    currency: str = "INR"
    is_simulation_mode: bool = True
    disclaimer: str
    stats: Dict[str, Any]
    recent_payments: List[PaymentAttemptResponse]
    recipients: List[RecipientResponse]

class ModelInfoResponse(BaseModel):
    model_version: str
    algorithm: str
    training_date: Optional[str] = None
    metrics: Dict[str, Any]
    feature_schema_version: str
    feature_columns: List[str]
    is_synthetic: bool = True
    disclaimer: str

class AppSettingsResponse(BaseModel):
    payment_mode: str
    live_upi_enabled: bool
    risk_thresholds: Dict[str, Any]
    max_payment_limit: float
    environment: str
