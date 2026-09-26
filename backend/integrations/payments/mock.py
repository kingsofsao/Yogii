"""MockPaymentProvider: the simulated rail used whenever live mode is off.

It never contacts a bank, NPCI, UPI or payment gateway. Outcomes are
deterministic, which makes demos and tests reproducible:

* The tester picks SUCCESS, FAILURE or PENDING on the payment screen.
* A PENDING payment settles to SUCCESS on its first status lookup (a stand-in
  for the bank confirming later). The outcome is encoded in the reference, so
  status lookups keep working after a server restart.
* Callbacks are HMAC-SHA256 signed over "<timestamp>.<raw body>" with a server
  secret, like most real webhook schemes. Unsigned, stale or tampered callbacks
  are rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Mapping, Optional

from backend.integrations.payments.base import (
    CallbackEvent, CallbackVerificationError, PaymentInitiationRequest, PaymentProvider,
    ProviderError, ProviderResult, ProviderStatus, ReversalResult, ReversalStatus, SettlementRecord,
)

SIGNATURE_HEADER = "x-yogii-mock-signature"
_OUTCOME_PREFIX = {"SUCCESS": "MOCKS", "FAILURE": "MOCKF", "PENDING": "MOCKP"}
_PREFIX_STATUS = {"MOCKS": ProviderStatus.SUCCESS, "MOCKF": ProviderStatus.FAILED, "MOCKP": ProviderStatus.PENDING}


def _ref_digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16].upper()


class MockPaymentProvider(PaymentProvider):
    name = "MockPaymentProvider"
    is_live = False

    def __init__(self, webhook_secret: str, tolerance_seconds: int = 300):
        if not webhook_secret:
            raise ValueError("MockPaymentProvider needs a webhook secret for callback signing.")
        self._secret = webhook_secret.encode()
        self._tolerance = tolerance_seconds
        self._ledger: Dict[str, SettlementRecord] = {}
        self._settled_pending: set = set()
        self._reversals: Dict[str, ReversalResult] = {}

    # -- payments --------------------------------------------------------------
    def initiate_payment(self, request: PaymentInitiationRequest) -> ProviderResult:
        outcome = (request.simulated_outcome or "SUCCESS").upper()
        if outcome not in _OUTCOME_PREFIX:
            raise ProviderError(f"Unknown simulated outcome '{outcome}'.")
        # Same idempotency key -> same reference -> same outcome.
        ref = f"{_OUTCOME_PREFIX[outcome]}-{_ref_digest(request.idempotency_key, request.payment_reference)}"
        status = _PREFIX_STATUS[ref[:5]]
        self._ledger[ref] = SettlementRecord(ref, status, request.amount)
        message = {
            ProviderStatus.SUCCESS: "Simulated payment completed by the mock rail.",
            ProviderStatus.FAILED: "Simulated payment declined by the mock rail.",
            ProviderStatus.PENDING: "Simulated payment is pending at the mock rail.",
        }[status]
        return ProviderResult(status, ref, message, is_simulated=True)

    def get_payment_status(self, provider_reference: str) -> ProviderResult:
        prefix = provider_reference[:5]
        if prefix not in _PREFIX_STATUS or not provider_reference.startswith(prefix + "-"):
            raise ProviderError("Unknown provider reference.")
        status = _PREFIX_STATUS[prefix]
        if status == ProviderStatus.PENDING:
            # The simulated bank confirms a pending payment on the first lookup.
            status = ProviderStatus.SUCCESS
            self._settled_pending.add(provider_reference)
            if provider_reference in self._ledger:
                old = self._ledger[provider_reference]
                self._ledger[provider_reference] = SettlementRecord(provider_reference, status, old.amount)
        return ProviderResult(status, provider_reference, f"Simulated status: {status.value}.", is_simulated=True)

    # -- callbacks -------------------------------------------------------------
    def sign_callback(self, body: bytes, timestamp: Optional[int] = None) -> Dict[str, str]:
        """Build the signature header a simulated bank would send (used by tests and demos)."""
        ts = int(timestamp if timestamp is not None else time.time())
        sig = hmac.new(self._secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        return {SIGNATURE_HEADER: f"t={ts},v1={sig}"}

    def verify_callback(self, headers: Mapping[str, str], body: bytes) -> CallbackEvent:
        lowered = {k.lower(): v for k, v in headers.items()}
        header = lowered.get(SIGNATURE_HEADER)
        if not header:
            raise CallbackVerificationError("Missing callback signature.")
        try:
            parts = dict(item.split("=", 1) for item in header.split(","))
            ts = int(parts["t"])
            received = parts["v1"]
        except (ValueError, KeyError):
            raise CallbackVerificationError("Malformed callback signature header.")
        if abs(time.time() - ts) > self._tolerance:
            raise CallbackVerificationError("Callback timestamp outside the allowed window.")
        expected = hmac.new(self._secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise CallbackVerificationError("Callback signature does not match.")
        try:
            payload = json.loads(body.decode("utf-8"))
            status = ProviderStatus(payload["status"])
            event_id = str(payload["event_id"])
            reference = str(payload["provider_reference"])
        except (ValueError, KeyError, UnicodeDecodeError):
            raise CallbackVerificationError("Callback body is not a valid status event.")
        if not event_id or not reference:
            raise CallbackVerificationError("Callback is missing identifiers.")
        return CallbackEvent(event_id, reference, status, datetime.fromtimestamp(ts, timezone.utc), payload)

    # -- reversals and reconciliation --------------------------------------------
    def request_reversal(self, provider_reference: str, amount: Decimal, reason: str,
                         idempotency_key: str) -> ReversalResult:
        rev_ref = f"MOCKR-{_ref_digest(idempotency_key, provider_reference)}"
        result = ReversalResult(rev_ref, provider_reference, ReversalStatus.COMPLETED,
                                "Simulated reversal completed by the mock rail.")
        self._reversals[rev_ref] = result
        if provider_reference in self._ledger:
            self._ledger[provider_reference] = SettlementRecord(provider_reference, ProviderStatus.REVERSED, amount)
        return result

    def get_reversal_status(self, reversal_reference: str) -> ReversalResult:
        if reversal_reference in self._reversals:
            return self._reversals[reversal_reference]
        if reversal_reference.startswith("MOCKR-"):
            return ReversalResult(reversal_reference, "", ReversalStatus.COMPLETED, "Simulated reversal completed.")
        raise ProviderError("Unknown reversal reference.")

    def fetch_settlement_records(self, batch_date: str) -> List[SettlementRecord]:
        # The mock keeps its ledger in memory only; reconciliation therefore falls
        # back to per-payment status lookups (see backend/domain/reconciliation.py).
        return list(self._ledger.values())
