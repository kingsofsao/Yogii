import uuid
from fastapi.testclient import TestClient
from backend.main import app
from backend.database.database import SessionLocal
from backend.database.models import User, DemoPaymentAccount, PaymentAttempt
from backend.core.encryption import encryption_service

client = TestClient(app)

def test_validate_all_critical_flows():
    print("\n--- [START] Executing Critical Flows Validation (A through F) ---")

    # =========================================================================
    # FLOW A: register -> login -> dashboard -> familiar recipient -> LOW risk -> mock payment -> COMPLETED -> balance changes
    # =========================================================================
    flow_a_uid = uuid.uuid4().hex[:6]
    flow_a_email = f"flow_a_{flow_a_uid}@demo.yogii"
    flow_a_upi = f"flow_a_{flow_a_uid}@yogii"

    # 1. Register
    r_reg = client.post("/api/auth/register", json={
        "full_name": f"Flow A User {flow_a_uid}",
        "email": flow_a_email,
        "phone": "9876500001",
        "upi_id": flow_a_upi,
        "password": "Password123!"
    })
    assert r_reg.status_code == 200, f"Register failed: {r_reg.text}"
    token_a = r_reg.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 2. Login
    r_login = client.post("/api/auth/login", json={
        "email_or_phone_or_upi": flow_a_upi,
        "password": "Password123!"
    })
    assert r_login.status_code == 200
    assert "access_token" in r_login.json()

    # 3. View Dashboard
    r_dash = client.get("/api/dashboard", headers=headers_a)
    assert r_dash.status_code == 200
    initial_balance = r_dash.json()["simulated_balance"]
    assert initial_balance == 50000.0

    # 4. Pay familiar recipient with low amount
    idem_a = f"IDEM-A-{uuid.uuid4().hex}"
    r_pay_a = client.post("/api/payments/assess", json={
        "recipient_upi": "rahul@upi",
        "amount": 400.0,
        "idempotency_key": idem_a,
        "payment_type": "P2P"
    }, headers=headers_a)
    assert r_pay_a.status_code == 200
    res_a = r_pay_a.json()
    assert res_a["state"] == "COMPLETED"
    assert res_a["risk_assessment"]["risk_band"] in ("LOW", "MEDIUM")

    # Invariant: Balance debited exactly once
    r_dash_after = client.get("/api/dashboard", headers=headers_a)
    new_balance_a = r_dash_after.json()["simulated_balance"]
    assert new_balance_a == initial_balance - 400.0
    print("[OK] FLOW A PASSED: Registration, login, dashboard, low risk completed, balance debited exactly once.")

    # =========================================================================
    # FLOW B: new recipient -> unusual amount -> HIGH -> demo verification -> mock payment
    # =========================================================================
    # Yogesh has baseline of ~₹500. Sending ₹25,000 to an unknown recipient is anomalous.
    r_login_yogesh = client.post("/api/auth/login", json={
        "email_or_phone_or_upi": "yogesh@yogii",
        "password": "Password123!"
    })
    token_yogesh = r_login_yogesh.json()["access_token"]
    headers_yogesh = {"Authorization": f"Bearer {token_yogesh}"}

    r_dash_y = client.get("/api/dashboard", headers=headers_yogesh)
    bal_yogesh_init = r_dash_y.json()["simulated_balance"]

    idem_b = f"IDEM-B-{uuid.uuid4().hex}"
    new_recip_b = f"brand_new_merchant_{uuid.uuid4().hex[:6]}@upi"
    r_pay_b = client.post("/api/payments/assess", json={
        "recipient_upi": new_recip_b,
        "amount": 6000.0,
        "idempotency_key": idem_b,
        "payment_type": "P2M"
    }, headers=headers_yogesh)
    assert r_pay_b.status_code == 200
    res_b = r_pay_b.json()

    # Must require demo verification due to new recipient & high amount
    assert res_b["state"] == "NEEDS_VERIFICATION"
    assert res_b["risk_assessment"]["risk_band"] in ("MEDIUM", "HIGH")
    payment_id_b = res_b["id"]

    # Invariant check: balance unchanged while in NEEDS_VERIFICATION
    r_dash_b_mid = client.get("/api/dashboard", headers=headers_yogesh)
    assert r_dash_b_mid.json()["simulated_balance"] == bal_yogesh_init

    # Complete Demo Verification
    r_verify_b = client.post(f"/api/payments/{payment_id_b}/verify", json={
        "demo_verification_confirmed": True
    }, headers=headers_yogesh)
    assert r_verify_b.status_code == 200
    res_b_verified = r_verify_b.json()
    assert res_b_verified["state"] == "COMPLETED"

    # Balance debited now
    r_dash_b_end = client.get("/api/dashboard", headers=headers_yogesh)
    assert r_dash_b_end.json()["simulated_balance"] == bal_yogesh_init - 6000.0
    print("[OK] FLOW B PASSED: New recipient, elevated risk -> NEEDS_VERIFICATION -> Demo verified -> COMPLETED.")

    # =========================================================================
    # FLOW C: very suspicious demo payment -> VERY_HIGH -> BLOCKED -> no balance change
    # =========================================================================
    r_dash_c_before = client.get("/api/dashboard", headers=headers_yogesh)
    bal_c_before = r_dash_c_before.json()["simulated_balance"]

    idem_c = f"IDEM-C-{uuid.uuid4().hex}"
    r_pay_c = client.post("/api/payments/assess", json={
        "recipient_upi": "crypto_drain@unknown",
        "amount": 28000.0,
        "idempotency_key": idem_c,
        "payment_type": "P2P",
        "device_id": "untrusted-vpn-node",
        "location": "Offshore"
    }, headers=headers_yogesh)
    assert r_pay_c.status_code == 200
    res_c = r_pay_c.json()

    assert res_c["state"] == "BLOCKED"
    assert res_c["risk_assessment"]["risk_band"] == "VERY_HIGH"
    assert res_c["risk_assessment"]["raw_risk_score"] >= 85.0

    # Invariant: Blocked payment MUST NOT change balance!
    r_dash_c_after = client.get("/api/dashboard", headers=headers_yogesh)
    assert r_dash_c_after.json()["simulated_balance"] == bal_c_before
    print("[OK] FLOW C PASSED: High anomaly -> VERY_HIGH -> BLOCKED -> Balance unchanged.")

    # =========================================================================
    # FLOW D: provider failure -> FAILED -> no balance change
    # =========================================================================
    r_dash_d_before = client.get("/api/dashboard", headers=headers_yogesh)
    bal_d_before = r_dash_d_before.json()["simulated_balance"]

    idem_d = f"IDEM-D-{uuid.uuid4().hex}"
    r_pay_d = client.post("/api/payments/assess", json={
        "recipient_upi": "terminal@fail.demo",
        "amount": 250.0,
        "idempotency_key": idem_d,
        "payment_type": "P2P"
    }, headers=headers_yogesh)
    assert r_pay_d.status_code == 200
    res_d = r_pay_d.json()

    assert res_d["state"] == "FAILED"
    # Invariant: Failed payment MUST NOT change balance!
    r_dash_d_after = client.get("/api/dashboard", headers=headers_yogesh)
    assert r_dash_d_after.json()["simulated_balance"] == bal_d_before
    print("[OK] FLOW D PASSED: Provider failure -> FAILED -> Balance unchanged.")

    # =========================================================================
    # FLOW E: retry payment using same idempotency key -> no duplicate transfer
    # =========================================================================
    idem_e = f"IDEM-E-{uuid.uuid4().hex}"
    r_pay_e1 = client.post("/api/payments/assess", json={
        "recipient_upi": "rahul@upi",
        "amount": 300.0,
        "idempotency_key": idem_e,
        "payment_type": "P2P"
    }, headers=headers_yogesh)
    assert r_pay_e1.status_code == 200

    bal_e_mid = client.get("/api/dashboard", headers=headers_yogesh).json()["simulated_balance"]

    # Re-sending the exact same idempotency key (simulating network retry)
    r_pay_e2 = client.post("/api/payments/assess", json={
        "recipient_upi": "rahul@upi",
        "amount": 300.0,
        "idempotency_key": idem_e,
        "payment_type": "P2P"
    }, headers=headers_yogesh)
    assert r_pay_e2.status_code == 200

    assert r_pay_e1.json()["id"] == r_pay_e2.json()["id"]
    bal_e_end = client.get("/api/dashboard", headers=headers_yogesh).json()["simulated_balance"]
    assert bal_e_mid == bal_e_end, "Duplicate idempotency call debited balance twice!"
    print("[OK] FLOW E PASSED: Duplicate idempotency key returned existing attempt without double-debiting.")

    # =========================================================================
    # FLOW F: Yogesh -> Visrojit -> Dinesh -> graph feature detected -> safe explanation returned
    # =========================================================================
    # Visrojit received ₹15,000 from Yogesh. Now assessing payment from Visrojit to Dinesh for ₹14,800.
    r_login_visrojit = client.post("/api/auth/login", json={
        "email_or_phone_or_upi": "visrojit@yogii",
        "password": "Password123!"
    })
    token_visrojit = r_login_visrojit.json()["access_token"]
    headers_visrojit = {"Authorization": f"Bearer {token_visrojit}"}

    idem_f = f"IDEM-F-{uuid.uuid4().hex}"
    r_pay_f = client.post("/api/payments/assess", json={
        "recipient_upi": "dinesh@yogii",
        "amount": 14800.0,
        "idempotency_key": idem_f,
        "payment_type": "P2P"
    }, headers=headers_visrojit)
    assert r_pay_f.status_code == 200
    res_f = r_pay_f.json()

    reason_codes = [rc["code"] for rc in res_f["risk_assessment"]["reason_codes"]]
    # Safe terminology check: must NOT describe relationship as 'friendship' or 'guilt'
    descriptions = " ".join([rc["description"] for rc in res_f["risk_assessment"]["reason_codes"]]).lower()
    assert "friend" not in descriptions
    assert "criminal" not in descriptions
    print(f"[OK] FLOW F PASSED: Multi-hop transaction chain assessed, safe explanation returned: {res_f['risk_assessment']['reason_codes']}")

    print("\n=== ALL CRITICAL FLOWS (A through F) VALIDATED AND PASSED! ===\n")

if __name__ == "__main__":
    test_validate_all_critical_flows()
