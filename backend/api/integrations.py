"""Inbound status callbacks from the payment rail.

Callbacks are only trusted after `PaymentProvider.verify_callback` succeeds
(signature + timestamp for the mock rail; whatever the sponsor bank specifies
for a future live adapter). Unsigned or tampered callbacks are rejected with
401 and recorded; replays of an already-processed event are ignored.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.core.rate_limit import rate_limit
from backend.core.services import get_payment_service
from backend.database.database import get_db

router = APIRouter(prefix="/integrations/payments", tags=["Payment rail callbacks"])
MAX_CALLBACK_BYTES = 16 * 1024


@router.post("/callback", dependencies=[Depends(rate_limit("provider_callback", 120, 60))])
async def provider_callback(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if len(body) > MAX_CALLBACK_BYTES:
        return JSONResponse({"status": "rejected", "detail": "Payload too large."}, status_code=413)
    code, payload = get_payment_service().handle_callback(db, dict(request.headers), body)
    return JSONResponse(payload, status_code=code)
