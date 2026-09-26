"""The fictional seed runs every scenario through the real service; check the outcomes and the ledger."""

from decimal import Decimal

from sqlalchemy import func

from backend.database.models import DemoPaymentAccount, PaymentAttempt, User
from backend.scripts.seed import DEMO_USERS, seed_demo_data

ORDER = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]


def test_seed_scenarios_and_balance_ledger(db):
    results = {r.scenario: r for r in seed_demo_data(db, verbose=False)}
    assert results["1 routine payment to familiar recipient"].band == "LOW"
    assert results["1 routine payment to familiar recipient"].state == "COMPLETED"
    assert results["8 same key replayed: completed exactly once"].state == "COMPLETED"
    assert ORDER.index(results["2 large payment to new recipient"].band) >= ORDER.index("MEDIUM")
    burst = [results[f"3 velocity burst #{i}"] for i in range(1, 6)]
    assert any("HIGH_RECENT_VELOCITY" in r.reasons for r in burst)
    assert ORDER.index(burst[-1].band) >= ORDER.index("MEDIUM")
    unusual = results["4 unusual time, device and location"]
    assert {"UNUSUAL_TIME", "DEVICE_OR_LOCATION_CHANGE"} <= set(unusual.reasons)
    assert results["6 very-high-risk attempt (blocked)"].state == "BLOCKED"
    passthrough = results["5b Visrojit -> Dinesh (possible pass-through)"]
    assert "POSSIBLE_PASS_THROUGH_PATTERN" in passthrough.reasons
    assert passthrough.state != "BLOCKED"  # a graph pattern is a signal, not proof
    assert results["7 failed payment (balance unchanged)"].state == "FAILED"
    assert results["pending payment (try Check status)"].state == "PENDING"

    # Ledger check: every balance equals start - completed outflows + completed inflows.
    for user in db.query(User).all():
        start = Decimal(next(d[4] for d in DEMO_USERS if d[0] == user.get_decrypted_profile()["full_name"]))
        out = db.query(func.coalesce(func.sum(PaymentAttempt.amount), 0)).filter(
            PaymentAttempt.sender_user_id == user.id, PaymentAttempt.state == "COMPLETED").scalar()
        inflow = db.query(func.coalesce(func.sum(PaymentAttempt.amount), 0)).filter(
            PaymentAttempt.recipient_user_id == user.id, PaymentAttempt.state == "COMPLETED").scalar()
        bal = db.query(DemoPaymentAccount).filter_by(user_id=user.id).one().simulated_balance
        assert Decimal(bal) == start - Decimal(out) + Decimal(inflow)
    # Blocked and failed attempts never set the ledger flag.
    assert db.query(PaymentAttempt).filter(PaymentAttempt.state.in_(["BLOCKED", "FAILED"]),
                                           PaymentAttempt.balance_applied.is_(True)).count() == 0


def test_seed_is_idempotent(db):
    seed_demo_data(db, verbose=False)
    n = db.query(PaymentAttempt).count()
    assert seed_demo_data(db, verbose=False) == []
    assert db.query(PaymentAttempt).count() == n
