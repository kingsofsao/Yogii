from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.core.auth import csrf_matches, decode_session_token
from backend.core.config import settings
from backend.core.rate_limit import enforce
from backend.database.database import get_db
from backend.database.models import User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Authenticate from the HttpOnly session cookie and enforce CSRF on unsafe methods."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    claims = decode_session_token(token)
    if request.method not in SAFE_METHODS and not csrf_matches(claims.get("csrf"), request.headers.get("x-csrf-token")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token.")
    try:
        user_id = int(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    user = db.get(User, user_id)
    if user is None or user.token_version != claims.get("tv"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again.")
    if user.status != "ACTIVE":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is not active.")
    request.state.session_claims = claims
    return user


def user_rate_limit(action: str, max_requests: int, window_seconds: int):
    """Per-user limit for authenticated endpoints."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        enforce(f"{action}:user:{user.id}", max_requests, window_seconds, action)
        return user
    return dependency
