from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.core.config import settings
from backend.database.database import engine, Base, SessionLocal
from backend.ml.inference import inference_service
from backend.ml.train import train_and_evaluate
from backend.scripts.seed import seed_fictional_demo_data

# Import API Routers
from backend.api.auth import router as auth_router
from backend.api.me import router as me_router
from backend.api.dashboard import router as dashboard_router
from backend.api.recipients import router as recipients_router
from backend.api.payments import router as payments_router
from backend.api.model_info import router as model_router
from backend.api.settings import router as settings_router
from backend.api.health import router as health_router

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security headers to all responses:
    - Strict X-Content-Type-Options
    - Clickjacking frame protection
    - Referrer-Policy
    - X-XSS-Protection
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database schema is present
    Base.metadata.create_all(bind=engine)

    # Ensure XGBoost model is trained and loaded
    model_path = Path(settings.MODEL_PATH)
    if not model_path.exists():
        print(f"XGBoost model artifact not found at {model_path}. Training synthetic model...")
        train_and_evaluate(output_dir=str(model_path.parent))

    inference_service.load_model()
    print("XGBoost fraud risk inference service initialized.")

    # Seed fictional demo data if database is fresh
    db = SessionLocal()
    try:
        seed_fictional_demo_data(db)
    finally:
        db.close()

    yield

app = FastAPI(
    title="Yogii - Secure Digital Payment & Fraud Risk Platform",
    description=(
        "Yogii Digital Payment Engine (SIMULATION MODE ONLY). "
        "Provides end-to-end payment state machine, AES-256-GCM encryption, "
        "HMAC blind indexing, transaction graph analysis, and XGBoost fraud scoring."
    ),
    version="1.0.0",
    lifespan=lifespan
)

# Apply Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# Apply Restrictive CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount Routers under /api
app.include_router(auth_router, prefix="/api")
app.include_router(me_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(recipients_router, prefix="/api")
app.include_router(payments_router, prefix="/api")
app.include_router(model_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(health_router, prefix="/api")
