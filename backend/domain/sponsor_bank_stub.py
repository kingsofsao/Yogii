from typing import Dict, Any, Optional
from backend.domain.provider import PaymentProvider, ProviderResponse

class SponsorBankNotConfiguredError(RuntimeError):
    """
    Raised when live UPI processing is attempted without an authorized sponsor-bank onboarding.
    """
    pass

class SponsorBankUPIProvider(PaymentProvider):
    """
    STUB: SponsorBankUPIProvider.
    
    IMPORTANT NOTICE & COMPLIANCE ARCHITECTURE:
    --------------------------------------------
    Yogii currently operates exclusively in SIMULATION MODE.
    
    Processing real UPI payments requires:
    1. Direct commercial partnership with an RBI-regulated Sponsor Bank (e.g., ICICI, Axis, HDFC, SBI).
    2. NPCI (National Payments Corporation of India) TPAP (Third-Party Application Provider) registration.
    3. Formal PSP (Payment Service Provider) technical onboarding & API documentation.
    4. Compliance with RBI circulars on data localization and storage of payment system data.
    5. Cert-In security audit, tokenization certification, and end-to-end sandbox sign-off.
    
    To maintain regulatory compliance and safety, this adapter remains an uninstantiable stub.
    Under NO circumstances should mock credentials or speculative bank endpoints be invented.
    """

    def __init__(self, *args, **kwargs):
        raise SponsorBankNotConfiguredError(
            "SponsorBankUPIProvider is currently an uninstantiated stub. "
            "Real UPI processing requires NPCI TPAP approval, Sponsor-Bank onboarding, "
            "and bank-certified PSP infrastructure. Use MockPaymentProvider instead."
        )

    def initiate_payment(self, *args, **kwargs) -> ProviderResponse:
        raise SponsorBankNotConfiguredError("Live bank payments are not enabled.")

    def get_payment_status(self, *args, **kwargs) -> ProviderResponse:
        raise SponsorBankNotConfiguredError("Live bank payments are not enabled.")

    def verify_callback(self, *args, **kwargs) -> bool:
        raise SponsorBankNotConfiguredError("Live bank payments are not enabled.")

    def request_reversal(self, *args, **kwargs) -> ProviderResponse:
        raise SponsorBankNotConfiguredError("Live bank payments are not enabled.")

    def get_reversal_status(self, *args, **kwargs) -> ProviderResponse:
        raise SponsorBankNotConfiguredError("Live bank payments are not enabled.")

    def reconcile(self, *args, **kwargs) -> Dict[str, Any]:
        raise SponsorBankNotConfiguredError("Live bank payments are not enabled.")
