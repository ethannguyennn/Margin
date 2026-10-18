"""Portal and device authentication (README-PART-3 section 5), per workspace.

- Portal: ``authorization: Bearer <workspace code>`` on every portal route; the code
  is also what workers type in the Even app to join (hackathon: one code, both
  uses). The shared ``PORTAL_TOKEN`` still works and opens the demo workspace.
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

from . import org
from .pipeline import DbDown, PipelineError
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
    """Raise Unauthorized unless the request carries a workspace code or the portal token.
    ``portal_auth`` (the route dependency) resolves the code; this re-check is free."""
    if getattr(request.state, "portal_org", None):
        return
    settings = request.app.state.settings
    expected = settings.portal_token.get_secret_value() if settings.portal_token else ""
    if not expected:
        log.warning("portal auth rejected from %s (%s %s): no such workspace", _client(request),
                    request.method, request.url.path)
        raise Unauthorized("Missing or wrong workspace code.")
    if not hmac.compare_digest(bearer(request).encode(), expected.encode()):
        log.warning("portal auth rejected from %s (%s %s)", _client(request), request.method,
                    request.url.path)
        raise Unauthorized("Missing or wrong workspace code.")
    request.state.portal_org = org.DEFAULT_ORG
    org.use(org.DEFAULT_ORG)


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
    code = bearer(request)
    found = None
    if code:
        try:
            found = await request.app.state.pipeline.db.org_by_code(code)
        except Exception as exc:  # noqa: BLE001
            raise DbDown(f"workspace lookup failed: {type(exc).__name__}") from exc
    if found is not None:
        request.state.portal_org = found["org_id"]
        org.use(found["org_id"])
        return
    require_portal(request)


def device_org(device: dict[str, Any]) -> str:
    """A lens that never joined a workspace sees the demo one."""
    return device.get("org_id") or org.DEFAULT_ORG


async def device_auth(request: Request) -> tuple[dict[str, Any], str]:
    device, token = await require_device(request)
    org.use(device_org(device))
    return device, token


async def device_scope(request: Request) -> None:
    """Open lens routes (ask, procedures): a valid device token scopes them to its
    workspace; no token or an unknown one leaves them unscoped, as before."""
    org.use(None)
    token = bearer(request)
    if not token:
        return
    try:
        device = await request.app.state.pipeline.db.device_by_token(token_hash(token))
    except Exception:  # noqa: BLE001 - scoping is best effort; the route reports db errors
        return
    if device is not None:
        org.use(device_org(device))


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
