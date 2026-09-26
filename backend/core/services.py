"""Process-wide service wiring, built once at startup from server configuration."""

from __future__ import annotations

from typing import Optional

from backend.domain.payment_service import PaymentService
from backend.integrations.payments import PaymentProvider, build_payment_provider

_provider: Optional[PaymentProvider] = None
_payment_service: Optional[PaymentService] = None


def init_services(provider: Optional[PaymentProvider] = None) -> PaymentService:
    """Build the provider (fails closed on unsafe config) and the payment service."""
    global _provider, _payment_service
    _provider = provider or build_payment_provider()
    _payment_service = PaymentService(_provider)
    return _payment_service


def get_payment_service() -> PaymentService:
    if _payment_service is None:
        return init_services()
    return _payment_service


def get_provider() -> PaymentProvider:
    get_payment_service()
    return _provider
