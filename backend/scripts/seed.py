import uuid
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from backend.database.models import (
    User, DemoPaymentAccount, Recipient, PaymentAttempt, RiskAssessment,
    FeatureSnapshot, TransactionGraphEdge, AppConfiguration
)
from backend.core.encryption import encryption_service, hash_password
from backend.domain.payment_state import PaymentState

def seed_fictional_demo_data(db: Session, force_reseed: bool = False) -> None:
    """
    Seeds comprehensive, clearly labelled FICTIONAL demo data into the Yogii database.
    Demonstrates scenarios 1 to 8:
    1. Routine payment to familiar recipient
    2. Large payment to a new recipient
    3. High transaction velocity
    4. Unusual simulated time/device/location
    5. Pass-through: Yogesh -> Visrojit -> Dinesh (similar amount, short time gap)
    6. Very-high-risk blocked payment
    7. Failed payment (balances unchanged)
    8. Completed payment (balance changed exactly once)
    """
    existing_users = db.query(User).count()
    if existing_users > 0 and not force_reseed:
        print("Database already contains user records. Skipping seed.")
        return

    if force_reseed:
        print("Force reseeding: clearing existing demo records...")
        db.query(FeatureSnapshot).delete()
        db.query(RiskAssessment).delete()
        db.query(TransactionGraphEdge).delete()
        db.query(PaymentAttempt).delete()
        db.query(DemoPaymentAccount).delete()
        db.query(Recipient).delete()
        db.query(User).delete()
        db.commit()

    print("Seeding fictional demo users and payment rails...")
    now = datetime.now(timezone.utc)
    shared_password_hash = hash_password("Password123!")

    # 1. Create Fictional Users: Yogesh, Visrojit, Dinesh
    demo_users_data = [
        {"name": "Yogesh Kumar", "email": "yogesh@demo.yogii", "phone": "9876543210", "upi": "yogesh@yogii", "balance": 45000.0},
        {"name": "Visrojit Sharma", "email": "visrojit@demo.yogii", "phone": "9876543211", "upi": "visrojit@yogii", "balance": 35000.0},
        {"name": "Dinesh Patel", "email": "dinesh@demo.yogii", "phone": "9876543212", "upi": "dinesh@yogii", "balance": 28000.0}
    ]

    users = {}
    accounts = {}
    for u in demo_users_data:
        email_hash = encryption_service.blind_index(u["email"])
        upi_hash = encryption_service.blind_index(u["upi"])
        phone_hash = encryption_service.blind_index(u["phone"])

        user = User(
            full_name_enc=encryption_service.encrypt(u["name"]),
            phone_enc=encryption_service.encrypt(u["phone"]),
            email_enc=encryption_service.encrypt(u["email"]),
            upi_id_enc=encryption_service.encrypt(u["upi"]),
            device_id_enc=encryption_service.encrypt(f"device-{u['upi'].split('@')[0]}"),
            phone_lookup_hash=phone_hash,
            email_lookup_hash=email_hash,
            upi_id_lookup_hash=upi_hash,
            password_hash=shared_password_hash,
            status="ACTIVE",
            created_at=now - timedelta(days=120)
        )
        db.add(user)
        db.flush()
        users[u["upi"]] = user

        account = DemoPaymentAccount(
            user_id=user.id,
            simulated_balance=u["balance"],
            currency="INR",
            status="ACTIVE",
            created_at=now - timedelta(days=120)
        )
        db.add(account)
        db.flush()
        accounts[u["upi"]] = account

    # 2. Create Fictional Demo Recipients (P2P and P2M)
    demo_recipients_data = [
        {"name": "Rahul Verma", "upi": "rahul@upi", "phone": "9123456780", "type": "P2P", "trust": "trusted", "category": None},
        {"name": "Fresh Market Mart", "upi": "freshmarket@merchant", "phone": "9123456781", "type": "P2M", "trust": "trusted", "category": "Groceries"},
        {"name": "Campus Cafe", "upi": "campuscafe@merchant", "phone": "9123456782", "type": "P2M", "trust": "trusted", "category": "Dining"},
        {"name": "Tech Gadgets Store", "upi": "techgadgets@merchant", "phone": "9123456783", "type": "P2M", "trust": "neutral", "category": "Electronics"},
        {"name": "Unknown Offshore Entity", "upi": "crypto_drain@unknown", "phone": "9123456784", "type": "P2P", "trust": "suspicious", "category": "Crypto"},
    ]

    recipients = {}
    for r in demo_recipients_data:
        upi_hash = encryption_service.blind_index(r["upi"])
        phone_hash = encryption_service.blind_index(r["phone"])
        rec = Recipient(
            name_enc=encryption_service.encrypt(r["name"]),
            upi_id_enc=encryption_service.encrypt(r["upi"]),
            phone_enc=encryption_service.encrypt(r["phone"]),
            upi_id_lookup_hash=upi_hash,
            phone_lookup_hash=phone_hash,
            recipient_type=r["type"],
            merchant_category=r["category"],
            trust_level=r["trust"],
            is_fictional_demo=True,
            created_at=now - timedelta(days=60)
        )
        db.add(rec)
        db.flush()
        recipients[r["upi"]] = rec

    yogesh_user = users["yogesh@yogii"]
    yogesh_acc = accounts["yogesh@yogii"]
    visrojit_user = users["visrojit@yogii"]
    visrojit_acc = accounts["visrojit@yogii"]
    dinesh_user = users["dinesh@yogii"]

    # 3. Seed Scenario 1: Routine historical payments to familiar recipient (Rahul Verma)
    for i, amt in enumerate([450.0, 500.0, 600.0, 350.0, 520.0]):
        tx_time = now - timedelta(days=20 - (i * 3))
        ref = f"YOGII-SIM-ROUTINE-{i+1}"
        p = PaymentAttempt(
            reference=ref,
            sender_account_id=yogesh_acc.id,
            sender_user_id=yogesh_user.id,
            recipient_id=recipients["rahul@upi"].id,
            recipient_upi_lookup_hash=encryption_service.blind_index("rahul@upi"),
            recipient_upi_masked="rahul@upi",
            payment_type="P2P",
            amount=amt,
            currency="INR",
            state=PaymentState.COMPLETED.value,
            provider="MockPaymentProvider",
            idempotency_key=str(uuid.uuid4()),
            created_at=tx_time,
            updated_at=tx_time
        )
        db.add(p)
        db.flush()

        ra = RiskAssessment(
            payment_attempt_id=p.id,
            raw_risk_score=12.5,
            calibrated_probability=0.125,
            risk_band="LOW",
            decision="ALLOW",
            reason_codes_json=json.dumps([{"code": "ROUTINE_TRANSACTION", "description": "Transaction parameters align with your established account history."}]),
            model_version="1.0.0-synthetic",
            created_at=tx_time
        )
        db.add(ra)

        edge = TransactionGraphEdge(
            sender_node=f"user:{yogesh_user.id}",
            receiver_node=f"upi:{encryption_service.blind_index('rahul@upi')[:16]}",
            payment_id=p.id,
            amount=amt,
            timestamp=tx_time
        )
        db.add(edge)

    # 4. Seed Scenario 5: Pass-Through Chain: Yogesh -> Visrojit -> Dinesh
    # Step A: Yogesh sends ₹15,000 to Visrojit (45 mins ago)
    t_a = now - timedelta(minutes=45)
    p_a = PaymentAttempt(
        reference="YOGII-SIM-CHAIN-1",
        sender_account_id=yogesh_acc.id,
        sender_user_id=yogesh_user.id,
        recipient_id=None,
        recipient_upi_lookup_hash=encryption_service.blind_index("visrojit@yogii"),
        recipient_upi_masked="visrojit@yogii",
        payment_type="P2P",
        amount=15000.0,
        currency="INR",
        state=PaymentState.COMPLETED.value,
        provider="MockPaymentProvider",
        idempotency_key=str(uuid.uuid4()),
        created_at=t_a,
        updated_at=t_a
    )
    db.add(p_a)
    db.flush()

    edge_a = TransactionGraphEdge(
        sender_node=f"user:{yogesh_user.id}",
        receiver_node=f"upi:{encryption_service.blind_index('visrojit@yogii')[:16]}",
        payment_id=p_a.id,
        amount=15000.0,
        timestamp=t_a
    )
    db.add(edge_a)

    # Step B: Visrojit sends ₹14,800 to Dinesh (15 mins ago)
    t_b = now - timedelta(minutes=15)
    p_b = PaymentAttempt(
        reference="YOGII-SIM-CHAIN-2",
        sender_account_id=visrojit_acc.id,
        sender_user_id=visrojit_user.id,
        recipient_id=None,
        recipient_upi_lookup_hash=encryption_service.blind_index("dinesh@yogii"),
        recipient_upi_masked="dinesh@yogii",
        payment_type="P2P",
        amount=14800.0,
        currency="INR",
        state=PaymentState.COMPLETED.value,
        provider="MockPaymentProvider",
        idempotency_key=str(uuid.uuid4()),
        created_at=t_b,
        updated_at=t_b
    )
    db.add(p_b)
    db.flush()

    edge_b = TransactionGraphEdge(
        sender_node=f"user:{visrojit_user.id}",
        receiver_node=f"upi:{encryption_service.blind_index('dinesh@yogii')[:16]}",
        payment_id=p_b.id,
        amount=14800.0,
        timestamp=t_b
    )
    db.add(edge_b)

    # 5. Seed Scenario 6: Very-high-risk blocked payment (₹48,000 to crypto drainer)
    t_blocked = now - timedelta(hours=2)
    p_block = PaymentAttempt(
        reference="YOGII-SIM-BLOCKED-DEMO",
        sender_account_id=yogesh_acc.id,
        sender_user_id=yogesh_user.id,
        recipient_id=recipients["crypto_drain@unknown"].id,
        recipient_upi_lookup_hash=encryption_service.blind_index("crypto_drain@unknown"),
        recipient_upi_masked="crypto_drain@unknown",
        payment_type="P2P",
        amount=48000.0,
        currency="INR",
        state=PaymentState.BLOCKED.value,
        provider="MockPaymentProvider",
        failure_reason="Payment blocked by Yogii prototype risk policy threshold (Risk Score >= 85).",
        idempotency_key=str(uuid.uuid4()),
        created_at=t_blocked,
        updated_at=t_blocked
    )
    db.add(p_block)
    db.flush()

    ra_block = RiskAssessment(
        payment_attempt_id=p_block.id,
        raw_risk_score=94.2,
        calibrated_probability=0.942,
        risk_band="VERY_HIGH",
        decision="BLOCK",
        reason_codes_json=json.dumps([
            {"code": "AMOUNT_ABOVE_USUAL", "description": "₹48,000 is significantly higher than your recent payment amounts."},
            {"code": "NEW_RECIPIENT", "description": "First-time transfer to an unverified recipient identifier."}
        ]),
        model_version="1.0.0-synthetic",
        created_at=t_blocked
    )
    db.add(ra_block)

    # 6. Seed Scenario 7: Failed transaction (balances unchanged)
    t_fail = now - timedelta(hours=5)
    p_fail = PaymentAttempt(
        reference="YOGII-SIM-FAILED-DEMO",
        sender_account_id=yogesh_acc.id,
        sender_user_id=yogesh_user.id,
        recipient_id=recipients["techgadgets@merchant"].id,
        recipient_upi_lookup_hash=encryption_service.blind_index("techgadgets@merchant"),
        recipient_upi_masked="techgadgets@merchant",
        payment_type="P2M",
        amount=3500.0,
        currency="INR",
        state=PaymentState.FAILED.value,
        provider="MockPaymentProvider",
        failure_reason="Simulated transaction declined by mock destination banking switch.",
        idempotency_key=str(uuid.uuid4()),
        created_at=t_fail,
        updated_at=t_fail
    )
    db.add(p_fail)
    db.flush()

    # 7. Seed AppConfiguration
    configs = [
        ("PAYMENT_MODE", "simulation", False),
        ("LIVE_UPI_ENABLED", "false", False),
        ("RISK_POLICY_VERSION", "v1.0-prototype", False)
    ]
    for k, v, sec in configs:
        db.add(AppConfiguration(config_key=k, config_value=v, is_secret=sec))

    db.commit()
    print("Fictional demo data seeded successfully with all 8 scenarios.")

if __name__ == "__main__":
    from backend.database.database import SessionLocal
    db = SessionLocal()
    try:
        seed_fictional_demo_data(db, force_reseed=True)
    finally:
        db.close()
