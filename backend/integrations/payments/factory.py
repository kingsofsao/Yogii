"""Choose the payment provider from server-side configuration only."""

from __future__ import annotations

from typing import Optional

from backend.core.config import Settings, settings as default_settings
from backend.integrations.payments.base import PaymentProvider, ProviderNotConfiguredError
from backend.integrations.payments.mock import MockPaymentProvider
from backend.integrations.payments.sponsor_bank import SponsorBankUPIProvider


def build_payment_provider(cfg: Optional[Settings] = None) -> PaymentProvider:
    """Return the provider for this deployment.

    Simulation (the default) always gets the mock rail. Live mode needs both
    PAYMENT_MODE=live and LIVE_PAYMENTS_ENABLED=true in the server environment,
    plus a named adapter; even then it fails today because no authorised
    adapter exists. There is no fallback from live to simulation.
    """
    cfg = cfg or default_settings
    cfg.validate()
    if cfg.PAYMENT_MODE == "simulation":
        return MockPaymentProvider(cfg.MOCK_PROVIDER_WEBHOOK_SECRET, cfg.CALLBACK_TOLERANCE_SECONDS)
    if cfg.PAYMENT_MODE == "live" and cfg.LIVE_PAYMENTS_ENABLED and cfg.SPONSOR_BANK_ADAPTER:
        return SponsorBankUPIProvider(cfg.SPONSOR_BANK_ADAPTER)  # raises until implemented
    raise ProviderNotConfiguredError("Live payments are disabled for this deployment.")
