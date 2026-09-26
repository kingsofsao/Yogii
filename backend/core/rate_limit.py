"""Sliding-window rate limiting and login lockout.

In-memory and per process: enough for a single-instance prototype. A
multi-instance deployment should move these counters to a shared store such
as Redis (see docs/DEPLOYMENT.md).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status

from backend.core.config import settings


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> Tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(window - (now - q[0])))
            q.append(now)
            return True, 0

    def count(self, key: str, window: int) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            return len(q)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce(key: str, limit: int, window: int, action: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry = limiter.hit(key, limit, window)
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many {action} requests. Try again in {retry} seconds.",
                            headers={"Retry-After": str(retry)})


def rate_limit(action: str, max_requests: int, window_seconds: int):
    """Per-IP limit, as a FastAPI dependency (used before authentication)."""
    def dependency(request: Request) -> None:
        enforce(f"{action}:ip:{client_ip(request)}", max_requests, window_seconds, action)
    return dependency


# --- login lockout (per identifier, independent of IP) ---------------------------
def login_locked(identifier_hash: str) -> bool:
    return limiter.count(f"loginfail:{identifier_hash}", settings.LOGIN_LOCKOUT_SECONDS) >= settings.LOGIN_MAX_FAILURES


def record_login_failure(identifier_hash: str) -> None:
    limiter.hit(f"loginfail:{identifier_hash}", 10_000, settings.LOGIN_LOCKOUT_SECONDS)


def clear_login_failures(identifier_hash: str) -> None:
    limiter.clear(f"loginfail:{identifier_hash}")
