"""Portal and device authentication (README-PART-3 section 5). One organisation.

- Portal: ``authorization: Bearer <PORTAL_TOKEN>`` on every portal route, compared
  with ``hmac.compare_digest``. One shared token in ``.env``; per-supervisor
  accounts / SSO are v3.
- Device: ``POST /v1/devices/pair`` is open (rate-limited per client IP) and mints a
  random 32-byte ``device_token``; only its SHA-256 is stored (Part 5's devices
  table). Every other lens route needs the token, and it scopes the device's
  assignments and progress.

Rejected auth is logged at WARN, like rejected CORS origins. Tokens are never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import Request

from .pipeline import PipelineError
from .schemas import PAIR_CODE_ALPHABET

log = logging.getLogger("specs.auth")


class Unauthorized(PipelineError):
    code = "unauthorized"


class RateLimited(PipelineError):
    code = "rate_limited"


def bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header[:7].lower() == "bearer " else ""


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_portal(request: Request) -> None:
    """Raise Unauthorized unless the request carries the portal token."""
    settings = request.app.state.settings
    expected = settings.portal_token.get_secret_value() if settings.portal_token else ""
    if not expected:
        log.warning("portal request rejected: PORTAL_TOKEN is not configured (%s %s)",
                    request.method, request.url.path)
        raise Unauthorized("The portal is disabled: PORTAL_TOKEN is not configured on the relay.")
    if not hmac.compare_digest(bearer(request).encode(), expected.encode()):
        log.warning("portal auth rejected from %s (%s %s)", _client(request), request.method,
                    request.url.path)
        raise Unauthorized("Missing or wrong portal token.")


def new_device_token() -> str:
    return secrets.token_urlsafe(32)  # 32 random bytes


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_pair_code() -> str:
    return "".join(secrets.choice(PAIR_CODE_ALPHABET) for _ in range(4))


async def require_device(request: Request) -> tuple[dict[str, Any], str]:
    """(device row, presented token) for a valid device token, else Unauthorized.
    Cached per request, so the route dependency and the handler share one lookup."""
    cached = getattr(request.state, "device_auth", None)
    if cached is not None:
        return cached
    token = bearer(request)
    device = None
    if token:
        p = request.app.state.pipeline
        device = await p.db.device_by_token(token_hash(token))
    if device is None:
        log.warning("device auth rejected from %s (%s %s)", _client(request), request.method,
                    request.url.path)
        raise Unauthorized("Missing or unknown device token. Pair the lens again.")
    request.state.device_auth = (device, token)
    return device, token


# FastAPI dependencies. Dependencies run before request-body validation, so an
# unauthenticated caller gets 401, never a 400 that reveals the route's body shape.


async def portal_auth(request: Request) -> None:
    require_portal(request)


async def device_auth(request: Request) -> tuple[dict[str, Any], str]:
    return await require_device(request)


class RateLimiter:
    """Sliding one-minute window per key. In-process: one relay process (ponytail)."""

    def __init__(self, per_minute: int, clock: Any = time.monotonic) -> None:
        self.per_minute, self.clock = per_minute, clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = self.clock()
        window = self.hits[key]
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) >= self.per_minute:
            log.warning("rate limit: %s exceeded %d pairings per minute", key, self.per_minute)
            raise RateLimited("Too many pairing requests. Wait a minute and try again.")
        window.append(now)
        if len(self.hits) > 10_000:  # bound memory under a scan
            for stale in [k for k, w in self.hits.items() if not w or now - w[-1] >= 60.0]:
                del self.hits[stale]


def client_key(request: Request) -> str:
    return _client(request)
