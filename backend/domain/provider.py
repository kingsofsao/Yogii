from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ProviderResponse:
    def __init__(
        self,
        success: bool,
        status: str,  # "SUCCESS", "PENDING", "FAILED"
        provider_reference: str,
        message: str = "",
        raw_payload: Optional[Dict[str, Any]] = None
    ):
        self.success = success
        self.status = status
        self.provider_reference = provider_reference
        self.message = message
        self.raw_payload = raw_payload or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "provider_reference": self.provider_reference,
            "message": self.message,
            "raw_payload": self.raw_payload
        }

class PaymentProvider(ABC):
    """
    Abstract interface for payment rails.
    Decouples the core payment domain from external provider implementations.
    """

    @abstractmethod
    def initiate_payment(
        self,
        payment_reference: str,
        amount: float,
        currency: str,
        sender_account_id: str,
        recipient_upi: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ProviderResponse:
        """Initiate payment execution with the provider rail."""
        pass

    @abstractmethod
    def get_payment_status(self, provider_reference: str) -> ProviderResponse:
        """Query real-time payment status from provider rail."""
        pass

    @abstractmethod
    def verify_callback(self, payload: Dict[str, Any], signature: str) -> bool:
        """Verify the cryptographic signature of an incoming webhook/callback."""
        pass

    @abstractmethod
    def request_reversal(self, provider_reference: str, reason: str) -> ProviderResponse:
        """Request transaction reversal / refund."""
        pass

    @abstractmethod
    def get_reversal_status(self, reversal_reference: str) -> ProviderResponse:
        """Query reversal status."""
        pass

    @abstractmethod
    def reconcile(self, batch_date: str) -> Dict[str, Any]:
        """Perform batch reconciliation report."""
        pass
