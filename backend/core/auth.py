"""Session tokens.

The browser receives a short-lived signed JWT in an HttpOnly, SameSite=Strict
cookie, so JavaScript can't read it. Each token carries a random CSRF value;
state-changing requests must echo it in the X-CSRF-Token header (double
submit, bound to the token). The `tv` claim must match users.token_version,
which lets "sign out everywhere" revoke every session server-side.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status
from fastapi.responses import Response

from backend.core.config import settings

ISSUER = "yogii"


def create_session_token(user_id: int, token_version: int) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    csrf = secrets.token_urlsafe(24)
    claims = {"sub": str(user_id), "tv": token_version, "csrf": csrf, "jti": secrets.token_hex(8),
              "iat": now, "exp": expires, "iss": ISSUER, "typ": "session"}
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), csrf, expires


def decode_session_token(token: str) -> Dict[str, Any]:
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], issuer=ISSUER,
                            options={"require": ["exp", "iat", "sub", "iss"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Please sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    if claims.get("typ") != "session":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    return claims


def set_session_cookies(response: Response, token: str, csrf: str, expires: datetime) -> None:
    max_age = int((expires - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(settings.SESSION_COOKIE_NAME, token, max_age=max_age, httponly=True,
                        secure=settings.COOKIE_SECURE, samesite="strict", path="/api")
    # Readable by the frontend so it can send X-CSRF-Token; useless without the HttpOnly session cookie.
    response.set_cookie(settings.CSRF_COOKIE_NAME, csrf, max_age=max_age, httponly=False,
                        secure=settings.COOKIE_SECURE, samesite="strict", path="/")


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/api")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")


def csrf_matches(expected: Optional[str], provided: Optional[str]) -> bool:
    return bool(expected and provided and secrets.compare_digest(expected, provided))
