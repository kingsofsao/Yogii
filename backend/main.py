"""Yogii API: simulated payments with a prototype fraud-risk check.

Startup fails closed: unsafe configuration, a live-mode request without an
authorised adapter, or a missing risk model stops the server with a clear
message instead of degrading silently.
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.config import settings
from backend.core.services import init_services
from backend.database.database import Base, SessionLocal, engine
from backend.domain.payment_service import PaymentError
from backend.ml.inference import ModelNotAvailableError, inference_service

from backend.api.auth import router as auth_router
from backend.api.dashboard import router as dashboard_router
from backend.api.health import router as health_router
from backend.api.integrations import router as integrations_router
from backend.api.me import router as me_router
from backend.api.model_info import router as model_router
from backend.api.payments import router as payments_router
from backend.api.recipients import router as recipients_router
from backend.api.settings import router as settings_router

log = logging.getLogger("yogii")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/api/docs") or request.url.path.startswith("/api/openapi"):
            h["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                                            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; img-src 'self' data: "
                                            "fastapi.tiangolo.com; frame-ancestors 'none'")
        else:
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            h["Cache-Control"] = "no-store"
        if settings.is_production:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def _register_model_metadata() -> None:
    from backend.database.models import ModelMetadata
    meta = inference_service.metadata
    db = SessionLocal()
    try:
        db.query(ModelMetadata).update({ModelMetadata.is_active: False})
        row = db.query(ModelMetadata).filter(ModelMetadata.model_version == meta["model_version"]).first()
        if row is None:
            row = ModelMetadata(model_version=meta["model_version"],
                                artifact_location=str(inference_service.artifact_dir),
                                metrics_json=json.dumps(meta.get("metrics", {})),
                                feature_schema_version=meta["feature_schema_version"], is_synthetic=True)
            db.add(row)
        row.is_active = True
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    init_services()  # raises for live mode: no authorised adapter exists
    if settings.DB_AUTO_CREATE:
        Base.metadata.create_all(bind=engine)
    try:
        inference_service.load_model()
    except ModelNotAvailableError as exc:
        log.error("Risk model unavailable: %s", exc)
        raise
    _register_model_metadata()
    if settings.SEED_DEMO_DATA_ON_STARTUP:
        from backend.scripts.seed import seed_if_empty
        seed_if_empty()
    log.info("Yogii API started in %s mode.", "SIMULATION" if settings.is_simulation else "LIVE")
    yield


app = FastAPI(
    title="Yogii API (simulation)",
    description=("Simulated UPI-style payments with a prototype fraud-risk assessment. Not connected to any bank, "
                 "NPCI or UPI. Not approved, certified or able to move real money."),
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH"],
                   allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"])


@app.exception_handler(PaymentError)
async def _payment_error(_: Request, exc: PaymentError):
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status_code)


@app.exception_handler(ModelNotAvailableError)
async def _model_error(_: Request, exc: ModelNotAvailableError):
    return JSONResponse({"detail": "The risk model is unavailable, so payments can't be assessed right now.",
                         "code": "model_unavailable"}, status_code=503)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    # Never echo submitted values back (they could contain something sensitive).
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "Invalid value")}
              for e in exc.errors()]
    return JSONResponse({"detail": "Please check the highlighted fields.", "errors": errors, "code": "invalid_input"},
                        status_code=422)


for r in (auth_router, me_router, dashboard_router, recipients_router, payments_router, model_router,
          settings_router, health_router, integrations_router):
    app.include_router(r, prefix="/api")
