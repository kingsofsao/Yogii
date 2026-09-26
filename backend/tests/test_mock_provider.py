"""MockPaymentProvider: deterministic outcomes, status lookups, signed callbacks, reversals."""

import json
import time
from decimal import Decimal

import pytest

from backend.integrations.payments import (
    CallbackVerificationError, MockPaymentProvider, PaymentInitiationRequest, ProviderError, ProviderStatus,
)


@pytest.fixture
def provider():
    return MockPaymentProvider("test-secret-for-mock-provider", tolerance_seconds=300)


def request(outcome=None, key="idem-123456"):
    return PaymentInitiationRequest(payment_reference="YOGII-SIM-1", idempotency_key=key, amount=Decimal("500.00"),
                                    currency="INR", payer_account_ref="1", payee_vpa="rahul@upi",
                                    payee_name="Rahul", payment_type="P2P", simulated_outcome=outcome)


@pytest.mark.parametrize("outcome,status", [(None, ProviderStatus.SUCCESS), ("SUCCESS", ProviderStatus.SUCCESS),
                                            ("FAILURE", ProviderStatus.FAILED), ("PENDING", ProviderStatus.PENDING)])
def test_outcomes_are_deterministic(provider, outcome, status):
    r = provider.initiate_payment(request(outcome))
    assert r.status == status
    assert r.is_simulated is True
    assert provider.initiate_payment(request(outcome)).provider_reference == r.provider_reference


def test_pending_settles_on_status_lookup(provider):
    ref = provider.initiate_payment(request("PENDING")).provider_reference
    assert provider.get_payment_status(ref).status == ProviderStatus.SUCCESS
    # Status survives a "restart" because the outcome is encoded in the reference.
    assert MockPaymentProvider("test-secret-for-mock-provider").get_payment_status(ref).status == ProviderStatus.SUCCESS


def test_failed_status_and_unknown_reference(provider):
    ref = provider.initiate_payment(request("FAILURE")).provider_reference
    assert provider.get_payment_status(ref).status == ProviderStatus.FAILED
    with pytest.raises(ProviderError):
        provider.get_payment_status("BANK-123")


def test_unknown_outcome_rejected(provider):
    with pytest.raises(ProviderError):
        provider.initiate_payment(request("MAYBE"))


def _body(**kw):
    payload = {"event_id": "evt-1", "provider_reference": "MOCKP-ABC", "status": "SUCCESS", **kw}
    return json.dumps(payload).encode()


def test_signed_callback_verifies(provider):
    body = _body()
    event = provider.verify_callback(provider.sign_callback(body), body)
    assert event.event_id == "evt-1" and event.status == ProviderStatus.SUCCESS


def test_unsigned_tampered_and_stale_callbacks_rejected(provider):
    body = _body()
    with pytest.raises(CallbackVerificationError, match="Missing"):
        provider.verify_callback({}, body)
    headers = provider.sign_callback(body)
    with pytest.raises(CallbackVerificationError, match="does not match"):
        provider.verify_callback(headers, _body(status="FAILED"))
    with pytest.raises(CallbackVerificationError, match="window"):
        provider.verify_callback(provider.sign_callback(body, timestamp=int(time.time()) - 3600), body)
    other = MockPaymentProvider("a-different-secret-value")
    with pytest.raises(CallbackVerificationError):
        provider.verify_callback(other.sign_callback(body), body)
    with pytest.raises(CallbackVerificationError, match="Malformed"):
        provider.verify_callback({"X-Yogii-Mock-Signature": "garbage"}, body)
    bad = b"not json"
    with pytest.raises(CallbackVerificationError, match="valid status event"):
        provider.verify_callback(provider.sign_callback(bad), bad)


def test_reversal(provider):
    ref = provider.initiate_payment(request()).provider_reference
    rev = provider.request_reversal(ref, Decimal("500.00"), "customer dispute", "rev-key-1")
    assert rev.status.value == "COMPLETED"
    assert provider.get_reversal_status(rev.reversal_reference).status.value == "COMPLETED"
    assert provider.fetch_settlement_records("2026-01-01")[0].status == ProviderStatus.REVERSED
