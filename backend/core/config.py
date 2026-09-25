import os
from typing import List

class Settings:
    APP_NAME: str = "Yogii"
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("true", "1")

    # Payment Rail Mode & Feature Flag
    # Hardcoded safety invariant: default is simulation, live UPI requires authorized sponsor-bank onboarding
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "simulation")
    LIVE_UPI_ENABLED: bool = os.getenv("LIVE_UPI_ENABLED", "false").lower() in ("true", "1")

    # Database & Redis
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/yogii.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Security & Keys
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-yogii-jwt-dev-key-change-in-production-12345")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRY", "1440"))  # 24 hours

    YOGII_ENCRYPTION_KEY: str = os.getenv("YOGII_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    YOGII_LOOKUP_HMAC_KEY: str = os.getenv("YOGII_LOOKUP_HMAC_KEY", "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210")
    YOGII_KEY_VERSION: str = os.getenv("YOGII_KEY_VERSION", "v1")

    # Risk Engine & Model
    MODEL_PATH: str = os.getenv("MODEL_PATH", "backend/model/fraud_model.json")
    MODEL_VERSION: str = os.getenv("MODEL_VERSION", "1.0.0-synthetic")

    # CORS
    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000,*").split(",")
        if origin.strip()
    ]

settings = Settings()
