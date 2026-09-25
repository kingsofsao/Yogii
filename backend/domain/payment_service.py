import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database.models import (
    PaymentAttempt, RiskAssessment, FeatureSnapshot, DemoPaymentAccount,
    Recipient, TransactionGraphEdge, User
)
from backend.domain.payment_state import (
    PaymentState, validate_state_transition, InvalidStateTransitionError
)
from backend.domain.mock_provider import MockPaymentProvider
from backend.domain.provider import PaymentProvider
from backend.ml.feature_engine import FeatureEngine
from backend.ml.inference import inference_service
from backend.core.audit import log_audit_event, log_security_event
from backend.core.encryption import encryption_service
from backend.core.config import settings

class PaymentExecutionError(Exception):
    pass

class PaymentService:
    def __init__(
        self,
        provider: Optional[PaymentProvider] = None,
        feature_engine: Optional[FeatureEngine] = None
    ):
        self.provider = provider or MockPaymentProvider()
        self.feature_engine = feature_engine or FeatureEngine()

    def assess_and_create_attempt(
        self,
        db: Session,
        sender_user_id: int,
        recipient_upi: str,
        amount: float,
        idempotency_key: str,
        payment_type: str = "P2P",
        device_id: str = "demo-device",
        location: str = "Chennai"
    ) -> PaymentAttempt:
        """
        Idempotent payment creation and initial fraud risk assessment.
        Ensures idempotency, runs feature engineering, XGBoost inference,
        and sets initial state (ASSESSING -> LOW/NEEDS_VERIFICATION/BLOCKED).
        """
        # 1. Idempotency Check: if key already exists, return existing attempt
        existing_attempt = (
            db.query(PaymentAttempt)
            .filter(PaymentAttempt.idempotency_key == idempotency_key)
            .first()
        )
        if existing_attempt:
            return existing_attempt

        # 2. Check Sender Account and Balance
        account = (
            db.query(DemoPaymentAccount)
            .filter(DemoPaymentAccount.user_id == sender_user_id)
            .first()
        )
        if not account:
            raise PaymentExecutionError("No active demo payment account found for user.")

        if amount <= 0:
            raise PaymentExecutionError("Payment amount must be greater than zero.")

        if account.simulated_balance < amount:
            raise PaymentExecutionError(
                f"Insufficient simulated balance. Current: ₹{account.simulated_balance:,.2f}, Requested: ₹{amount:,.2f}"
            )

        # 3. Blind index for recipient lookup
        recip_lookup_hash = encryption_service.blind_index(recipient_upi)
        recipient = (
            db.query(Recipient)
            .filter(Recipient.upi_id_lookup_hash == recip_lookup_hash)
            .first()
        )

        reference = f"YOGII-SIM-{uuid.uuid4().hex[:10].upper()}"

        # 4. Create initial PaymentAttempt in DRAFT state
        attempt = PaymentAttempt(
            reference=reference,
            sender_account_id=account.id,
            sender_user_id=sender_user_id,
            recipient_id=recipient.id if recipient else None,
            recipient_upi_lookup_hash=recip_lookup_hash,
            recipient_upi_masked=recipient_upi if len(recipient_upi) < 8 else f"{recipient_upi[:3]}***{recipient_upi[-6:]}",
            payment_type=payment_type,
            amount=amount,
            currency="INR",
            state=PaymentState.DRAFT.value,
            provider="MockPaymentProvider",
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc)
        )
        db.add(attempt)
        db.flush()

        # 5. Transition to ASSESSING
        validate_state_transition(attempt.state, PaymentState.ASSESSING.value)
        attempt.state = PaymentState.ASSESSING.value
        db.flush()

        # 6. Extract features through Feature Engine
        features = self.feature_engine.build_features(
            db=db,
            sender_user_id=sender_user_id,
            recipient_lookup_hash=recip_lookup_hash,
            amount=amount,
            timestamp=attempt.created_at,
            device_id=device_id,
            location=location
        )

        # 7. Execute XGBoost model inference
        risk_score, prob, risk_band, decision, reason_codes = inference_service.predict(features)

        # 8. Record Risk Assessment and Feature Snapshot
        risk_record = RiskAssessment(
            payment_attempt_id=attempt.id,
            raw_risk_score=risk_score,
            calibrated_probability=prob,
            risk_band=risk_band,
            decision=decision,
            reason_codes_json=json.dumps(reason_codes),
            model_version=settings.MODEL_VERSION,
            created_at=datetime.now(timezone.utc)
        )
        db.add(risk_record)

        snapshot = FeatureSnapshot(
            payment_attempt_id=attempt.id,
            features_json=json.dumps(features),
            created_at=datetime.now(timezone.utc)
        )
        db.add(snapshot)

        # 9. Transition State based on Risk Decision Policy
        if risk_band == "VERY_HIGH" or decision == "BLOCK":
            validate_state_transition(attempt.state, PaymentState.BLOCKED.value)
            attempt.state = PaymentState.BLOCKED.value
            attempt.failure_reason = "Payment blocked by Yogii prototype risk policy threshold (Risk Score >= 85)."
            log_security_event(
                event_type="payment_block",
                severity="HIGH",
                user_id=str(sender_user_id),
                details={"reference": reference, "risk_score": risk_score, "risk_band": risk_band},
                db_session=db
            )
        elif risk_band in ("MEDIUM", "HIGH") or decision == "REVIEW":
            validate_state_transition(attempt.state, PaymentState.NEEDS_VERIFICATION.value)
            attempt.state = PaymentState.NEEDS_VERIFICATION.value
        else:
            # LOW risk (0-29): Ready to execute immediately through mock rail
            attempt = self._execute_provider_payment(db, attempt, account, recipient_upi)

        log_audit_event(
            actor_id=str(sender_user_id),
            action="payment_assessed",
            resource=f"payment:{attempt.reference}",
            result=attempt.state,
            metadata={"amount": amount, "risk_score": risk_score, "risk_band": risk_band},
            db_session=db
        )

        db.commit()
        db.refresh(attempt)
        return attempt

    def verify_and_continue_payment(
        self,
        db: Session,
        payment_id: int,
        sender_user_id: int,
        demo_verification_confirmed: bool
    ) -> PaymentAttempt:
        """
        Handles explicit Demo Verification for MEDIUM and HIGH risk transactions.
        NEVER collects or requests UPI PIN, OTP, or banking passwords.
        """
        attempt = (
            db.query(PaymentAttempt)
            .filter(PaymentAttempt.id == payment_id, PaymentAttempt.sender_user_id == sender_user_id)
            .first()
        )
        if not attempt:
            raise PaymentExecutionError("Payment attempt not found.")

        if attempt.state != PaymentState.NEEDS_VERIFICATION.value:
            raise PaymentExecutionError(f"Payment is in state '{attempt.state}', not awaiting demo verification.")

        if not demo_verification_confirmed:
            raise PaymentExecutionError("Demo verification confirmation is required to proceed.")

        account = (
            db.query(DemoPaymentAccount)
            .filter(DemoPaymentAccount.id == attempt.sender_account_id)
            .first()
        )
        if not account:
            raise PaymentExecutionError("Sender account not found.")

        log_audit_event(
            actor_id=str(sender_user_id),
            action="demo_verification_completed",
            resource=f"payment:{attempt.reference}",
            result="VERIFIED",
            metadata={"amount": attempt.amount},
            db_session=db
        )

        attempt = self._execute_provider_payment(db, attempt, account, attempt.recipient_upi_masked)
        db.commit()
        db.refresh(attempt)
        return attempt

    def _execute_provider_payment(
        self,
        db: Session,
        attempt: PaymentAttempt,
        account: DemoPaymentAccount,
        recipient_upi: str
    ) -> PaymentAttempt:
        """
        Invokes PaymentProvider and enforces critical balance invariants:
        - Blocked: balance does not change
        - Failed: balance does not change
        - Completed: balance updates EXACTLY ONCE
        """
        # Execute through provider
        provider_resp = self.provider.initiate_payment(
            payment_reference=attempt.reference,
            amount=attempt.amount,
            currency=attempt.currency,
            sender_account_id=str(account.id),
            recipient_upi=recipient_upi
        )

        if provider_resp.status == "SUCCESS":
            validate_state_transition(attempt.state, PaymentState.COMPLETED.value)
            attempt.state = PaymentState.COMPLETED.value

            # INVARIANT: Atomically update balance exactly once
            account.simulated_balance -= attempt.amount
            db.add(account)

            # Record directed graph edge for transaction relationship tracking
            edge = TransactionGraphEdge(
                sender_node=f"user:{attempt.sender_user_id}",
                receiver_node=f"upi:{attempt.recipient_upi_lookup_hash[:16]}",
                payment_id=attempt.id,
                amount=attempt.amount,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(edge)

        elif provider_resp.status == "PENDING":
            validate_state_transition(attempt.state, PaymentState.PENDING.value)
            attempt.state = PaymentState.PENDING.value
            # Invariant: No balance change until settled

        else:
            validate_state_transition(attempt.state, PaymentState.FAILED.value)
            attempt.state = PaymentState.FAILED.value
            attempt.failure_reason = provider_resp.message
            # Invariant: No balance change on failure

        log_audit_event(
            actor_id=str(attempt.sender_user_id),
            action="provider_payment_executed",
            resource=f"payment:{attempt.reference}",
            result=attempt.state,
            metadata={"provider": attempt.provider, "provider_ref": provider_resp.provider_reference},
            db_session=db
        )

        return attempt

payment_service = PaymentService()
