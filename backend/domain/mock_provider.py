import hmac
import hashlib
import json
import uuid
from typing import Dict, Any, Optional
from backend.domain.provider import PaymentProvider, ProviderResponse

class MockPaymentProvider(PaymentProvider):
    """
    Simulation payment provider rail for testing, verification, and demo execution.
    Supports deterministic controlled outcomes via special flags or recipient patterns.
    """

    WEBHOOK_SECRET = "mock-webhook-hmac-secret-dev"

    def __init__(self, default_outcome: str = "SUCCESS"):
        self.default_outcome = default_outcome  # "SUCCESS", "FAILURE", "PENDING"
        self._ledger: Dict[str, Dict[str, Any]] = {}

    def initiate_payment(
        self,
        payment_reference: str,
        amount: float,
        currency: str,
        sender_account_id: str,
        recipient_upi: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ProviderResponse:
        provider_ref = f"MOCK-TXN-{uuid.uuid4().hex[:12].upper()}"
        meta = metadata or {}

        # Allow deterministic testing overrides:
        # 1. via explicit forced_outcome in metadata
        # 2. via recipient suffix (e.g. "@fail.demo" or "@pending.demo")
        outcome = meta.get("forced_outcome") or self.default_outcome
        if "@fail" in recipient_upi.lower():
            outcome = "FAILURE"
        elif "@pending" in recipient_upi.lower():
            outcome = "PENDING"

        record = {
            "payment_reference": payment_reference,
            "provider_reference": provider_ref,
            "amount": amount,
            "currency": currency,
            "recipient_upi": recipient_upi,
            "status": outcome,
            "metadata": meta
        }
        self._ledger[provider_ref] = record

        if outcome == "SUCCESS":
            return ProviderResponse(
                success=True,
                status="SUCCESS",
                provider_reference=provider_ref,
                message="Simulated transaction completed successfully by MockPaymentProvider rail.",
                raw_payload=record
            )
        elif outcome == "PENDING":
            return ProviderResponse(
                success=True,
                status="PENDING",
                provider_reference=provider_ref,
                message="Simulated payment submitted to mock clearing rail, awaiting batch settlement.",
                raw_payload=record
            )
        else:
            return ProviderResponse(
                success=False,
                status="FAILED",
                provider_reference=provider_ref,
                message="Simulated transaction declined by mock destination banking switch.",
                raw_payload=record
            )

    def get_payment_status(self, provider_reference: str) -> ProviderResponse:
        record = self._ledger.get(provider_reference)
        if not record:
            return ProviderResponse(
                success=False,
                status="FAILED",
                provider_reference=provider_reference,
                message="Transaction not found in MockPaymentProvider ledger."
            )
        return ProviderResponse(
            success=record["status"] in ("SUCCESS", "PENDING"),
            status=record["status"],
            provider_reference=provider_reference,
            message=f"Status retrieved: {record['status']}",
            raw_payload=record
        )

    def generate_signed_callback_payload(self, provider_reference: str, status: str) -> Dict[str, Any]:
        """Utility for automated tests to simulate a signed webhook from the mock provider rail."""
        payload = {
            "provider_reference": provider_reference,
            "status": status,
            "event": "payment.status_update"
        }
        serialized = json.dumps(payload, sort_keys=True)
        sig = hmac.new(self.WEBHOOK_SECRET.encode("utf-8"), serialized.encode("utf-8"), hashlib.sha256).hexdigest()
        return {"payload": payload, "signature": sig}

    def verify_callback(self, payload: Dict[str, Any], signature: str) -> bool:
        serialized = json.dumps(payload, sort_keys=True)
        expected_sig = hmac.new(self.WEBHOOK_SECRET.encode("utf-8"), serialized.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, signature)

    def request_reversal(self, provider_reference: str, reason: str) -> ProviderResponse:
        reversal_ref = f"MOCK-REV-{uuid.uuid4().hex[:12].upper()}"
        if provider_reference in self._ledger:
            self._ledger[provider_reference]["status"] = "REVERSED"
        return ProviderResponse(
            success=True,
            status="SUCCESS",
            provider_reference=reversal_ref,
            message=f"Simulated reversal approved for reason: {reason}"
        )

    def get_reversal_status(self, reversal_reference: str) -> ProviderResponse:
        return ProviderResponse(
            success=True,
            status="SUCCESS",
            provider_reference=reversal_reference,
            message="Simulated reversal executed."
        )

    def reconcile(self, batch_date: str) -> Dict[str, Any]:
        return {
            "batch_date": batch_date,
            "total_records": len(self._ledger),
            "reconciled": True
        }
