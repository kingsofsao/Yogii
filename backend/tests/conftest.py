"""Shared test setup.

Tests run against a throwaway SQLite file by default. Set TEST_DATABASE_URL to
run the same suite against PostgreSQL, for example:

    TEST_DATABASE_URL=postgresql://yogii_owner:devowner@localhost:5432/yogii_test pytest backend/tests
"""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="yogii-tests-")
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["DB_AUTO_CREATE"] = "true"
os.environ["PAYMENT_MODE"] = "simulation"
os.environ["LIVE_PAYMENTS_ENABLED"] = "false"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SEED_DEMO_DATA_ON_STARTUP"] = "false"

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core.rate_limit import limiter  # noqa: E402
from backend.core.services import get_payment_service, init_services  # noqa: E402
from backend.database.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import app  # noqa: E402
from backend.ml.inference import inference_service  # noqa: E402

PASSWORD = "Str0ngPassword!"


@pytest.fixture(autouse=True)
def fresh_database():
    """Every test starts with empty tables and fresh rate-limit counters."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    limiter.reset()
    init_services()
    yield
    limiter.reset()


@pytest.fixture(scope="session", autouse=True)
def model_loaded():
    inference_service.load_model()


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def service():
    return get_payment_service()


class ApiUser:
    """A TestClient signed in as one user, sending the CSRF header automatically."""

    def __init__(self, client: TestClient, profile: dict, csrf: str):
        self.client, self.profile, self.csrf = client, profile, csrf

    @property
    def id(self) -> int:
        return self.profile["id"]

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, json=None, key=None, headers=None, **kw):
        h = {"X-CSRF-Token": self.csrf, **(headers or {})}
        if key:
            h["Idempotency-Key"] = key
        return self.client.post(url, json=json, headers=h, **kw)

    def patch(self, url, json=None, **kw):
        return self.client.patch(url, json=json, headers={"X-CSRF-Token": self.csrf}, **kw)

    def assess(self, to, amount, key=None, **extra):
        return self.post("/api/payments/assess", {"recipient_upi": to, "amount": amount, **extra},
                         key=key or f"assess-{uuid.uuid4().hex}")

    def authorize(self, payment_id, key=None, **extra):
        return self.post("/api/payments", {"payment_id": payment_id, **extra}, key=key or f"auth-{uuid.uuid4().hex}")

    def balance(self) -> float:
        return float(self.get("/api/me").json()["simulated_balance"])


def new_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def make_user():
    """Register a fresh user and return an ApiUser. Usage: make_user("Asha Rao")."""
    clients = []

    def _make(name="Test User", upi=None, phone=None, email=None) -> ApiUser:
        n = uuid.uuid4().hex[:6]
        client = new_client().__enter__()
        clients.append(client)
        payload = {"full_name": name, "email": email or f"user{n}@example.com",
                   "phone": phone or f"9{uuid.uuid4().int % 10**9:09d}", "upi_id": upi or f"user{n}@yogii",
                   "password": PASSWORD}
        r = client.post("/api/auth/register", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        return ApiUser(client, body["user"], body["csrf_token"])

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def seeded_directory(db):
    """Fictional directory payees used across tests (a merchant, a contact, a watchlisted payee)."""
    from backend.core.encryption import encryption_service as enc
    from backend.database.models import Recipient
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    rows = [("Fresh Market", "freshmarket@merchant", "P2M", False), ("Rahul Verma", "rahul@upi", "P2P", False),
            ("crypto_drain", "crypto_drain@unknown", "P2P", True)]
    for name, upi, kind, watch in rows:
        db.add(Recipient(name_enc=enc.encrypt(name), upi_id_enc=enc.encrypt(upi), upi_id_lookup_hash=enc.blind_index(upi),
                         recipient_type=kind, on_watchlist=watch, is_fictional_demo=True,
                         created_at=now - timedelta(days=3 if watch else 500)))
    db.commit()
    return {r[1]: r for r in rows}
