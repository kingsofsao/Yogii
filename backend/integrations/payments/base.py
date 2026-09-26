"""The boundary between Yogii and whoever actually moves money.

Today the only implementation is `MockPaymentProvider` (simulation). A future
sponsor-bank / UPI adapter must implement this same interface, using only the
bank's documented APIs, credentials and authentication journey. The UPI PIN is
captured by the bank/PSP's certified component, never by Yogii, so nothing in
this interface carries a PIN, OTP, password or card detail.

In live mode the sponsor bank and the applicable UPI rules decide the outcome.
Yogii's prototype risk policy may add friction (warn, verify or stop before
submission), but it cannot override a bank decline, and a bank approval is only
trusted when it arrives through `get_payment_status` or a verified callback.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional


class ProviderStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    UNKNOWN = "UNKNOWN"


class ReversalStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ProviderError(RuntimeError):
    """A provider call could not be completed (network, validation, unknown reference)."""


class CallbackVerificationError(ProviderError):
    """An incoming callback failed signature, freshness or format checks. Never trust it."""


class ProviderNotConfiguredError(ProviderError):
    """Live payments were requested but no authorised adapter is available."""


@dataclass(frozen=True)
class PaymentInitiationRequest:
    payment_reference: str          # Yogii's own reference, unique per attempt
    idempotency_key: str            # stable across retries of the same attempt
    amount: Decimal
    currency: str
    payer_account_ref: str          # opaque Yogii account id, never a bank credential
    payee_vpa: str                  # UPI ID (virtual payment address) of the payee
    payee_name: str
    payment_type: str               # "P2P" or "P2M"
    note: str = ""
    # Simulation only: the demo outcome chosen by the tester. Live adapters must
    # reject any request that sets it.
    simulated_outcome: Optional[str] = None


@dataclass(frozen=True)
class ProviderResult:
    status: ProviderStatus
    provider_reference: str
    message: str
    is_simulated: bool
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallbackEvent:
    """A status update that has passed signature and freshness verification."""
    event_id: str
    provider_reference: str
    status: ProviderStatus
    occurred_at: datetime
    raw: Dict[str, Any]


@dataclass(frozen=True)
class ReversalResult:
    reversal_reference: str
    provider_reference: str
    status: ReversalStatus
    message: str


@dataclass(frozen=True)
class SettlementRecord:
    provider_reference: str
    status: ProviderStatus
    amount: Decimal


class PaymentProvider(abc.ABC):
    """Interface every payment rail must implement."""

    name: str = "abstract"
    is_live: bool = False

    @abc.abstractmethod
    def initiate_payment(self, request: PaymentInitiationRequest) -> ProviderResult:
        """Submit a payment. Must be idempotent on `request.idempotency_key`."""

    @abc.abstractmethod
    def get_payment_status(self, provider_reference: str) -> ProviderResult:
        """Look up the authoritative status of a submitted payment."""

    @abc.abstractmethod
    def verify_callback(self, headers: Mapping[str, str], body: bytes) -> CallbackEvent:
        """Verify an incoming status callback (signature, timestamp, schema) and parse it.

        Must raise CallbackVerificationError for anything unsigned, stale or malformed.
        """

    @abc.abstractmethod
    def request_reversal(self, provider_reference: str, amount: Decimal, reason: str,
                         idempotency_key: str) -> ReversalResult:
        """Ask the rail to reverse or refund a completed payment."""

    @abc.abstractmethod
    def get_reversal_status(self, reversal_reference: str) -> ReversalResult:
        """Look up the status of a reversal / refund request."""

    @abc.abstractmethod
    def fetch_settlement_records(self, batch_date: str) -> List[SettlementRecord]:
        """Return the rail's settlement records for a day, used for reconciliation."""
