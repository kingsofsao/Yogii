"""Payment rail boundary: interface, simulated rail, and the (unimplemented) sponsor-bank adapter."""

from backend.integrations.payments.base import (  # noqa: F401
    CallbackEvent, CallbackVerificationError, PaymentInitiationRequest, PaymentProvider, ProviderError,
    ProviderNotConfiguredError, ProviderResult, ProviderStatus, ReversalResult, ReversalStatus, SettlementRecord,
)
from backend.integrations.payments.factory import build_payment_provider  # noqa: F401
from backend.integrations.payments.mock import MockPaymentProvider  # noqa: F401
