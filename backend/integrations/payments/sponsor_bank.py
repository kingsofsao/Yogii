"""Placeholder for a future sponsor-bank / UPI adapter. Deliberately unimplemented.

Yogii is not authorised to process real UPI payments. This adapter stays
unimplemented until an authorised sponsor bank or PSP provides its API
documentation, credentials, certificates and onboarding. When that happens:

* Implement `PaymentProvider` using only the bank's documented endpoints and
  message formats. Do not guess endpoints, field names or signing schemes.
* Let the bank/PSP's certified SDK or journey capture the UPI PIN and any
  step-up authentication. Yogii must never see, log or store a PIN or OTP.
* Verify every callback with the bank's specified mechanism (for example
  signatures or mutual TLS) before trusting it.
* Treat the bank's decision and the applicable UPI requirements as
  authoritative. Yogii's prototype risk policy cannot override them.
* Reject `simulated_outcome` on every request.

Constructing this class always raises, so a misconfigured deployment fails at
startup instead of silently falling back to simulation or to guesswork.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Mapping

from backend.integrations.payments.base import (
    CallbackEvent, PaymentInitiationRequest, PaymentProvider, ProviderNotConfiguredError,
    ProviderResult, ReversalResult, SettlementRecord,
)

_NOT_AVAILABLE = (
    "The sponsor-bank UPI adapter is not implemented. Real payments require an authorised "
    "sponsor bank / PSP, their documentation and credentials, onboarding, and the required "
    "testing and certification. Yogii currently runs in simulation only."
)


class SponsorBankUPIProvider(PaymentProvider):
    name = "SponsorBankUPIProvider"
    is_live = True

    def __init__(self, adapter_name: str = ""):
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)

    def initiate_payment(self, request: PaymentInitiationRequest) -> ProviderResult:  # pragma: no cover
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)

    def get_payment_status(self, provider_reference: str) -> ProviderResult:  # pragma: no cover
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)

    def verify_callback(self, headers: Mapping[str, str], body: bytes) -> CallbackEvent:  # pragma: no cover
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)

    def request_reversal(self, provider_reference: str, amount: Decimal, reason: str,
                         idempotency_key: str) -> ReversalResult:  # pragma: no cover
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)

    def get_reversal_status(self, reversal_reference: str) -> ReversalResult:  # pragma: no cover
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)

    def fetch_settlement_records(self, batch_date: str) -> List[SettlementRecord]:  # pragma: no cover
        raise ProviderNotConfiguredError(_NOT_AVAILABLE)
