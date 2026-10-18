"""Observability: Sentry init, the one stage-timing helper, trace ids, the events write.

Spans are named exactly ``stt``, ``embed``, ``retrieve``, ``generate``, ``verify``
so they line up with the app's ``capture`` / ``upload`` / ``render``. The relay
continues the app's trace from the ``sentry-trace`` / ``baggage`` headers (the
Sentry FastAPI integration does this; CORS allows both headers).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any

import sentry_sdk

from . import __version__
from .config import Settings
from .schemas import Latency

log = logging.getLogger("specs.obs")

STAGES = ("stt", "embed", "retrieve", "generate", "verify")
_SENTRY_TRACE_RE = re.compile(r"^\s*([0-9a-f]{32})(?:-[0-9a-f]{16})?(?:-[01])?\s*$")
_quota_lock = Lock()
_quota_counts: Counter[str] = Counter()
request_quota: ContextVar[bool] = ContextVar("specs_request_quota", default=False)


def quota_snapshot() -> dict:
    """Process-lifetime counters; no prompts, credentials or request bodies."""
    with _quota_lock:
        return {"gemini_429_total": sum(_quota_counts.values()),
                "gemini_429_by_stage": dict(_quota_counts)}


def record_quota_error(exc: BaseException, stage: str) -> bool:
    """Count a propagated provider 429 once, even through nested timing spans."""
    current, found, seen = exc, None, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "code", None) or getattr(current, "status_code", None)
        if str(code) == "429" or re.search(r"\bHTTP\s+429\b|\bRESOURCE_EXHAUSTED\b", str(current), re.I):
            found = current
        current = current.__cause__ or current.__context__
    if found is None:
        return False
    request_quota.set(True)
    with _quota_lock:
        if getattr(found, "_specs_quota_counted", False):
            return False
        found._specs_quota_counted = True
        _quota_counts[stage] += 1
        total = sum(_quota_counts.values())
    log.warning("Gemini quota exceeded stage=%s gemini_429_total=%d", stage, total)
    return True


def version(settings: Settings) -> str:
    return f"{__version__}+{settings.git_sha}" if settings.git_sha else __version__


def init_sentry(settings: Settings) -> bool:
    """Initialise sentry-sdk with tracing and logs. No DSN -> no-op (local dev, tests)."""
    if not settings.sentry_dsn_relay:
        log.info("SENTRY_DSN_RELAY not set; Sentry disabled")
        return False
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn_relay,
        environment=settings.sentry_environment,
        release=f"specs-relay@{version(settings)}",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        enable_logs=True,
        send_default_pii=False,  # no IPs, no cookies, no request bodies with transcripts
        # Continue the app's trace inbound; never attach our trace headers to outbound
        # third-party calls (Gemini, Photon).
        trace_propagation_targets=[],
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR,
                               sentry_logs_level=logging.INFO),
        ],
    )
    log.info("Sentry enabled (environment=%s)", settings.sentry_environment)
    return True


# --- trace id ----------------------------------------------------------------


def resolve_trace_id(headers: Mapping[str, str]) -> str:
    """The id of the trace this request belongs to.

    Prefers the active Sentry transaction (which has already continued the app's
    trace), then the incoming ``sentry-trace`` header, then a fresh id, so every
    response carries a trace_id even with Sentry disabled.
    """
    client = sentry_sdk.get_client()
    enabled = client.is_active() and bool(getattr(client, "dsn", None))
    span = sentry_sdk.get_current_span() if enabled else None
    if span is not None and getattr(span, "trace_id", None):
        return span.trace_id
    match = _SENTRY_TRACE_RE.match(headers.get("sentry-trace", "") or "")
    if match:
        return match.group(1)
    return uuid.uuid4().hex


# --- stage timing -------------------------------------------------------------


class StageTimer:
    """Per-request accumulator. A stage records its *self* time: time spent in a
    nested stage (``embed`` inside ``retrieve``) is attributed to the nested one only.
    Stages that run twice (the generate/verify retry) accumulate."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.ms: dict[str, float] = defaultdict(float)
        self._child_ms: list[float] = []

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def latency(self) -> Latency:
        return Latency(
            **{name: round(self.ms.get(name, 0.0)) for name in STAGES},
            total=round(self.elapsed_ms()),
        )


_timer: ContextVar[StageTimer | None] = ContextVar("specs_stage_timer", default=None)


def start_timer() -> StageTimer:
    timer = StageTimer()
    _timer.set(timer)
    return timer


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Sentry span + ``latency_ms`` entry for one pipeline stage. One helper, used everywhere."""
    timer = _timer.get()
    with sentry_sdk.start_span(op=name, name=name):
        start = time.perf_counter()
        if timer is not None:
            timer._child_ms.append(0.0)
        try:
            yield
        except Exception as exc:
            record_quota_error(exc, name)
            raise
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            if timer is not None:
                child = timer._child_ms.pop()
                timer.ms[name] += max(0.0, elapsed - child)
                if timer._child_ms:
                    timer._child_ms[-1] += elapsed


# --- events -------------------------------------------------------------------


async def write_event(db: Any, **fields: Any) -> None:
    """Call Part 5's writer. Never raises into the request path."""
    try:
        await db.write_event(**fields)
    except Exception as exc:  # noqa: BLE001 - analytics must never cost an answer
        log.warning("events write failed: %s", type(exc).__name__)
