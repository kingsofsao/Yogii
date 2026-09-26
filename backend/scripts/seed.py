"""Seed FICTIONAL demo data by running payments through the real service.

    python -m backend.scripts.seed            # seed an empty database
    python -m backend.scripts.seed --reset    # wipe demo data first (development only)

Every person, UPI ID, merchant and payment here is fictional. Each payment,
including the backdated history, goes through PaymentService with the real
feature engine, risk model and mock rail. That means stored risk scores are
genuine model outputs, not hard-coded numbers.

Scenarios are placed before the most recent 18:30 IST, so they fall in daytime hours
(except scenario 4, which is deliberately at 3 AM). Scenarios created:
 1. Routine payment to a familiar recipient (Yogesh -> rahul@upi)
 2. Much larger-than-usual payment to a new recipient (Yogesh -> arjun.mehta@okaxis)
 3. High velocity: several payments in a few minutes (Dinesh)
 4. Unusual simulated time, device and location (Visrojit at 3 AM on a new phone)
 5. Possible pass-through: Yogesh -> Visrojit -> Dinesh, similar amounts, short gap
 6. Very-high-risk attempt that is blocked (Yogesh -> crypto_drain@unknown)
 7. Failed payment that does not change balances (mock rail outcome FAILURE)
 8. Completed payment that updates balances exactly once (same key replayed)
Plus one PENDING payment so "check status" can be tried.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.encryption import encryption_service, hash_password
from backend.database.database import Base, SessionLocal, engine
from backend.database.models import (
    AuditEvent, DemoPaymentAccount, FeatureSnapshot, PaymentAttempt, PaymentStateTransition, ProviderCallbackEvent,
    Recipient, RiskAssessment, SecurityEvent, TransactionGraphEdge, User, UserPreference,
)
from backend.domain.payment_service import PaymentError, PaymentService
from backend.integrations.payments import build_payment_provider
from backend.ml.inference import inference_service

IST = ZoneInfo("Asia/Kolkata")
DEMO_PASSWORD = "Password123!"  # fictional demo accounts only

DEMO_USERS = [
    # name, email, phone, upi, starting simulated balance, account age (days)
    ("Yogesh Kumar", "yogesh@demo.yogii", "9876543210", "yogesh@yogii", 100000, 420),
    ("Visrojit Sharma", "visrojit@demo.yogii", "9876543211", "visrojit@yogii", 45000, 380),
    ("Dinesh Patel", "dinesh@demo.yogii", "9876543212", "dinesh@yogii", 40000, 300),
]
DEMO_RECIPIENTS = [
    # name, upi, phone, type, category, watchlist, age (days)
    ("Rahul Verma", "rahul@upi", "9123456780", "P2P", None, False, 900),
    ("Priya Nair", "priya.nair@okbank", "9123456785", "P2P", None, False, 700),
    ("Fresh Market", "freshmarket@merchant", "9123456781", "P2M", "Groceries", False, 1200),
    ("Campus Cafe", "campuscafe@merchant", "9123456782", "P2M", "Dining", False, 800),
    ("Tech Gadgets", "techgadgets@merchant", "9123456783", "P2M", "Electronics", False, 600),
    ("City Book Hub", "bookhub@merchant", "9123456786", "P2M", "Books", False, 500),
    ("crypto_drain", "crypto_drain@unknown", "9123456784", "P2P", None, True, 3),
]
# Everyday payees and typical amounts for each user's backdated history.
HISTORY_PLAN = {
    "yogesh@yogii": [("rahul@upi", 600), ("freshmarket@merchant", 1400), ("campuscafe@merchant", 300),
                     ("visrojit@yogii", 800), ("bookhub@merchant", 500)],
    "visrojit@yogii": [("freshmarket@merchant", 1800), ("campuscafe@merchant", 350), ("priya.nair@okbank", 900),
                       ("yogesh@yogii", 700)],
    "dinesh@yogii": [("freshmarket@merchant", 1200), ("campuscafe@merchant", 250), ("rahul@upi", 700)],
}


@dataclass
class ScenarioResult:
    scenario: str
    reference: str
    state: str
    score: Optional[int]
    band: Optional[str]
    reasons: List[str]


class Seeder:
    def __init__(self, db: Session, now: Optional[datetime] = None):
        self.db = db
        self.now = now or datetime.now(timezone.utc)
        self._clock = self.now
        self.service = PaymentService(build_payment_provider(), clock=lambda: self._clock)
        self.users: Dict[str, User] = {}
        self.results: List[ScenarioResult] = []
        self._n = 0

    def pay(self, sender: str, to: str, amount, at: datetime, device: str = "primary", location: str = "home",
            outcome: str = "SUCCESS", verify: bool = True, key: Optional[str] = None,
            scenario: Optional[str] = None) -> Optional[PaymentAttempt]:
        self._clock = at
        self._n += 1
        key = key or f"seed-{self._n:05d}-{sender.split('@')[0]}"
        try:
            attempt = self.service.assess(self.db, self.users[sender], to, amount, key,
                                          simulated_device=device, simulated_location=location, at=at)
            if attempt.state in ("ASSESSING", "NEEDS_VERIFICATION") and (verify or attempt.state == "ASSESSING"):
                attempt = self.service.authorize(self.db, self.users[sender], attempt.id, f"{key}-auth",
                                                 demo_verification_confirmed=verify, simulated_outcome=outcome, at=at)
        except PaymentError as exc:
            print(f"  ! {scenario or 'history'}: {exc}")
            return None
        if scenario:
            ra = attempt.risk_assessment
            import json
            self.results.append(ScenarioResult(
                scenario, attempt.reference, attempt.state, ra.risk_score if ra else None, ra.risk_band if ra else None,
                [r["code"] for r in json.loads(ra.reason_codes_json)] if ra else []))
        return attempt

    def create_people(self) -> None:
        pw = hash_password(DEMO_PASSWORD)
        for name, email, phone, upi, balance, age in DEMO_USERS:
            u = User(full_name_enc=encryption_service.encrypt(name), phone_enc=encryption_service.encrypt(phone),
                     email_enc=encryption_service.encrypt(email), upi_id_enc=encryption_service.encrypt(upi),
                     phone_lookup_hash=encryption_service.blind_index(phone),
                     email_lookup_hash=encryption_service.blind_index(email),
                     upi_id_lookup_hash=encryption_service.blind_index(upi), password_hash=pw, status="ACTIVE",
                     is_fictional_demo=True, created_at=self.now - timedelta(days=age))
            self.db.add(u)
            self.db.flush()
            self.db.add(DemoPaymentAccount(user_id=u.id, simulated_balance=Decimal(balance), is_simulated=True,
                                           created_at=self.now - timedelta(days=age)))
            self.db.add(UserPreference(user_id=u.id))
            self.users[upi] = u
        for name, upi, phone, rtype, cat, watch, age in DEMO_RECIPIENTS:
            self.db.add(Recipient(name_enc=encryption_service.encrypt(name), upi_id_enc=encryption_service.encrypt(upi),
                                  phone_enc=encryption_service.encrypt(phone),
                                  upi_id_lookup_hash=encryption_service.blind_index(upi),
                                  phone_lookup_hash=encryption_service.blind_index(phone),
                                  recipient_type=rtype, merchant_category=cat, on_watchlist=watch,
                                  trust_level="watchlist" if watch else "demo", is_fictional_demo=True,
                                  created_at=self.now - timedelta(days=age)))
        self.db.commit()

    def create_history(self, days: int = 45) -> None:
        rng = random.Random(7)
        plan = []
        for sender, payees in HISTORY_PLAN.items():
            for day in range(days, 1, -1):
                if rng.random() < 0.55:
                    to, typical = payees[rng.randrange(len(payees))]
                    local = (self.now - timedelta(days=day)).astimezone(IST).replace(
                        hour=rng.randint(10, 19), minute=rng.randint(0, 59), second=0, microsecond=0)
                    amount = round(typical * rng.uniform(0.6, 1.4) / 10) * 10
                    plan.append((local.astimezone(timezone.utc), sender, to, amount))
        for at, sender, to, amount in sorted(plan):
            self.pay(sender, to, amount, at)

    def scenario_anchor(self) -> datetime:
        """Most recent 18:30 IST at least 30 minutes ago, so scenarios happen in daytime hours."""
        local = self.now.astimezone(IST).replace(hour=18, minute=30, second=0, microsecond=0)
        if local.astimezone(timezone.utc) > self.now - timedelta(minutes=30):
            local -= timedelta(days=1)
        return local.astimezone(timezone.utc)

    def create_scenarios(self) -> None:
        now = self.scenario_anchor()
        # 7. A failed payment: the mock rail declines, balances stay the same.
        self.pay("yogesh@yogii", "freshmarket@merchant", 1200, now - timedelta(hours=5), outcome="FAILURE",
                 scenario="7 failed payment (balance unchanged)")
        # 1 and 8. Routine payment, then the same Idempotency-Key replayed: one payment, one debit.
        first = self.pay("yogesh@yogii", "rahul@upi", 500, now - timedelta(hours=4), key="seed-routine-rahul",
                         scenario="1 routine payment to familiar recipient")
        if first is not None:
            again = self.service.assess(self.db, self.users["yogesh@yogii"], "rahul@upi", 500, "seed-routine-rahul")
            assert again.id == first.id, "idempotency replay must return the same attempt"
            self.results.append(ScenarioResult("8 same key replayed: completed exactly once", first.reference,
                                               first.state, None, None, []))
        # 2. Much larger than usual, new recipient.
        self.pay("yogesh@yogii", "arjun.mehta@okaxis", 18000, now - timedelta(hours=3),
                 scenario="2 large payment to new recipient")
        # 3. Velocity: several payments to new payees within minutes.
        t = now - timedelta(hours=2)
        for i, (to, amount) in enumerate([("bookhub@merchant", 900), ("tutor.anil@okaxis", 1500),
                                          ("priya.nair@okbank", 2000), ("gift.shop88@okicici", 2500),
                                          ("quick.cash77@oksbi", 3000)]):
            self.pay("dinesh@yogii", to, amount, t + timedelta(minutes=3 * i), scenario=f"3 velocity burst #{i + 1}")
        # 4. Unusual simulated time, device and location.
        three_am = now.astimezone(IST).replace(hour=3, minute=10, second=0, microsecond=0)
        self.pay("visrojit@yogii", "gift.shop88@okicici", 6000, three_am.astimezone(timezone.utc),
                 device="new-phone", location="unfamiliar-city", scenario="4 unusual time, device and location")
        # 6. Very high risk: watchlisted payee, large amount, new device. Blocked before authorisation.
        self.pay("yogesh@yogii", "crypto_drain@unknown", 40000, now - timedelta(minutes=70), device="new-phone",
                 scenario="6 very-high-risk attempt (blocked)")
        # 5. Possible pass-through: Yogesh -> Visrojit, then Visrojit -> Dinesh, similar amount, 12 minutes later.
        self.pay("yogesh@yogii", "visrojit@yogii", 15000, now - timedelta(minutes=50),
                 scenario="5a Yogesh -> Visrojit")
        self.pay("visrojit@yogii", "dinesh@yogii", 14700, now - timedelta(minutes=38),
                 scenario="5b Visrojit -> Dinesh (possible pass-through)")
        # A pending payment for the "check status" demo.
        self.pay("dinesh@yogii", "freshmarket@merchant", 800, now - timedelta(minutes=20), outcome="PENDING",
                 scenario="pending payment (try Check status)")


def reset_demo_data(db: Session) -> None:
    for model in (ProviderCallbackEvent, TransactionGraphEdge, PaymentStateTransition, FeatureSnapshot, RiskAssessment,
                  PaymentAttempt, UserPreference, DemoPaymentAccount, Recipient, User, AuditEvent, SecurityEvent):
        db.query(model).delete()
    db.commit()


def seed_demo_data(db: Session, reset: bool = False, verbose: bool = True) -> List[ScenarioResult]:
    if settings.is_production:
        raise SystemExit("Refusing to seed fictional demo data into a production deployment.")
    if not settings.is_simulation:
        raise SystemExit("Demo data can only be seeded in simulation mode.")
    if reset:
        reset_demo_data(db)
    elif db.query(User).count() > 0:
        if verbose:
            print("Database already has users; skipping seed (use --reset in development).")
        return []
    if not inference_service.is_loaded:
        inference_service.load_model()
    seeder = Seeder(db)
    seeder.create_people()
    seeder.create_history()
    seeder.create_scenarios()
    if verbose:
        print("\nFICTIONAL demo data seeded. Scenario results (real model outputs, synthetic training data):")
        for r in seeder.results:
            print(f"  {r.scenario:<48} {r.state:<19} score={r.score!s:<4} band={r.band!s:<10} {','.join(r.reasons)}")
        print(f"\nDemo sign-in: yogesh@demo.yogii / visrojit@demo.yogii / dinesh@demo.yogii, password {DEMO_PASSWORD}")
    return seeder.results


def seed_if_empty() -> None:
    db = SessionLocal()
    try:
        seed_demo_data(db, reset=False, verbose=True)
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="delete existing demo data first (development only)")
    args = ap.parse_args()
    if settings.DB_AUTO_CREATE:
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_data(db, reset=args.reset)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
