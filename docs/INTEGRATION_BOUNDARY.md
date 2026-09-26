# Payment-rail integration boundary

Yogii can't move real money. This document describes the seam where an authorised sponsor-bank / UPI adapter could be added later, and the rules any such adapter must follow. Nothing here claims that Yogii is approved, certified or ready for live payments.

## Where the boundary is

```
frontend ──> /api/payments/assess ──> PaymentService.assess()   (features, model, prototype policy)
         ──> /api/payments         ──> PaymentService.authorize() ──> PaymentProvider.initiate_payment()
rail     ──> /api/integrations/payments/callback ──> PaymentProvider.verify_callback() ──> PaymentService
```

- `backend/integrations/payments/base.py`: the `PaymentProvider` interface and its typed request/response objects.
- `backend/integrations/payments/mock.py`: `MockPaymentProvider`, the only implementation.
- `backend/integrations/payments/sponsor_bank.py`: `SponsorBankUPIProvider`. It is **unimplemented**, and its constructor always raises `ProviderNotConfiguredError`.
- `backend/integrations/payments/factory.py`: picks the provider from server configuration only.

Nothing outside `backend/integrations/payments/` knows how a rail works. The payment service only sees `ProviderResult`, `CallbackEvent`, `ReversalResult` and `SettlementRecord`.

## The interface

| Method | Contract |
|---|---|
| `initiate_payment(PaymentInitiationRequest)` | Submits a payment. It must be idempotent on `idempotency_key`, so the same key always gives the same outcome and reference. Returns `SUCCESS`, `PENDING` or `FAILED` and a provider reference. |
| `get_payment_status(reference)` | The authoritative status lookup. Yogii only completes a `PENDING` payment after this method or a verified callback reports success. |
| `verify_callback(headers, body)` | Verifies the signature, freshness and schema, then returns a `CallbackEvent`. It must raise `CallbackVerificationError` for anything unsigned, stale, tampered or malformed. |
| `request_reversal(reference, amount, reason, key)` / `get_reversal_status(ref)` | Reversal or refund, and its status. |
| `fetch_settlement_records(date)` | The rail's settlement view of a day, used by `backend/domain/reconciliation.py`. |

`PaymentInitiationRequest` has no field for a PIN, OTP, password or card detail, and it never will. `simulated_outcome` exists only for the mock rail. A live adapter must reject any request that sets it, and the service already refuses it outside simulation.

## How live mode is controlled

Live mode needs **all** of these in the **server environment**:

1. `PAYMENT_MODE=live`
2. `LIVE_PAYMENTS_ENABLED=true`
3. `SPONSOR_BANK_ADAPTER=<name>`
4. `APP_ENV=production`, together with every production safety check in `Settings.validate()`

Even then, `build_payment_provider()` constructs `SponsorBankUPIProvider`, which raises. The API therefore **refuses to start**, and nothing falls back to simulation.

- **Users can't enable it.** `PATCH /api/settings` accepts personal preferences only and rejects unknown fields.
- **The database can't enable it.** No `app_configurations` row is ever read for the payment mode.

The tests `backend/tests/test_config_and_boundary.py` pin all of this down.

## Callbacks

- **Endpoint:** `POST /api/integrations/payments/callback` (server to server, rate-limited, 16 KB maximum).
- **Mock rail signature:** `X-Yogii-Mock-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "<t>.<raw body>">`, keyed with `MOCK_PROVIDER_WEBHOOK_SECRET`. It is valid for 5 minutes.
- **Recording:** every callback is stored in `provider_callback_events` with a SHA-256 of the payload:
  - rejected callbacks are stored with `signature_valid=false`;
  - replays are recognised by `(provider, event_id)` and ignored.
- **Effect on balances:** a verified callback can only move a payment through legal transitions, and the ledger is applied at most once (`balance_applied`).

## What a real sponsor-bank adapter must do

Only when an authorised sponsor bank or PSP has provided documentation, credentials and onboarding:

- **Use only documented APIs.** Implement `PaymentProvider` using the bank's documented endpoints, message formats and signing or mTLS requirements. Do not guess any of them.
- **Keep credentials out of the code.** Load them from a secrets manager, never from source or `.env` files in the repository.
- **Let the bank authenticate the payer.** The bank or PSP's certified SDK or journey collects the UPI PIN and any step-up authentication. Yogii must never see, log or store the PIN or an OTP.
- **Let the bank decide.** The sponsor bank's approved risk policy and the applicable UPI requirements are **authoritative**. Yogii's prototype policy may add friction before submission, but it must never approve anything the bank declines or treat its own score as a bank decision.
- **Verify every callback** using the bank's mechanism. Reject everything else.
- **Reconcile** against the bank's settlement files. Investigate mismatches; never auto-correct balances.
- **Complete certification first.** Pass the bank's sandbox and certification testing and any required audits before enabling live traffic.
- **Get independent review.** Have an independent legal, compliance and security review of the whole system. The controls in this repository do not, by themselves, make it compliant.
