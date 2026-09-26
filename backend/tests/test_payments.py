"""Payment flow and invariants: blocked/failed never move money, completed moves it exactly once."""

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.database.models import (
    FeatureSnapshot, PaymentAttempt, PaymentStateTransition, ProviderCallbackEvent, RiskAssessment, TransactionGraphEdge,
)
from backend.domain.payment_service import PaymentError, PaymentService
from backend.domain.payment_state import InvalidStateTransitionError, validate_state_transition


def first_payment(u, to, amount=500):
    r = u.assess(to, amount)
    assert r.status_code == 201, r.text
    return r.json()


def test_low_risk_payment_completes_and_debits_exactly_once(make_user, seeded_directory):
    u = make_user("Asha Rao")
    before = u.balance()
    p = first_payment(u, "freshmarket@merchant", 250)
    assert p["is_simulated"] and p["mode"] == "SIMULATION"
    assert p["risk"]["band"] == "LOW" and p["state"] == "ASSESSING" and p["actions"]["can_authorize"]
    assert u.balance() == before  # assessing never moves money
    key = f"auth-{uuid.uuid4().hex}"
    done = u.authorize(p["id"], key=key).json()
    assert done["state"] == "COMPLETED"
    replay = u.authorize(p["id"], key=key)  # same authorisation retried
    assert replay.status_code == 200 and replay.json()["state"] == "COMPLETED"
    assert u.authorize(p["id"]).status_code == 409  # a different key can't submit it again
    assert u.balance() == before - 250


def test_transfer_between_yogii_users_credits_receiver(make_user):
    a, b = make_user("Asha Rao"), make_user("Bala Iyer")
    p = first_payment(a, b.profile["upi_id"], 300)
    if p["actions"]["needs_verification"]:
        u = a.authorize(p["id"], demo_verification_confirmed=True)
    else:
        u = a.authorize(p["id"])
    assert u.json()["state"] == "COMPLETED"
    assert b.balance() == 50300.0 and a.balance() == 49700.0
    dash = b.get("/api/dashboard").json()
    assert dash["recent_incoming"][0]["from_name"] == "Asha Rao"


def test_idempotent_assessment_per_sender(make_user, seeded_directory):
    a, b = make_user("Asha Rao"), make_user("Bala Iyer")
    r1 = a.assess("rahul@upi", 400, key="same-key-123")
    r2 = a.assess("rahul@upi", 400, key="same-key-123")
    assert r1.json()["id"] == r2.json()["id"]
    # Another user reusing the same key gets their own attempt, never someone else's.
    r3 = b.assess("rahul@upi", 400, key="same-key-123")
    assert r3.json()["id"] != r1.json()["id"]


def test_idempotency_key_is_required(make_user, seeded_directory):
    u = make_user()
    r = u.post("/api/payments/assess", {"recipient_upi": "rahul@upi", "amount": 100})
    assert r.status_code == 422


def test_watchlisted_payee_is_blocked_and_recorded(make_user, seeded_directory, db):
    u = make_user("Asha Rao")
    before = u.balance()
    p = first_payment(u, "crypto_drain@unknown", 40000)
    assert p["state"] == "BLOCKED" and p["risk"]["band"] == "VERY_HIGH" and p["risk"]["blocked"]
    assert not p["actions"]["can_authorize"]
    assert u.authorize(p["id"]).status_code == 409
    assert u.balance() == before
    row = db.get(PaymentAttempt, p["id"])
    assert row.balance_applied is False and row.provider_reference is None
    ra = db.query(RiskAssessment).filter_by(payment_attempt_id=row.id).one()
    assert ra.model_version and ra.policy_version and ra.decision == "BLOCK" and json.loads(ra.reason_codes_json)
    assert db.query(FeatureSnapshot).filter_by(payment_attempt_id=row.id).count() == 1
    states = [t.to_state for t in db.query(PaymentStateTransition).filter_by(payment_attempt_id=row.id)]
    assert states == ["DRAFT", "ASSESSING", "BLOCKED"]
    assert db.query(TransactionGraphEdge).count() == 0


def test_failed_payment_does_not_change_balance(make_user, seeded_directory):
    u = make_user()
    before = u.balance()
    p = first_payment(u, "freshmarket@merchant", 250)
    r = u.authorize(p["id"], simulated_outcome="FAILURE").json()
    assert r["state"] == "FAILED" and "declined" in r["failure_reason"]
    assert u.balance() == before


