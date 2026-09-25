import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, HTTPException, status

class InMemoryRateLimiter:
    """
    Sliding window rate limiter.
    Stores timestamps per client key and cleans expired windows.
    Also supports fallback if Redis is unavailable.
    """
    def __init__(self):
        # key -> list of timestamps
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        window_start = now - window_seconds

        # Clean timestamps older than window
        timestamps = [ts for ts in self.requests[key] if ts > window_start]
        self.requests[key] = timestamps

        if len(timestamps) >= max_requests:
            retry_after = int(window_seconds - (now - timestamps[0])) if timestamps else window_seconds
            return False, max(1, retry_after)

        self.requests[key].append(now)
        return True, 0

limiter = InMemoryRateLimiter()

def rate_limit(action_name: str, max_requests: int = 10, window_seconds: int = 60):
    """
    FastAPI dependency factory to enforce rate limits per IP/action.
    """
    async def dependency(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        # Combine IP and action
        key = f"{action_name}:{client_ip}"
        allowed, retry_after = limiter.is_allowed(key, max_requests, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {action_name}. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )
        return True
    return dependency
