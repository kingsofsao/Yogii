"""API request and response models.

Every request model forbids unknown fields and rejects any field that looks
like a UPI PIN, OTP, CVV, card number or bank password, wherever it appears.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core.validation import (
    InvalidInput, check_password_strength, contains_forbidden_secret, normalize_email, normalize_name,
    normalize_phone, normalize_upi_id,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_secrets(cls, values: Any) -> Any:
        key = contains_forbidden_secret(values)
        if key:
            raise ValueError(f"'{key}' must never be sent to Yogii. Yogii does not collect PINs, OTPs, "
                             "card details or bank passwords.")
        return values


def _wrap(fn, value):
    try:
        return fn(value)
    except InvalidInput as exc:
        raise ValueError(str(exc))


# ------------------------------------------------------------------ auth
class RegisterRequest(StrictRequest):
    full_name: str = Field(..., max_length=80)
    email: str = Field(..., max_length=254)
    phone: str = Field(..., max_length=16)
    upi_id: str = Field(..., max_length=60, description="Demo UPI ID ending in @yogii")
    password: str = Field(..., max_length=128)

    _name = field_validator("full_name")(classmethod(lambda cls, v: _wrap(normalize_name, v)))
    _email = field_validator("email")(classmethod(lambda cls, v: _wrap(normalize_email, v)))
    _phone = field_validator("phone")(classmethod(lambda cls, v: _wrap(normalize_phone, v)))
    _password = field_validator("password")(classmethod(lambda cls, v: _wrap(check_password_strength, v)))

    @field_validator("upi_id")
    @classmethod
    def _upi(cls, v: str) -> str:
        v = _wrap(normalize_upi_id, v)
        if not v.endswith("@yogii"):
            raise ValueError("Demo UPI IDs must end with @yogii.")
        return v


class LoginRequest(StrictRequest):
    identifier: str = Field(..., min_length=3, max_length=254, description="Email, mobile number or UPI ID")
    password: str = Field(..., min_length=1, max_length=128)


class UserProfile(BaseModel):
    id: int
    full_name: str
    email: str
    phone: str
    upi_id: str
    status: str
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class SessionResponse(BaseModel):
    user: UserProfile
    csrf_token: str
    expires_at: str
    mode: str


class MeResponse(UserProfile):
    simulated_balance: str
    currency: str = "INR"
    is_simulated: bool = True
    mode: str


# ------------------------------------------------------------------ recipients
class RecipientResponse(BaseModel):
    name: str
    upi_id: str
    payment_type: Literal["P2P", "P2M"]
    kind: Literal["yogii_user", "merchant", "contact", "unverified"]
    merchant_category: Optional[str] = None
    is_fictional_demo: bool = True
    notice: Optional[str] = None


# ------------------------------------------------------------------ payments
class SimulatedContext(StrictRequest):
    device: str = Field("primary", max_length=40, pattern=r"^[A-Za-z0-9 _.-]+$")
    location: str = Field("home", max_length=40, pattern=r"^[A-Za-z0-9 _.-]+$")


class AssessRequest(StrictRequest):
    recipient_upi: str = Field(..., max_length=60)
    amount: float = Field(..., gt=0)
    note: str = Field("", max_length=80)
    simulated_context: SimulatedContext = Field(default_factory=SimulatedContext)

    @field_validator("amount")
    @classmethod
    def _two_decimals(cls, v: float) -> float:
        if round(v, 2) != v:
            raise ValueError("Amount can have at most two decimal places.")
        return v


class AuthorizeRequest(StrictRequest):
    payment_id: int = Field(..., gt=0)
    demo_verification_confirmed: bool = False
    simulated_outcome: Optional[Literal["SUCCESS", "FAILURE", "PENDING"]] = None


class ReasonCode(BaseModel):
    code: str
    description: str


class RiskView(BaseModel):
    score: int
    band: str
    decision: str
    requires_verification: bool
    blocked: bool
    reason_codes: List[ReasonCode]
    score_kind: str
    model_version: str
    policy_version: str
    assessed_at: str


class TimelineEntry(BaseModel):
    state: str
    reason: Optional[str]
    at: str


class PaymentActions(BaseModel):
    can_authorize: bool
    needs_verification: bool
    can_cancel: bool
    can_refresh_status: bool


class PaymentRecipientView(BaseModel):
    name: str
    upi_id: str
    payment_type: str


class PaymentView(BaseModel):
    id: int
    reference: str
    mode: str
    is_simulated: bool
    direction: Literal["outgoing", "incoming"] = "outgoing"
    state: str
    amount: str
    currency: str
    recipient: PaymentRecipientView
    note: Optional[str] = None
    failure_reason: Optional[str] = None
    simulated_outcome: Optional[str] = None
    provider: str
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    risk: Optional[RiskView] = None
    actions: PaymentActions
    timeline: Optional[List[TimelineEntry]] = None


class IncomingView(BaseModel):
    id: int
    direction: Literal["incoming"] = "incoming"
    reference: str
    amount: str
    currency: str
    from_name: str
    state: str
    is_simulated: bool
    created_at: str


class PaymentListResponse(BaseModel):
    items: List[PaymentView]
    total: int
    limit: int
    offset: int


class PaymentStatusResponse(BaseModel):
    id: int
    reference: str
    state: str
    provider: str
    is_simulated: bool
    updated_at: str


# ------------------------------------------------------------------ dashboard / settings / model
class DashboardResponse(BaseModel):
    user: UserProfile
    simulated_balance: str
    currency: str
    mode: str
    is_simulated: bool
    notice: str
    stats: Dict[str, int]
    recent_payments: List[PaymentView]
    recent_incoming: List[IncomingView]
    hide_balance: bool


class PreferencesView(BaseModel):
    hide_balance: bool
    notify_on_high_risk: bool
    theme: Literal["system", "light", "dark"]


class SettingsResponse(BaseModel):
    mode: str
    live_payments_enabled: bool
    live_payments_note: str
    provider: str
    risk_policy_version: str
    risk_bands: Dict[str, str]
    thresholds_note: str
    max_payment_amount: int
    history_window_days: int
    graph_depth: int
    data_retention_days: Dict[str, int]
    preferences: PreferencesView


class UpdatePreferencesRequest(StrictRequest):
    hide_balance: Optional[bool] = None
    notify_on_high_risk: Optional[bool] = None
    theme: Optional[Literal["system", "light", "dark"]] = None


class SecurityEventView(BaseModel):
    event_type: str
    severity: str
    created_at: str


class ModelInfoResponse(BaseModel):
    model_version: str
    loaded: bool
    algorithm: Optional[str]
    training_date: Optional[str]
    score_kind: Optional[str]
    feature_schema_version: Optional[str]
    feature_columns: List[str]
    history_window_days: Optional[int]
    graph_depth: Optional[int]
    metrics: Dict[str, Any]
    feature_importance_gain: Dict[str, float]
    is_synthetic: bool
    risk_bands: Dict[str, str]
    disclaimer: str
