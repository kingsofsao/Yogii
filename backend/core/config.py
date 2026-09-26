"""Server-side configuration for Yogii.

Everything here comes from environment variables set by the deployment. None of
it can be changed through the API or the database: in particular, the live
payment flag is read once from the environment and there is no endpoint, user
setting or `app_configurations` row that can switch it on.

Yogii is a prototype. It runs in SIMULATION mode, and live mode cannot start
until an authorised sponsor-bank adapter has been implemented and configured
(see docs/INTEGRATION_BOUNDARY.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


class ConfigurationError(RuntimeError):
    """Raised at startup when the deployment configuration is unsafe or inconsistent."""


# Development defaults. They are rejected when APP_ENV=production.
DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0000000000000000"
DEV_ENCRYPTION_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
DEV_HMAC_KEY = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
DEV_MOCK_WEBHOOK_SECRET = "dev-only-mock-provider-webhook-secret"
_KNOWN_DEV_VALUES = {
    DEV_JWT_SECRET, DEV_ENCRYPTION_KEY, DEV_HMAC_KEY, DEV_MOCK_WEBHOOK_SECRET,
    # values that shipped in earlier versions of .env.example / docker-compose.yml
    "super-secret-yogii-jwt-dev-key-change-in-production-12345",
}

ALLOWED_HISTORY_WINDOWS = (7, 30, 90)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else float(raw)


def _list(name: str, default: str) -> List[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass
class Settings:
    APP_NAME: str = "Yogii"
    APP_ENV: str = field(default_factory=lambda: os.getenv("APP_ENV", "development").lower())

    # --- Payment rail -----------------------------------------------------------
    # PAYMENT_MODE=simulation is the only mode that can run today.
    PAYMENT_MODE: str = field(default_factory=lambda: os.getenv("PAYMENT_MODE", "simulation").lower())
    # Second, independent server-side switch. Both must be set for live mode, and
    # live mode additionally needs an implemented, configured sponsor-bank adapter.
    LIVE_PAYMENTS_ENABLED: bool = field(default_factory=lambda: _bool("LIVE_PAYMENTS_ENABLED", _bool("LIVE_UPI_ENABLED", False)))
    SPONSOR_BANK_ADAPTER: str = field(default_factory=lambda: os.getenv("SPONSOR_BANK_ADAPTER", "").strip())
    MOCK_PROVIDER_WEBHOOK_SECRET: str = field(default_factory=lambda: os.getenv("MOCK_PROVIDER_WEBHOOK_SECRET", DEV_MOCK_WEBHOOK_SECRET))
    CALLBACK_TOLERANCE_SECONDS: int = field(default_factory=lambda: _int("CALLBACK_TOLERANCE_SECONDS", 300))

    # --- Database ---------------------------------------------------------------
    DATABASE_URL: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./backend/data/yogii.db"))
    # create_all() is a local-development convenience only; real deployments use Alembic.
    DB_AUTO_CREATE: bool = field(default_factory=lambda: _bool("DB_AUTO_CREATE", os.getenv("DATABASE_URL", "sqlite").startswith("sqlite")))
    SEED_DEMO_DATA_ON_STARTUP: bool = field(default_factory=lambda: _bool("SEED_DEMO_DATA_ON_STARTUP", False))

    # --- Auth and sessions -------------------------------------------------------
    JWT_SECRET: str = field(default_factory=lambda: os.getenv("JWT_SECRET", DEV_JWT_SECRET))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = field(default_factory=lambda: _int("ACCESS_TOKEN_EXPIRE_MINUTES", _int("JWT_EXPIRY", 30)))
    SESSION_COOKIE_NAME: str = "yogii_session"
    CSRF_COOKIE_NAME: str = "yogii_csrf"
    COOKIE_SECURE: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", os.getenv("APP_ENV", "development").lower() == "production"))
    LOGIN_MAX_FAILURES: int = field(default_factory=lambda: _int("LOGIN_MAX_FAILURES", 5))
    LOGIN_LOCKOUT_SECONDS: int = field(default_factory=lambda: _int("LOGIN_LOCKOUT_SECONDS", 900))
    RATE_LIMIT_ENABLED: bool = field(default_factory=lambda: _bool("RATE_LIMIT_ENABLED", True))

    # --- Encryption --------------------------------------------------------------
    YOGII_ENCRYPTION_KEY: str = field(default_factory=lambda: os.getenv("YOGII_ENCRYPTION_KEY", DEV_ENCRYPTION_KEY))
    YOGII_LOOKUP_HMAC_KEY: str = field(default_factory=lambda: os.getenv("YOGII_LOOKUP_HMAC_KEY", DEV_HMAC_KEY))
    YOGII_KEY_VERSION: str = field(default_factory=lambda: os.getenv("YOGII_KEY_VERSION", "v1"))

    # --- Risk model and prototype policy ----------------------------------------
    MODEL_DIR: str = field(default_factory=lambda: os.getenv("MODEL_DIR", "backend/model"))
    MODEL_VERSION: str = field(default_factory=lambda: os.getenv("MODEL_VERSION", "2.0.0-synthetic"))
    # Yogii prototype thresholds (score 0-100). NOT RBI, NPCI or bank standards.
    RISK_THRESHOLD_MEDIUM: int = field(default_factory=lambda: _int("RISK_THRESHOLD_MEDIUM", 30))
    RISK_THRESHOLD_HIGH: int = field(default_factory=lambda: _int("RISK_THRESHOLD_HIGH", 60))
    RISK_THRESHOLD_VERY_HIGH: int = field(default_factory=lambda: _int("RISK_THRESHOLD_VERY_HIGH", 85))
    RISK_POLICY_VERSION: str = "yogii-prototype-policy-v1"
    FEATURE_HISTORY_DAYS: int = field(default_factory=lambda: _int("FEATURE_HISTORY_DAYS", 30))
    GRAPH_MAX_DEPTH: int = field(default_factory=lambda: _int("GRAPH_MAX_DEPTH", 2))
    GRAPH_WINDOW_MINUTES: int = field(default_factory=lambda: _int("GRAPH_WINDOW_MINUTES", 120))
    GRAPH_AMOUNT_TOLERANCE: float = field(default_factory=lambda: _float("GRAPH_AMOUNT_TOLERANCE", 0.25))

    # --- Simulation limits ---------------------------------------------------------
    MAX_PAYMENT_AMOUNT: int = field(default_factory=lambda: _int("MAX_PAYMENT_AMOUNT", 100000))
    DEMO_STARTING_BALANCE: int = field(default_factory=lambda: _int("DEMO_STARTING_BALANCE", 50000))

    # --- Data retention (days) -----------------------------------------------------
    RETENTION_FEATURE_SNAPSHOT_DAYS: int = field(default_factory=lambda: _int("RETENTION_FEATURE_SNAPSHOT_DAYS", 180))
    RETENTION_SECURITY_EVENT_DAYS: int = field(default_factory=lambda: _int("RETENTION_SECURITY_EVENT_DAYS", 365))
    RETENTION_GRAPH_EDGE_DAYS: int = field(default_factory=lambda: _int("RETENTION_GRAPH_EDGE_DAYS", 90))

    # --- HTTP ------------------------------------------------------------------------
    CORS_ORIGINS: List[str] = field(default_factory=lambda: _list(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_simulation(self) -> bool:
        return self.PAYMENT_MODE == "simulation"

    @property
    def risk_thresholds(self) -> dict:
        return {"MEDIUM": self.RISK_THRESHOLD_MEDIUM, "HIGH": self.RISK_THRESHOLD_HIGH,
                "VERY_HIGH": self.RISK_THRESHOLD_VERY_HIGH}

    def validate(self) -> "Settings":
        """Fail closed on unsafe or inconsistent configuration."""
        errors: List[str] = []
        if self.APP_ENV not in ("development", "test", "production"):
            errors.append("APP_ENV must be development, test or production.")
        if self.PAYMENT_MODE not in ("simulation", "live"):
            errors.append("PAYMENT_MODE must be 'simulation' or 'live'.")
        if self.PAYMENT_MODE == "live":
            if not self.LIVE_PAYMENTS_ENABLED:
                errors.append("PAYMENT_MODE=live requires LIVE_PAYMENTS_ENABLED=true in the server deployment.")
            if not self.SPONSOR_BANK_ADAPTER:
                errors.append("PAYMENT_MODE=live requires SPONSOR_BANK_ADAPTER to name an authorised adapter.")
            if not self.is_production:
                errors.append("PAYMENT_MODE=live is only permitted with APP_ENV=production.")
        if not (0 < self.RISK_THRESHOLD_MEDIUM < self.RISK_THRESHOLD_HIGH < self.RISK_THRESHOLD_VERY_HIGH <= 100):
            errors.append("Risk thresholds must satisfy 0 < MEDIUM < HIGH < VERY_HIGH <= 100.")
        if self.FEATURE_HISTORY_DAYS not in ALLOWED_HISTORY_WINDOWS:
            errors.append("FEATURE_HISTORY_DAYS must be 7, 30 or 90.")
        if self.GRAPH_MAX_DEPTH not in (1, 2, 3):
            errors.append("GRAPH_MAX_DEPTH must be 1, 2 or 3.")
        if "*" in self.CORS_ORIGINS:
            errors.append("CORS_ORIGINS must list explicit origins; '*' is not allowed with credentialed requests.")
        if self.is_production:
            for name in ("JWT_SECRET", "YOGII_ENCRYPTION_KEY", "YOGII_LOOKUP_HMAC_KEY", "MOCK_PROVIDER_WEBHOOK_SECRET"):
                value = getattr(self, name)
                if value in _KNOWN_DEV_VALUES or len(value) < 32:
                    errors.append(f"{name} must be set to a unique secret of at least 32 characters in production.")
            if self.DATABASE_URL.startswith("sqlite"):
                errors.append("Production deployments must use PostgreSQL, not SQLite.")
            if not self.COOKIE_SECURE:
                errors.append("COOKIE_SECURE must be true in production (serve over TLS).")
            if self.DB_AUTO_CREATE:
                errors.append("DB_AUTO_CREATE must be false in production; run Alembic migrations instead.")
        if errors:
            raise ConfigurationError("Unsafe Yogii configuration:\n  - " + "\n  - ".join(errors))
        return self


settings = Settings()


def reload_settings() -> Settings:
    """Re-read the environment (used by tests)."""
    global settings
    fresh = Settings()
    settings.__dict__.update(fresh.__dict__)
    return settings


def mode_label(s: Optional[Settings] = None) -> str:
    s = s or settings
    return "SIMULATION" if s.is_simulation else "LIVE"