def test_pending_payment_settles_once_on_status_lookup(make_user, seeded_directory):
    u = make_user()
    before = u.balance()
    p = first_payment(u, "freshmarket@merchant", 250)
    assert u.authorize(p["id"], simulated_outcome="PENDING").json()["state"] == "PENDING"
    assert u.balance() == before
    assert u.get(f"/api/payments/{p['id']}/status").json()["state"] == "COMPLETED"
    assert u.get(f"/api/payments/{p['id']}/status").json()["state"] == "COMPLETED"
    assert u.balance() == before - 250


def test_verification_required_for_medium_and_high(make_user, seeded_directory, db):
    u = make_user()
    # A large amount to a brand-new, unverified payee with no history needs verification.
    p = first_payment(u, "brand.new.payee@okaxis", 30000)
    if p["state"] == "BLOCKED":
        pytest.skip("model blocked this example outright")
    assert p["state"] == "NEEDS_VERIFICATION", p["risk"]
    r = u.authorize(p["id"])
    assert r.status_code == 422 and r.json()["code"] == "verification_required"
    ok = u.authorize(p["id"], demo_verification_confirmed=True).json()
    assert ok["state"] == "COMPLETED"
    assert db.get(PaymentAttempt, p["id"]).verification_completed_at is not None


def test_cancel_before_authorisation(make_user, seeded_directory):
    u = make_user()
    p = first_payment(u, "freshmarket@merchant", 250)
    r = u.post(f"/api/payments/{p['id']}/cancel").json()
    assert r["state"] == "FAILED" and "Cancelled" in r["failure_reason"]
    assert u.authorize(p["id"]).status_code == 409
    assert u.balance() == 50000.0


@pytest.mark.parametrize("amount,code", [(0, 422), (-5, 422), (100001, 422), (10.123, 422), (60000, 422)])
def test_invalid_amounts_rejected(make_user, seeded_directory, amount, code):
    u = make_user()
    assert u.assess("rahul@upi", amount).status_code == code


@pytest.mark.parametrize("to", ["not-an-upi", "a@b", "x" * 60 + "@okaxis", "rahul@upi; DROP TABLE users"])
def test_invalid_recipients_rejected(make_user, to):
    assert make_user().assess(to, 100).status_code == 422


def test_cannot_pay_self(make_user):
    u = make_user()
    r = u.assess(u.profile["upi_id"], 100)
    assert r.status_code == 422 and r.json()["code"] == "self_payment"


def test_expired_assessment_cannot_be_authorised(db, make_user, seeded_directory, service):
    u = make_user()
    p = first_payment(u, "freshmarket@merchant", 250)
    from backend.database.models import User
    later = datetime.now(timezone.utc) + timedelta(minutes=30)
    with pytest.raises(PaymentError, match="expired"):
        service.authorize(db, db.get(User, u.id), p["id"], "late-key-123", at=later)


def test_other_users_cannot_see_or_act_on_a_payment(make_user, seeded_directory):
    a, b = make_user("Asha Rao"), make_user("Bala Iyer")
    p = first_payment(a, "freshmarket@merchant", 250)
    assert b.get(f"/api/payments/{p['id']}").status_code == 404
    assert b.get(f"/api/payments/{p['id']}/status").status_code == 404
    assert b.authorize(p["id"]).status_code == 404
    assert b.post(f"/api/payments/{p['id']}/cancel").status_code == 404
    assert b.get("/api/payments").json()["total"] == 0


def test_history_filters_and_detail_timeline(make_user, seeded_directory):
    u = make_user()
    ok = first_payment(u, "freshmarket@merchant", 250)
    u.authorize(ok["id"])
    first_payment(u, "crypto_drain@unknown", 40000)
    assert u.get("/api/payments?state=BLOCKED").json()["total"] == 1
    assert u.get("/api/payments?band=VERY_HIGH").json()["total"] == 1
    assert u.get("/api/payments").json()["total"] == 2
    assert u.get("/api/payments?state=NOPE").status_code == 422
    detail = u.get(f"/api/payments/{ok['id']}").json()
    assert [t["state"] for t in detail["timeline"]][-1] == "COMPLETED"


def test_state_machine_rejects_illegal_transitions():
    for a, b in [("BLOCKED", "COMPLETED"), ("FAILED", "COMPLETED"), ("COMPLETED", "FAILED"), ("DRAFT", "COMPLETED"),
                 ("PENDING", "BLOCKED"), ("REVERSED", "COMPLETED"), ("NEEDS_VERIFICATION", "BLOCKED")]:
        with pytest.raises(InvalidStateTransitionError):
            validate_state_transition(a, b)
    validate_state_transition("PENDING", "COMPLETED")
    validate_state_transition("COMPLETED", "REVERSED")


