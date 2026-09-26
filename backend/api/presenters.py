"""Turn database rows into API responses. Nothing internal (features, thresholds,
contributions, receiver history) leaves through here."""

from __future__ import annotations

import json
from decimal import Decimal

from backend.core.encryption import encryption_service
from backend.database.database import as_utc
from backend.database.models import PaymentAttempt, User
from backend.schemas import (
    IncomingView, PaymentActions, PaymentRecipientView, PaymentView, ReasonCode, RiskView, TimelineEntry, UserProfile,
)


def iso(dt) -> str | None:
    return as_utc(dt).isoformat() if dt else None


def money(value) -> str:
    return f"{Decimal(value):.2f}"


def user_profile(user: User) -> UserProfile:
    p = user.get_decrypted_profile()
    return UserProfile(id=user.id, full_name=p["full_name"], email=p["email"], phone=p["phone"],
                       upi_id=p["upi_id"], status=user.status, created_at=iso(user.created_at),
                       last_login_at=iso(user.last_login_at))


def payment_view(p: PaymentAttempt, include_timeline: bool = False) -> PaymentView:
    risk = None
    ra = p.risk_assessment
    if ra is not None:
        try:
            reasons = [ReasonCode(**r) for r in json.loads(ra.reason_codes_json)]
        except (ValueError, TypeError):
            reasons = []
        risk = RiskView(score=ra.risk_score, band=ra.risk_band, decision=ra.decision,
                        requires_verification=ra.decision == "VERIFY", blocked=ra.decision == "BLOCK",
                        reason_codes=reasons, score_kind=ra.score_kind, model_version=ra.model_version,
                        policy_version=ra.policy_version, assessed_at=iso(ra.created_at))
    upi = encryption_service.decrypt(p.recipient_upi_enc) if p.recipient_upi_enc else p.recipient_upi_masked
    name = encryption_service.decrypt(p.recipient_name_enc) if p.recipient_name_enc else upi
    awaiting = p.state in ("ASSESSING", "NEEDS_VERIFICATION") and not p.authorization_idempotency_key
    timeline = None
    if include_timeline:
        timeline = [TimelineEntry(state=t.to_state, reason=t.reason, at=iso(t.created_at)) for t in p.transitions]
    return PaymentView(
        id=p.id, reference=p.reference, mode=p.mode, is_simulated=p.is_simulated, state=p.state,
        amount=money(p.amount), currency=p.currency,
        recipient=PaymentRecipientView(name=name, upi_id=upi, payment_type=p.payment_type),
        note=encryption_service.decrypt(p.note_enc) if p.note_enc else None,
        failure_reason=p.failure_reason, simulated_outcome=p.simulated_outcome, provider=p.provider,
        created_at=iso(p.created_at), updated_at=iso(p.updated_at), completed_at=iso(p.completed_at), risk=risk,
        actions=PaymentActions(can_authorize=awaiting, needs_verification=awaiting and p.state == "NEEDS_VERIFICATION",
                               can_cancel=awaiting, can_refresh_status=p.state == "PENDING"),
        timeline=timeline,
    )


def incoming_view(p: PaymentAttempt, sender_name: str) -> IncomingView:
    return IncomingView(id=p.id, reference=p.reference, amount=money(p.amount), currency=p.currency,
                        from_name=sender_name, state=p.state, is_simulated=p.is_simulated,
                        created_at=iso(p.created_at))
