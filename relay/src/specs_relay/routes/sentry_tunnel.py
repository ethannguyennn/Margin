"""Browser envelope tunnel, pinned to SENTRY_DSN_APP; never an arbitrary HTTP proxy.

The public SDK sends its DSN in the first envelope line. Compare it to the exact
configured app DSN; derive the destination only from server configuration. Keep
binary item payloads byte-for-byte, cap the stream, rate limit and never log it.
See https://docs.sentry.io/platforms/javascript/troubleshooting/#using-the-tunnel-option
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..auth import RateLimiter
from ..pipeline import BadRequest
from .common import NotFound, PayloadTooLarge

router = APIRouter()
MAX_BYTES = 256 * 1024


def destination(dsn: str) -> str:
    parsed = urlsplit(dsn)
    prefix, _, project = parsed.path.rstrip('/').rpartition('/')
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.username or parsed.password
            or not project.isdigit() or parsed.query or parsed.fragment):
        raise ValueError('Invalid configured app DSN')
    host = parsed.hostname + (f':{parsed.port}' if parsed.port else '')
    return f'https://{host}{prefix}/api/{project}/envelope/'


async def forward(url: str, envelope: bytes) -> int:
    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
        response = await client.post(url, content=envelope,
                                     headers={'content-type': 'application/x-sentry-envelope'})
        return response.status_code


@router.post('/v1/sentry-tunnel')
async def tunnel(request: Request) -> Response:
    dsn = request.app.state.settings.sentry_dsn_app
    if not dsn:
        raise NotFound('App telemetry tunnel is not configured.')
    try:
        url = destination(dsn)
    except ValueError as exc:
        raise NotFound('App telemetry tunnel is not configured correctly.') from exc
    limiter = getattr(request.app.state, 'sentry_tunnel_limiter', None)
    if limiter is None:
        limiter = request.app.state.sentry_tunnel_limiter = RateLimiter(60)
    limiter.check(request.client.host if request.client else 'unknown')
    if request.headers.get('content-encoding', 'identity') != 'identity':
        raise BadRequest('Compressed envelopes are not accepted.')
    length = request.headers.get('content-length', '')
    if length.isdigit() and int(length) > MAX_BYTES:
        raise PayloadTooLarge('Telemetry envelope is too large.')
    envelope = bytearray()
    async for part in request.stream():
        if len(envelope) + len(part) > MAX_BYTES:
            raise PayloadTooLarge('Telemetry envelope is too large.')
        envelope.extend(part)
    header = envelope.split(b'\n', 1)[0]
    try:
        if len(header) > 8192 or json.loads(header).get('dsn') != dsn:
            raise ValueError('DSN mismatch')
    except (ValueError, TypeError, AttributeError) as exc:
        raise BadRequest('Envelope must target the configured app project.') from exc
    try:
        status = await forward(url, bytes(envelope))
    except httpx.HTTPError:
        return Response(status_code=502, headers={'Cache-Control': 'no-store'})
    return Response(status_code=200 if 200 <= status < 300 else 502,
                    headers={'Cache-Control': 'no-store'})