def test_reversal_restores_balances_once(make_user, seeded_directory, db, service):
    a, b = make_user("Asha Rao"), make_user("Bala Iyer")
    p = first_payment(a, b.profile["upi_id"], 300)
    a.authorize(p["id"], demo_verification_confirmed=True)
    attempt = db.get(PaymentAttempt, p["id"])
    service.reverse(db, attempt, "demo dispute")
    assert attempt.state == "REVERSED"
    assert a.balance() == 50000.0 and b.balance() == 50000.0
    with pytest.raises(PaymentError):
        service.reverse(db, attempt, "again")
    assert a.balance() == 50000.0


# ------------------------------------------------------------------ provider callbacks

def _callback(client, provider, payload, sign=True, ts=None):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers.update(provider.sign_callback(body, timestamp=ts))
    return client.post("/api/integrations/payments/callback", content=body, headers=headers)


def test_signed_callback_completes_pending_payment_once(make_user, seeded_directory, db, service):
    u = make_user()
    p = first_payment(u, "freshmarket@merchant", 250)
    ref = db.get(PaymentAttempt, u.authorize(p["id"], simulated_outcome="PENDING").json()["id"]).provider_reference
    payload = {"event_id": "evt-100", "provider_reference": ref, "status": "SUCCESS"}
    r = _callback(u.client, service.provider, payload)
    assert r.status_code == 200 and r.json()["status"] == "applied"
    assert _callback(u.client, service.provider, payload).json()["status"] == "duplicate"   # replay
    payload2 = {"event_id": "evt-101", "provider_reference": ref, "status": "SUCCESS"}
    assert _callback(u.client, service.provider, payload2).json()["status"] == "ignored"    # already completed
    assert u.balance() == 49750.0


def test_unsigned_or_tampered_callbacks_are_rejected_and_recorded(make_user, seeded_directory, db, service):
    u = make_user()
    p = first_payment(u, "freshmarket@merchant", 250)
    ref = db.get(PaymentAttempt, u.authorize(p["id"], simulated_outcome="PENDING").json()["id"]).provider_reference
    payload = {"event_id": "evt-200", "provider_reference": ref, "status": "SUCCESS"}
    assert _callback(u.client, service.provider, payload, sign=False).status_code == 401
    assert _callback(u.client, service.provider, payload, ts=int(time.time()) - 3600).status_code == 401
    body = json.dumps(payload).encode()
    forged = {**service.provider.sign_callback(b"something else"), "Content-Type": "application/json"}
    assert u.client.post("/api/integrations/payments/callback", content=body, headers=forged).status_code == 401
    assert db.query(ProviderCallbackEvent).filter_by(outcome="REJECTED").count() == 3
    assert db.get(PaymentAttempt, p["id"]).state == "PENDING"
    assert u.balance() == 50000.0


def test_simulated_outcome_not_allowed_outside_simulation(make_user, seeded_directory, db, service, monkeypatch):
    from backend.core import config
    u = make_user()
    p = first_payment(u, "freshmarket@merchant", 250)
    monkeypatch.setattr(config.settings, "PAYMENT_MODE", "live")
    from backend.database.models import User
    with pytest.raises(PaymentError, match="not available in live mode"):
        service.authorize(db, db.get(User, u.id), p["id"], "live-key-123", simulated_outcome="SUCCESS")


@pytest.mark.skipif(not __import__("backend.database.database", fromlist=["x"]).supports_row_locks(),
                    reason="row-lock race test needs PostgreSQL (set TEST_DATABASE_URL)")
def test_concurrent_authorisations_debit_once(make_user, seeded_directory):
    from concurrent.futures import ThreadPoolExecutor
    from backend.core.services import get_payment_service
    from backend.database.database import SessionLocal
    from backend.database.models import User

    u = make_user()
    p = first_payment(u, "freshmarket@merchant", 250)

    def attempt(i):
        s = SessionLocal()
        try:
            get_payment_service().authorize(s, s.get(User, u.id), p["id"], f"race-key-{i:04d}")
            return "ok"
        except PaymentError as exc:
            return exc.code
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt, range(6)))
    assert outcomes.count("ok") == 1 and outcomes.count("already_authorized") == 5
    assert u.balance() == 49750.0
