import uuid
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database.database import SessionLocal
from backend.database.models import User

client = TestClient(app)

def test_health_and_ready_endpoints():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["payment_mode"] == "simulation"

    r_ready = client.get("/api/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ready"

def test_forbidden_credentials_rejected_at_validation():
    # Invariant: Yogii must never accept, process, or store UPI PIN or OTP
    payload_with_pin = {
        "full_name": "Attacker",
        "email": "attacker@test.com",
        "phone": "9999888877",
        "upi_id": "attacker@upi",
        "password": "Password123!",
        "upi_pin": "1234"  # FORBIDDEN
    }
    r = client.post("/api/auth/register", json=payload_with_pin)
    assert r.status_code == 422
    assert "Forbidden security credential" in r.text

    payload_with_otp = {
        "email_or_phone_or_upi": "attacker@upi",
        "password": "Password123!",
        "otp": "654321"  # FORBIDDEN
    }
    r2 = client.post("/api/auth/login", json=payload_with_otp)
    assert r2.status_code == 422
    assert "Forbidden security credential" in r2.text

def test_sensitive_user_fields_not_in_plaintext_in_database():
    unique_suffix = uuid.uuid4().hex[:6]
    test_email = f"secure_{unique_suffix}@yogii.demo"
    test_phone = "9876500000"
    test_name = f"Secure User {unique_suffix}"

    reg_payload = {
        "full_name": test_name,
        "email": test_email,
        "phone": test_phone,
        "upi_id": f"secure_{unique_suffix}@yogii",
        "password": "Password123!"
    }
    r = client.post("/api/auth/register", json=reg_payload)
    assert r.status_code == 200

    # Query raw database row to inspect persisted bytes
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email_lookup_hash == r.json()["user"]["email"]).first()
        # Even if not found by raw email, look by ID
        user_row = db.query(User).filter(User.id == r.json()["user"]["id"]).first()
        assert user_row is not None
        # INVARIANT: Database columns must NOT be equal to plaintext!
        assert user_row.full_name_enc != test_name
        assert user_row.email_enc != test_email
        assert user_row.phone_enc != test_phone
        assert user_row.full_name_enc.startswith("v1$")
        assert user_row.password_hash.startswith("$argon2id$")
    finally:
        db.close()

def test_unauthorized_access_rejected():
    r = client.get("/api/me")
    assert r.status_code == 401

    r_dash = client.get("/api/dashboard")
    assert r_dash.status_code == 401

def test_end_to_end_user_journey():
    # 1. Register
    uid = uuid.uuid4().hex[:6]
    reg_payload = {
        "full_name": f"E2E Tester {uid}",
        "email": f"e2e_{uid}@test.com",
        "phone": "9812345678",
        "upi_id": f"e2e_{uid}@yogii",
        "password": "Password123!"
    }
    r_reg = client.post("/api/auth/register", json=reg_payload)
    assert r_reg.status_code == 200
    token = r_reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. View /api/me
    r_me = client.get("/api/me", headers=headers)
    assert r_me.status_code == 200
    assert r_me.json()["full_name"] == f"E2E Tester {uid}"
    assert r_me.json()["simulated_balance"] == 50000.0

    # 3. View /api/dashboard
    r_dash = client.get("/api/dashboard", headers=headers)
    assert r_dash.status_code == 200
    assert r_dash.json()["is_simulation_mode"] is True

    # 4. Assess Payment
    assess_payload = {
        "recipient_upi": "rahul@upi",
        "amount": 500.0,
        "idempotency_key": "IDEM-TEST-" + uuid.uuid4().hex,
        "payment_type": "P2P"
    }
    r_pay = client.post("/api/payments/assess", json=assess_payload, headers=headers)
    assert r_pay.status_code == 200
    pay_data = r_pay.json()
    assert pay_data["state"] in ("COMPLETED", "NEEDS_VERIFICATION")
    assert pay_data["is_simulated"] is True

    # 5. Check History
    r_hist = client.get("/api/payments", headers=headers)
    assert r_hist.status_code == 200
    assert len(r_hist.json()) >= 1

def test_user_cannot_enable_live_upi():
    # Login as seed user
    login_payload = {
        "email_or_phone_or_upi": "yogesh@yogii",
        "password": "Password123!"
    }
    r_login = client.post("/api/auth/login", json=login_payload)
    assert r_login.status_code == 200
    headers = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

    # Attempt to enable live UPI (Must be forbidden)
    r_patch = client.patch("/api/settings", json={"live_upi_enabled": True}, headers=headers)
    assert r_patch.status_code == 403
    assert "Permission denied" in r_patch.text
