"""Authentication, authorisation, CSRF, input validation, secret rejection and rate limits."""

import pytest

from backend.tests.conftest import PASSWORD, new_client


def register(client, **over):
    payload = {"full_name": "Asha Rao", "email": "asha@example.com", "phone": "9812345678",
               "upi_id": "asha@yogii", "password": PASSWORD, **over}
    return client.post("/api/auth/register", json=payload)


def test_register_sets_httponly_session_cookie_and_simulated_balance():
    with new_client() as c:
        r = register(c)
        assert r.status_code == 201
        body = r.json()
        assert "access_token" not in body and body["mode"] == "SIMULATION"
        cookie = r.headers.get_list("set-cookie")
        session = next(h for h in cookie if h.startswith("yogii_session="))
        assert "HttpOnly" in session and "samesite=strict" in session.lower()
        me = c.get("/api/me").json()
        assert me["simulated_balance"] == "50000.00" and me["is_simulated"] is True


@pytest.mark.parametrize("field,value", [
    ("password", "short1A"), ("password", "alllowercase123"), ("phone", "12345"), ("phone", "5812345678"),
    ("email", "not-an-email"), ("upi_id", "asha@okaxis"), ("upi_id", "bad upi@yogii"), ("full_name", "<script>"),
])
def test_register_validation(field, value):
    with new_client() as c:
        r = register(c, **{field: value})
        assert r.status_code == 422
        assert value not in r.text  # submitted values are never echoed back


def test_duplicate_registration_rejected():
    with new_client() as c:
        assert register(c).status_code == 201
        assert register(c, upi_id="other@yogii", phone="9812345670").status_code == 409


@pytest.mark.parametrize("secret_field", ["upi_pin", "otp", "cvv", "card_number", "bank_password", "mpin"])
def test_secret_fields_are_refused_everywhere(make_user, secret_field):
    with new_client() as c:
        r = register(c, **{secret_field: "1234"})
        assert r.status_code == 422 and "1234" not in r.text
    u = make_user()
    r = u.post("/api/payments/assess", {"recipient_upi": "rahul@upi", "amount": 10,
                                         "simulated_context": {"device": "primary", secret_field: "1234"}},
               key="secret-test-key")
    assert r.status_code == 422


def test_login_with_email_phone_or_upi_and_generic_errors(make_user):
    with new_client() as c:
        register(c)
    for ident in ("asha@example.com", "ASHA@example.com", "9812345678", "+91 98123 45678", "asha@yogii"):
        with new_client() as c:
            assert c.post("/api/auth/login", json={"identifier": ident, "password": PASSWORD}).status_code == 200
    with new_client() as c:
        wrong_pw = c.post("/api/auth/login", json={"identifier": "asha@yogii", "password": "Wrong123456"})
        no_user = c.post("/api/auth/login", json={"identifier": "nobody@yogii", "password": "Wrong123456"})
        assert wrong_pw.status_code == no_user.status_code == 401
        assert wrong_pw.json()["detail"] == no_user.json()["detail"]


def test_account_lockout_after_repeated_failures():
    with new_client() as c:
        register(c)
    with new_client() as c:
        for _ in range(5):
            assert c.post("/api/auth/login", json={"identifier": "asha@yogii", "password": "Nope1234567"}).status_code == 401
        r = c.post("/api/auth/login", json={"identifier": "asha@yogii", "password": PASSWORD})
        assert r.status_code == 429  # locked even with the right password


def test_login_rate_limit_per_ip():
    with new_client() as c:
        codes = [c.post("/api/auth/login", json={"identifier": f"x{i}@yogii", "password": "whatever1A"}).status_code
                 for i in range(11)]
        assert codes[-1] == 429 and "Retry-After" in c.post(
            "/api/auth/login", json={"identifier": "y@yogii", "password": "whatever1A"}).headers


def test_assessment_rate_limit(make_user, seeded_directory):
    u = make_user()
    codes = [u.assess("freshmarket@merchant", 10).status_code for _ in range(21)]
    assert codes[:20].count(201) == 20 and codes[20] == 429


@pytest.mark.parametrize("method,url", [("get", "/api/me"), ("get", "/api/dashboard"), ("get", "/api/payments"),
                                        ("get", "/api/payments/1"), ("get", "/api/payments/1/status"),
                                        ("get", "/api/recipients/lookup?q=rahul@upi"), ("get", "/api/settings"),
                                        ("get", "/api/model/info"), ("post", "/api/payments/assess"),
                                        ("post", "/api/payments"), ("patch", "/api/settings")])
def test_protected_routes_require_sign_in(method, url):
    with new_client() as c:
        # Unsafe methods may fail body validation first (422); either way nothing is processed.
        assert getattr(c, method)(url).status_code in ((401,) if method == "get" else (401, 422))


def test_csrf_required_for_state_changes(make_user, seeded_directory):
    u = make_user()
    r = u.client.post("/api/payments/assess", json={"recipient_upi": "rahul@upi", "amount": 10},
                      headers={"Idempotency-Key": "csrf-test-key"})
    assert r.status_code == 403
    r = u.client.post("/api/payments/assess", json={"recipient_upi": "rahul@upi", "amount": 10},
                      headers={"Idempotency-Key": "csrf-test-key", "X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert u.assess("rahul@upi", 10).status_code == 201


def test_logout_everywhere_revokes_sessions(make_user):
    u = make_user()
    with new_client() as other:
        other.cookies.update(u.client.cookies)  # same session in a second "browser"
        assert other.get("/api/me").status_code == 200
        assert u.post("/api/auth/logout-all").status_code == 200
        assert other.get("/api/me").status_code == 401


def test_tampered_or_foreign_token_rejected(make_user):
    import jwt
    u = make_user()
    forged = jwt.encode({"sub": str(u.id), "tv": 0, "typ": "session", "iss": "yogii", "iat": 1, "exp": 9999999999},
                        "not-the-server-secret", algorithm="HS256")
    with new_client() as c:
        c.cookies.set("yogii_session", forged)
        assert c.get("/api/me").status_code == 401


def test_recipient_lookup_reveals_no_private_data(make_user, seeded_directory):
    a, b = make_user("Asha Rao"), make_user("Bala Iyer", phone="9811111111")
    r = a.get(f"/api/recipients/lookup?q={b.profile['upi_id']}").json()
    assert r == {"name": "Bala Iyer", "upi_id": b.profile["upi_id"], "payment_type": "P2P", "kind": "yogii_user",
                 "merchant_category": None, "is_fictional_demo": False, "notice": None}
    assert a.get("/api/recipients/lookup?q=9811111111").json()["name"] == "Bala Iyer"
    unknown = a.get("/api/recipients/lookup?q=someone@okaxis").json()
    assert unknown["kind"] == "unverified" and "Double-check" in unknown["notice"]
    assert a.get("/api/recipients/lookup?q=freshmarket@merchant").json()["payment_type"] == "P2M"
    assert a.get("/api/recipients/lookup?q=abc").status_code == 422


def test_security_headers(make_user):
    u = make_user()
    h = u.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["content-security-policy"].startswith("default-src 'none'") and h["cache-control"] == "no-store"


def test_user_sees_own_security_events(make_user):
    with new_client() as c:
        register(c)
    with new_client() as c:
        c.post("/api/auth/login", json={"identifier": "asha@yogii", "password": "Wrong123456"})
        c.post("/api/auth/login", json={"identifier": "asha@yogii", "password": PASSWORD})
        events = c.get("/api/me/security-events").json()
        assert events[0]["event_type"] == "login_failure"
