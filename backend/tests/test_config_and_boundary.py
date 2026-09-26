"""Live payments stay off unless the server deployment says otherwise, and even then can't start."""

import pytest

from backend.core.config import ConfigurationError, Settings, settings
from backend.integrations.payments import MockPaymentProvider, ProviderNotConfiguredError, build_payment_provider
from backend.integrations.payments.sponsor_bank import SponsorBankUPIProvider


def cfg(**overrides) -> Settings:
    s = Settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_default_mode_is_simulation_with_mock_provider():
    assert settings.PAYMENT_MODE == "simulation"
    assert settings.LIVE_PAYMENTS_ENABLED is False
    provider = build_payment_provider(cfg())
    assert isinstance(provider, MockPaymentProvider)
    assert provider.is_live is False


def test_live_mode_requires_server_flag():
    with pytest.raises(ConfigurationError, match="LIVE_PAYMENTS_ENABLED"):
        cfg(PAYMENT_MODE="live", LIVE_PAYMENTS_ENABLED=False, SPONSOR_BANK_ADAPTER="x").validate()


def test_live_mode_only_in_production_and_needs_named_adapter():
    with pytest.raises(ConfigurationError, match="only permitted with APP_ENV=production"):
        cfg(PAYMENT_MODE="live", LIVE_PAYMENTS_ENABLED=True, SPONSOR_BANK_ADAPTER="x").validate()
    with pytest.raises(ConfigurationError, match="SPONSOR_BANK_ADAPTER"):
        cfg(PAYMENT_MODE="live", LIVE_PAYMENTS_ENABLED=True, SPONSOR_BANK_ADAPTER="").validate()


def test_fully_configured_live_mode_still_fails_because_adapter_is_unimplemented():
    secret = "s" * 40
    live = cfg(APP_ENV="production", PAYMENT_MODE="live", LIVE_PAYMENTS_ENABLED=True, SPONSOR_BANK_ADAPTER="bank",
               JWT_SECRET=secret + "1", YOGII_ENCRYPTION_KEY="a" * 64, YOGII_LOOKUP_HMAC_KEY="b" * 64,
               MOCK_PROVIDER_WEBHOOK_SECRET=secret + "2", DATABASE_URL="postgresql://x", COOKIE_SECURE=True,
               DB_AUTO_CREATE=False)
    live.validate()  # configuration itself is consistent...
    with pytest.raises(ProviderNotConfiguredError, match="not implemented"):
        build_payment_provider(live)  # ...but there is no authorised adapter, so it fails closed


def test_sponsor_adapter_cannot_be_constructed():
    with pytest.raises(ProviderNotConfiguredError):
        SponsorBankUPIProvider("any")


def test_production_rejects_development_secrets_and_sqlite():
    with pytest.raises(ConfigurationError) as exc:
        cfg(APP_ENV="production", DATABASE_URL="sqlite:///x.db").validate()
    msg = str(exc.value)
    assert "JWT_SECRET" in msg and "YOGII_ENCRYPTION_KEY" in msg and "PostgreSQL" in msg


def test_invalid_policy_and_graph_settings_rejected():
    with pytest.raises(ConfigurationError, match="thresholds"):
        cfg(RISK_THRESHOLD_MEDIUM=70, RISK_THRESHOLD_HIGH=60).validate()
    with pytest.raises(ConfigurationError, match="GRAPH_MAX_DEPTH"):
        cfg(GRAPH_MAX_DEPTH=4).validate()
    with pytest.raises(ConfigurationError, match="FEATURE_HISTORY_DAYS"):
        cfg(FEATURE_HISTORY_DAYS=14).validate()
    with pytest.raises(ConfigurationError, match="CORS"):
        cfg(CORS_ORIGINS=["*"]).validate()


def test_user_cannot_enable_live_payments_through_the_api(make_user):
    u = make_user("Asha Rao")
    r = u.patch("/api/settings", {"live_payments_enabled": True})
    assert r.status_code == 422
    r = u.patch("/api/settings", {"payment_mode": "live"})
    assert r.status_code == 422
    s = u.get("/api/settings").json()
    assert s["mode"] == "SIMULATION"
    assert s["live_payments_enabled"] is False
    assert s["provider"] == "MockPaymentProvider"
    assert "Not RBI, NPCI or bank standards" in s["thresholds_note"]


def test_preferences_can_be_updated(make_user):
    u = make_user("Asha Rao")
    r = u.patch("/api/settings", {"hide_balance": True, "theme": "dark"})
    assert r.status_code == 200
    assert r.json()["preferences"] == {"hide_balance": True, "notify_on_high_risk": True, "theme": "dark"}
    assert u.get("/api/dashboard").json()["hide_balance"] is True


def test_health_reports_simulation_mode(make_user):
    u = make_user()
    assert u.get("/api/health").json() == {"status": "ok", "mode": "SIMULATION"}
    assert u.get("/api/ready").json()["status"] == "ready"
