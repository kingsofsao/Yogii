"""Payment orchestration: assess -> (verify) -> authorise -> provider -> ledger.

Invariants (all covered by tests):
* Every attempt is recorded with its risk assessment, model version, decision,
  reason codes, feature snapshot and a state-transition trail.
* BLOCKED and FAILED attempts never change a balance.
* Only a COMPLETED payment changes balances, and it does so exactly once:
  the `balance_applied` flag is checked and set in the same transaction as the
  debit, under row locks on PostgreSQL.
* Assessment is idempotent per (sender, Idempotency-Key); authorisation is
  idempotent per (sender, authorisation key).
* A status change reported by a provider is only trusted when it comes from
  `get_payment_status` or a verified, non-replayed callback.
* No PIN, OTP or password is ever accepted here.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Mapping, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.audit import log_audit_event, log_security_event
from backend.core.config import mode_label, settings
from backend.core.encryption import encryption_service
from backend.core.validation import InvalidInput, normalize_upi_id
from backend.database.database import as_utc, supports_row_locks
from backend.database.models import (
    DemoPaymentAccount, FeatureSnapshot, PaymentAttempt, PaymentStateTransition, ProviderCallbackEvent,
    RiskAssessment, TransactionGraphEdge, User, graph_node_for,
)
from backend.domain.payment_state import InvalidStateTransitionError, PaymentState, validate_state_transition
from backend.domain.risk_policy import RiskPolicy
from backend.integrations.payments import (
    CallbackVerificationError, PaymentInitiationRequest, PaymentProvider, ProviderError, ProviderStatus,
)
from backend.ml.feature_engine import FeatureEngine, ResolvedRecipient, hash_signal, resolve_recipient
from backend.ml.features import FEATURE_SCHEMA_VERSION
from backend.ml.inference import FraudInferenceService, inference_service

ASSESSMENT_VALID_FOR = timedelta(minutes=15)
SIMULATED_OUTCOMES = ("SUCCESS", "FAILURE", "PENDING")


class PaymentError(Exception):
    """A request that cannot be carried out. `status_code` maps it to HTTP."""

    def __init__(self, message: str, status_code: int = 400, code: str = "payment_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _mask_upi(upi: str) -> str:
    name, _, handle = upi.partition("@")
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}{'*' * max(2, len(name) - len(visible))}@{handle}"


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@dataclass
class RecipientView:
    name: str
    upi_id: str
    payment_type: str
    kind: str  # user, directory, unregistered


class PaymentService:
    def __init__(self, provider: PaymentProvider, inference: Optional[FraudInferenceService] = None,
                 feature_engine: Optional[FeatureEngine] = None, policy: Optional[RiskPolicy] = None,
                 clock: Optional[Callable[[], datetime]] = None):
        self.provider = provider
        self.inference = inference or inference_service
        self.features = feature_engine or FeatureEngine()
        self.policy = policy or RiskPolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------ helpers
    def now(self) -> datetime:
        return as_utc(self.clock())

    def _transition(self, db: Session, attempt: PaymentAttempt, to: PaymentState, reason: str, actor: str) -> None:
        try:
            validate_state_transition(attempt.state, to.value)
        except InvalidStateTransitionError as exc:
            raise PaymentError(str(exc), 409, "invalid_state")
        db.add(PaymentStateTransition(payment_attempt_id=attempt.id, from_state=attempt.state, to_state=to.value,
                                      reason=reason[:255], actor=actor, created_at=self.now()))
        attempt.state = to.value
        attempt.updated_at = self.now()

    def _lock(self, query):
        return query.with_for_update() if supports_row_locks() else query

    def _account(self, db: Session, user_id: int, lock: bool = False) -> Optional[DemoPaymentAccount]:
        q = db.query(DemoPaymentAccount).filter(DemoPaymentAccount.user_id == user_id)
        return (self._lock(q) if lock else q).first()

    def _get_owned(self, db: Session, payment_id: int, user_id: int, lock: bool = False) -> PaymentAttempt:
        q = db.query(PaymentAttempt).filter(PaymentAttempt.id == payment_id, PaymentAttempt.sender_user_id == user_id)
        attempt = (self._lock(q) if lock else q).first()
        if attempt is None:
            # Same response whether it does not exist or belongs to someone else.
            raise PaymentError("Payment not found.", 404, "not_found")
        return attempt

    def recipient_view(self, db: Session, upi_id: str) -> tuple[ResolvedRecipient, RecipientView]:
        upi = normalize_upi_id(upi_id)
        resolved = resolve_recipient(db, encryption_service.blind_index(upi))
        if resolved.user is not None:
            name = encryption_service.decrypt(resolved.user.full_name_enc)
        elif resolved.directory is not None:
            name = encryption_service.decrypt(resolved.directory.name_enc)
        else:
            name = "Unverified UPI ID"
        return resolved, RecipientView(name, upi, resolved.payment_type, resolved.kind)

    # ------------------------------------------------------------------ assess
    def assess(self, db: Session, sender: User, recipient_upi: str, amount, idempotency_key: str,
               note: str = "", simulated_device: str = "primary", simulated_location: str = "home",
               at: Optional[datetime] = None) -> PaymentAttempt:
        """Create an attempt and run the risk assessment. Idempotent per sender + key."""
        key = (idempotency_key or "").strip()
        if not 8 <= len(key) <= 100:
            raise PaymentError("An Idempotency-Key of 8-100 characters is required.", 400, "idempotency_key")
        existing = (db.query(PaymentAttempt)
                    .filter(PaymentAttempt.sender_user_id == sender.id, PaymentAttempt.idempotency_key == key).first())
        if existing:
            return existing

        try:
            resolved, view = self.recipient_view(db, recipient_upi)
        except InvalidInput as exc:
            raise PaymentError(str(exc), 422, "invalid_recipient")
        if resolved.user is not None and resolved.user.id == sender.id:
            raise PaymentError("You can't send money to yourself.", 422, "self_payment")
        amount = _money(amount)
        if amount <= 0 or amount > settings.MAX_PAYMENT_AMOUNT:
            raise PaymentError(f"Amount must be between ₹1 and ₹{settings.MAX_PAYMENT_AMOUNT:,} (simulation limit).",
                               422, "invalid_amount")
        account = self._account(db, sender.id)
        if account is None or account.status != "ACTIVE":
            raise PaymentError("No active simulated account.", 409, "no_account")
        if Decimal(account.simulated_balance) < amount:
            raise PaymentError("Not enough simulated balance for this amount.", 422, "insufficient_balance")

        at = as_utc(at) if at else self.now()
        device_hash = hash_signal("device", f"{sender.id}:{simulated_device or 'primary'}")
        location_hash = hash_signal("location", f"{sender.id}:{simulated_location or 'home'}")
        attempt = PaymentAttempt(
            reference=f"YOGII-{'SIM' if settings.is_simulation else 'LIVE'}-{uuid.uuid4().hex[:12].upper()}",
            mode=mode_label(), sender_account_id=account.id, sender_user_id=sender.id,
            recipient_id=resolved.directory.id if resolved.directory else None,
            recipient_user_id=resolved.user.id if resolved.user else None,
            recipient_upi_lookup_hash=resolved.upi_hash, recipient_upi_masked=_mask_upi(view.upi_id),
            recipient_upi_enc=encryption_service.encrypt(view.upi_id),
            recipient_name_enc=encryption_service.encrypt(view.name),
            payment_type=view.payment_type, amount=amount, currency="INR",
            note_enc=encryption_service.encrypt(note[:80]) if note else None,
            state=PaymentState.DRAFT.value, provider=self.provider.name, idempotency_key=key,
            device_hash=device_hash, location_hash=location_hash, created_at=at, updated_at=at,
        )
        db.add(attempt)
        try:
            db.flush()
        except IntegrityError:
            # A concurrent request with the same key won the race; return its attempt.
            db.rollback()
            return (db.query(PaymentAttempt)
                    .filter(PaymentAttempt.sender_user_id == sender.id, PaymentAttempt.idempotency_key == key).one())
        db.add(PaymentStateTransition(payment_attempt_id=attempt.id, from_state=None, to_state="DRAFT",
                                      reason="Payment details entered", actor=f"user:{sender.id}", created_at=at))
        self._transition(db, attempt, PaymentState.ASSESSING, "Risk assessment started", "system")

        features, graph, _ = self.features.build(db, sender, resolved, float(amount), at, device_hash,
                                                 location_hash, exclude_id=attempt.id)
        result = self.inference.predict(features)  # raises ModelNotAvailableError: no fallback
        decision = self.policy.decide(result.risk_score, [r["code"] for r in result.reason_codes])

        db.add(RiskAssessment(
            payment_attempt_id=attempt.id, risk_score=result.risk_score,
            raw_risk_score=Decimal(str(round(result.raw_probability * 100, 3))),
            calibrated_probability=Decimal(str(round(result.calibrated_probability, 5))),
            score_kind=result.score_kind, risk_band=decision.band, decision=decision.decision,
            reason_codes_json=json.dumps(result.reason_codes), model_version=result.model_version,
            policy_version=self.policy.version, thresholds_json=json.dumps(self.policy.thresholds),
            graph_depth=self.features.graph_depth, history_window_days=self.features.window_days, created_at=at,
        ))
        db.add(FeatureSnapshot(payment_attempt_id=attempt.id, feature_schema_version=FEATURE_SCHEMA_VERSION,
                               features_json=json.dumps({k: round(v, 5) for k, v in features.items()}),
                               created_at=at))
        attempt.decision = decision.decision
        if decision.blocked:
            attempt.failure_reason = "Blocked before authorisation by the Yogii prototype risk policy."
            self._transition(db, attempt, PaymentState.BLOCKED,
                             f"Risk {result.risk_score} ({decision.band}): blocked by prototype policy", "system")
            log_security_event("payment_blocked", "HIGH", user_id=str(sender.id),
                               details={"reference": attempt.reference, "risk_score": result.risk_score},
                               db_session=db)
        elif decision.requires_verification:
            self._transition(db, attempt, PaymentState.NEEDS_VERIFICATION,
                             f"Risk {result.risk_score} ({decision.band}): demo verification required", "system")
        else:
            db.add(PaymentStateTransition(payment_attempt_id=attempt.id, from_state="ASSESSING",
                                          to_state="ASSESSING", reason=f"Risk {result.risk_score} (LOW): ready",
                                          actor="system", created_at=at))
        log_audit_event(str(sender.id), "payment_assessed", f"payment:{attempt.reference}", attempt.state,
                        {"risk_score": result.risk_score, "band": decision.band,
                         "model_version": result.model_version}, db_session=db)
        db.commit()
        db.refresh(attempt)
        return attempt

    # ------------------------------------------------------------------ authorise
    def authorize(self, db: Session, sender: User, payment_id: int, authorization_key: str,
                  demo_verification_confirmed: bool = False, simulated_outcome: Optional[str] = None,
                  at: Optional[datetime] = None) -> PaymentAttempt:
        key = (authorization_key or "").strip()
        if not 8 <= len(key) <= 100:
            raise PaymentError("An Idempotency-Key of 8-100 characters is required.", 400, "idempotency_key")
        attempt = self._get_owned(db, payment_id, sender.id, lock=True)
        if attempt.authorization_idempotency_key:
            if attempt.authorization_idempotency_key == key:
                return attempt  # replay of the same authorisation: no second submission
            raise PaymentError("This payment has already been authorised.", 409, "already_authorized")
        if attempt.state == PaymentState.BLOCKED.value:
            raise PaymentError("This payment was blocked by the risk check and can't be authorised.", 409, "blocked")
        if attempt.state not in (PaymentState.ASSESSING.value, PaymentState.NEEDS_VERIFICATION.value):
            raise PaymentError(f"This payment is {attempt.state.lower()} and can't be authorised.", 409, "invalid_state")
        now = as_utc(at) if at else self.now()
        if now - as_utc(attempt.created_at) > ASSESSMENT_VALID_FOR:
            raise PaymentError("This risk assessment has expired. Start the payment again.", 409, "assessment_expired")
        if attempt.state == PaymentState.NEEDS_VERIFICATION.value:
            if not demo_verification_confirmed:
                raise PaymentError("Demo verification is required for this payment.", 422, "verification_required")
            attempt.verification_completed_at = now
            log_audit_event(str(sender.id), "demo_verification_completed", f"payment:{attempt.reference}",
                            "VERIFIED", db_session=db)

        outcome = None
        if simulated_outcome:
            if not settings.is_simulation:
                raise PaymentError("Simulated outcomes are not available in live mode.", 422, "not_simulation")
            outcome = simulated_outcome.upper()
            if outcome not in SIMULATED_OUTCOMES:
                raise PaymentError("simulated_outcome must be SUCCESS, FAILURE or PENDING.", 422, "invalid_outcome")
        attempt.simulated_outcome = outcome or ("SUCCESS" if settings.is_simulation else None)
        attempt.authorization_idempotency_key = key

        account = self._account(db, sender.id, lock=True)
        if Decimal(account.simulated_balance) < Decimal(attempt.amount):
            attempt.failure_reason = "Not enough simulated balance."
            self._transition(db, attempt, PaymentState.FAILED, "Insufficient simulated balance", "system")
            db.commit()
            return attempt

        upi = encryption_service.decrypt(attempt.recipient_upi_enc)
        try:
            result = self.provider.initiate_payment(PaymentInitiationRequest(
                payment_reference=attempt.reference, idempotency_key=f"{attempt.reference}:{key}",
                amount=Decimal(attempt.amount), currency=attempt.currency, payer_account_ref=str(account.id),
                payee_vpa=upi, payee_name=encryption_service.decrypt(attempt.recipient_name_enc),
                payment_type=attempt.payment_type, simulated_outcome=attempt.simulated_outcome,
            ))
        except ProviderError as exc:
            attempt.failure_reason = "The payment rail could not accept this payment."
            self._transition(db, attempt, PaymentState.FAILED, f"Provider error: {type(exc).__name__}", "provider")
            db.commit()
            return attempt

        attempt.provider_reference = result.provider_reference
        self._apply_provider_status(db, attempt, result.status, "provider", now,
                                    message=result.message)
        log_audit_event(str(sender.id), "payment_authorized", f"payment:{attempt.reference}", attempt.state,
                        {"provider": self.provider.name, "mode": attempt.mode}, db_session=db)
        db.commit()
        db.refresh(attempt)
        return attempt

    def cancel(self, db: Session, sender: User, payment_id: int) -> PaymentAttempt:
        attempt = self._get_owned(db, payment_id, sender.id, lock=True)
        if attempt.state not in (PaymentState.ASSESSING.value, PaymentState.NEEDS_VERIFICATION.value):
            raise PaymentError("Only a payment that hasn't been authorised can be cancelled.", 409, "invalid_state")
        attempt.failure_reason = "Cancelled by you before authorisation."
        self._transition(db, attempt, PaymentState.FAILED, "Cancelled by sender", f"user:{sender.id}")
        log_audit_event(str(sender.id), "payment_cancelled", f"payment:{attempt.reference}", "FAILED", db_session=db)
        db.commit()
        return attempt

    # ------------------------------------------------------------------ provider status
    def _apply_provider_status(self, db: Session, attempt: PaymentAttempt, status: ProviderStatus, actor: str,
                               at: datetime, message: str = "") -> bool:
        """Move the attempt according to an authoritative provider status. Returns True if it changed."""
        if status == ProviderStatus.SUCCESS:
            if attempt.state == PaymentState.COMPLETED.value:
                return False
            return self._complete(db, attempt, actor, at)
        if status == ProviderStatus.PENDING:
            if attempt.state in (PaymentState.ASSESSING.value, PaymentState.NEEDS_VERIFICATION.value):
                self._transition(db, attempt, PaymentState.PENDING, "Awaiting confirmation from the rail", actor)
                return True
            return False
        if status == ProviderStatus.FAILED:
            if attempt.state in (PaymentState.COMPLETED.value, PaymentState.FAILED.value, PaymentState.REVERSED.value):
                return False
            attempt.failure_reason = "The payment rail declined this payment." + (" (simulated)" if attempt.is_simulated else "")
            self._transition(db, attempt, PaymentState.FAILED, "Declined by the rail", actor)
            return True
        return False

    def _complete(self, db: Session, attempt: PaymentAttempt, actor: str, at: datetime) -> bool:
        """Apply the simulated ledger exactly once, in the caller's transaction."""
        if attempt.balance_applied:
            return False
        sender_acct = self._lock(db.query(DemoPaymentAccount).filter(
            DemoPaymentAccount.id == attempt.sender_account_id)).one()
        amount = Decimal(attempt.amount)
        if Decimal(sender_acct.simulated_balance) < amount:
            attempt.failure_reason = "Not enough simulated balance when the payment settled."
            self._transition(db, attempt, PaymentState.FAILED, "Insufficient simulated balance at settlement", actor)
            return True
        self._transition(db, attempt, PaymentState.COMPLETED, "Confirmed by the rail", actor)
        sender_acct.simulated_balance = Decimal(sender_acct.simulated_balance) - amount
        if attempt.recipient_user_id:
            recv = self._account(db, attempt.recipient_user_id, lock=True)
            if recv is not None:
                recv.simulated_balance = Decimal(recv.simulated_balance) + amount
        attempt.balance_applied = True
        attempt.completed_at = at
        sender = db.get(User, attempt.sender_user_id)
        db.add(TransactionGraphEdge(sender_node=sender.graph_node,
                                    receiver_node=graph_node_for(attempt.recipient_upi_lookup_hash),
                                    payment_id=attempt.id, amount=amount, payment_type=attempt.payment_type,
                                    timestamp=as_utc(attempt.created_at)))
        return True

    def refresh_status(self, db: Session, sender: User, payment_id: int) -> PaymentAttempt:
        """Status lookup. For PENDING payments, ask the rail for the authoritative status."""
        attempt = self._get_owned(db, payment_id, sender.id, lock=True)
        if attempt.state == PaymentState.PENDING.value and attempt.provider_reference:
            try:
                result = self.provider.get_payment_status(attempt.provider_reference)
            except ProviderError:
                return attempt
            if self._apply_provider_status(db, attempt, result.status, "provider:status_lookup", self.now()):
                log_audit_event(str(sender.id), "payment_status_updated", f"payment:{attempt.reference}",
                                attempt.state, db_session=db)
            db.commit()
        return attempt

    def reverse(self, db: Session, attempt: PaymentAttempt, reason: str, actor: str = "ops") -> PaymentAttempt:
        """Reverse a completed payment through the rail and undo the simulated ledger once."""
        if attempt.state != PaymentState.COMPLETED.value:
            raise PaymentError("Only completed payments can be reversed.", 409, "invalid_state")
        result = self.provider.request_reversal(attempt.provider_reference, Decimal(attempt.amount), reason,
                                                f"reverse:{attempt.reference}")
        if result.status.value != "COMPLETED":
            raise PaymentError("The reversal has not completed yet.", 409, "reversal_pending")
        self._transition(db, attempt, PaymentState.REVERSED, reason, actor)
        if attempt.balance_applied and not attempt.balance_reversed:
            amount = Decimal(attempt.amount)
            s = self._lock(db.query(DemoPaymentAccount).filter(DemoPaymentAccount.id == attempt.sender_account_id)).one()
            s.simulated_balance = Decimal(s.simulated_balance) + amount
            if attempt.recipient_user_id:
                r = self._account(db, attempt.recipient_user_id, lock=True)
                if r is not None:
                    r.simulated_balance = Decimal(r.simulated_balance) - amount
            attempt.balance_reversed = True
        db.commit()
        return attempt

    # ------------------------------------------------------------------ callbacks
    def handle_callback(self, db: Session, headers: Mapping[str, str], body: bytes) -> tuple[int, dict]:
        """Verify and apply a provider callback. Returns (http_status, body)."""
        digest = hashlib.sha256(body).hexdigest()
        record = ProviderCallbackEvent(provider=self.provider.name, payload_sha256=digest, received_at=self.now(),
                                       signature_valid=False, outcome="REJECTED")
        try:
            event = self.provider.verify_callback(headers, body)
        except CallbackVerificationError as exc:
            record.detail = str(exc)[:255]
            db.add(record)
            log_security_event("provider_callback_rejected", "HIGH", details={"reason": str(exc)}, db_session=db)
            db.commit()
            return 401, {"status": "rejected", "detail": "Callback verification failed."}

        if db.query(ProviderCallbackEvent).filter(ProviderCallbackEvent.provider == self.provider.name,
                                                  ProviderCallbackEvent.event_id == event.event_id).first():
            return 200, {"status": "duplicate"}
        record.signature_valid = True
        record.event_id = event.event_id
        record.provider_reference = event.provider_reference
        record.reported_status = event.status.value
        attempt = self._lock(db.query(PaymentAttempt).filter(
            PaymentAttempt.provider_reference == event.provider_reference)).first()
        if attempt is None:
            record.outcome, record.detail = "IGNORED", "Unknown provider reference"
        else:
            changed = self._apply_provider_status(db, attempt, event.status, "provider:callback", self.now())
            record.outcome = "APPLIED" if changed else "IGNORED"
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return 200, {"status": "duplicate"}
        return 200, {"status": record.outcome.lower()}
