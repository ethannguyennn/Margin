"""App factory: Sentry init, CORS, trace ids, error shape, router mount, pipeline factory.

Run:  uvicorn margin_relay.main:create_app --factory --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import importlib
import logging
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import obs
from .config import Settings, get_settings
from .pipeline import mock
from .schemas import ErrorBody, ErrorResponse, IntentResult

log = logging.getLogger("margin.relay")

ALLOWED_HEADERS = ["content-type", "sentry-trace", "baggage", "x-session-id", "authorization"]
ERROR_STATUS = {"bad_request": 400, "stt_failed": 502, "db_down": 503, "llm_timeout": 504,
                "internal": 500}


# --- pipeline factory -------------------------------------------------------------


@dataclass
class Pipeline:
    transcriber: Any
    classify: Callable[[str], IntentResult]
    retriever: Any
    generator: Any
    verify: Callable[..., Any]
    sanitize: Callable[[str], str]
    notifier: Any
    db: Any
    real_db: bool
    mocked: list[str] = field(default_factory=list)  # components running on mocks
    min_sim: float = float("-inf")  # gate thresholds; -inf disables the gate
    min_rrf: float = float("-inf")
    sessions: OrderedDict[str, Any] = field(default_factory=OrderedDict)  # last answer, for repeat

    def remember(self, session_id: str, response: Any) -> None:
        self.sessions[session_id] = response
        self.sessions.move_to_end(session_id)
        while len(self.sessions) > 1000:
            self.sessions.popitem(last=False)


def _import(name: str) -> ModuleType | None:
    """Lazy import of a real module. Missing (Part 4/5 not merged yet) -> None."""
    try:
        return importlib.import_module(f"margin_relay.{name}")
    except ImportError as exc:
        log.warning("real %s unavailable (%s); using mock", name, exc)
        return None


def _construct(cls: Any, settings: Settings, **kw: Any) -> Any:
    from_settings = getattr(cls, "from_settings", None)
    return from_settings(settings, **kw) if from_settings else cls(settings, **kw)


def _adapt_intent(classify: Callable[[str], Any],
                  deviation_text: Callable[[str], str] | None) -> Callable[[str], IntentResult]:
    """Part 4's classify_intent returns a bare intent string (plus a separate
    deviation_text helper); normalise both shapes to IntentResult."""

    def run(transcript: str) -> IntentResult:
        result = classify(transcript)
        if isinstance(result, IntentResult):
            return result
        intent = str(result)
        text = deviation_text(transcript) if intent == "deviation" and deviation_text else transcript
        try:
            return IntentResult(intent=intent, text=text)
        except ValueError:
            log.warning("classifier returned unknown intent %r; treating as question", intent)
            return IntentResult(intent="question", text=transcript)

    return run


class _PoolStore:
    """Part 4's retrieval Store over Part 5's pool, resolved per call because the pool
    only opens in the lifespan (after the factory ran). Falls back to Part 5's own
    vector_top/fts_top/steps_for when the db module exposes no pool."""

    def __init__(self, retrieve_mod: ModuleType, db: Any) -> None:
        self._retrieve, self._db = retrieve_mod, db

    def _store(self) -> Any:
        pool = getattr(self._db, "get_pool", None) or getattr(self._db, "pool", None)
        pool = pool() if callable(pool) else pool  # Part 5's db.pool is a function
        return self._retrieve.PgStore(pool) if pool is not None else self._db

    async def vector_top(self, q_embedding: list[float], k: int, revision: str | None) -> list[Any]:
        return await self._store().vector_top(q_embedding, k, revision)

    async def fts_top(self, query: str, k: int, revision: str | None) -> list[Any]:
        return await self._store().fts_top(query, k, revision)

    async def steps_for(self, doc_id: str, revision: str | None) -> list[Any]:
        return await self._store().steps_for(doc_id, revision)


def build_pipeline(settings: Settings) -> Pipeline:
    """MOCK_MODE=1 -> every component mocked, nothing real is imported.
    MOCK_MODE=0 -> real modules, lazily imported; any one that is missing or fails to
    construct falls back to its mock with a WARN, and /v1/health reports mock=true."""
    mocked: list[str] = []
    if settings.mock_mode:
        p = Pipeline(transcriber=mock.MockTranscriber(), classify=mock.classify_intent,
                     retriever=mock.MockRetriever(), generator=mock.MockGenerator(),
                     verify=mock.verify, sanitize=mock.sanitize, notifier=mock.MockNotifier(),
                     db=mock.MockDB(), real_db=False, mocked=["all"])
        _set_thresholds(p, settings, mock_retriever=True)
        return p

    def attempt(name: str, build: Callable[[], Any], fallback: Callable[[], Any]) -> Any:
        try:
            return build()
        except Exception as exc:  # noqa: BLE001 - missing key/model/module: degrade, loudly
            log.warning("real %s not constructed (%s: %s); using mock", name,
                        type(exc).__name__, exc)
            mocked.append(name)
            return fallback()

    db_mod = _import("db")
    db: Any = db_mod if db_mod is not None else mock.MockDB()
    if db_mod is None:
        mocked.append("db")

    def need(mod: ModuleType | None) -> ModuleType:
        if mod is None:
            raise ImportError("module not present")
        return mod

    intent_mod = _import("pipeline.intent")
    classify = attempt("intent", lambda: _adapt_intent(
        need(intent_mod).classify_intent, getattr(intent_mod, "deviation_text", None)),
        lambda: mock.classify_intent)
    sanitize_mod = _import("pipeline.sanitize")
    sanitize = attempt("sanitize", lambda: need(sanitize_mod).sanitize, lambda: mock.sanitize)
    verify_mod = _import("pipeline.verify")
    verify = attempt("verify", lambda: need(verify_mod).verify, lambda: mock.verify)

    generate_mod = _import("pipeline.generate")
    client_cache: list[Any] = []

    def gemini() -> Any:  # one shared client for embed + generate
        if not client_cache:
            client_cache.append(need(generate_mod).gemini_client(settings.gemini_api_key))
        return client_cache[0]

    generator = attempt("generate", lambda: _construct(
        need(generate_mod).GeminiGenerator, settings, client=gemini()), mock.MockGenerator)

    retrieve_mod = _import("pipeline.retrieve")
    retriever_is_mock = False

    def real_retriever() -> Any:
        mod = need(retrieve_mod)
        if db_mod is None:
            raise ImportError("db module not present")
        embedder = mod.GeminiEmbedder(gemini(), settings.gemini_model_embed, settings.embed_dim)
        return mod.Retriever(_PoolStore(mod, db_mod), embedder)

    def mock_retriever() -> Any:
        nonlocal retriever_is_mock
        retriever_is_mock = True
        return mock.MockRetriever()

    retriever = attempt("retrieve", real_retriever, mock_retriever)

    transcribe_mod = _import("pipeline.transcribe")
    transcriber = attempt("transcribe", lambda: _construct(
        need(transcribe_mod).GeminiTranscriber, settings), mock.MockTranscriber)

    def real_notifier() -> Any:
        name = settings.notifier.strip().lower() or "console"
        mod = need(_import(f"notify.{name}"))
        cls = getattr(mod, f"{name.capitalize()}Notifier")
        return cls.from_settings(settings) if hasattr(cls, "from_settings") else (
            cls(settings) if name != "console" else cls())

    notifier = attempt("notify", real_notifier, mock.MockNotifier)

    p = Pipeline(transcriber=transcriber, classify=classify, retriever=retriever,
                 generator=generator, verify=verify, sanitize=sanitize, notifier=notifier,
                 db=db, real_db=db_mod is not None, mocked=mocked)
    _set_thresholds(p, settings, mock_retriever=retriever_is_mock)
    if mocked:
        log.warning("MOCK_MODE=0 but running on mocks for: %s", ", ".join(mocked))
    return p


def _set_thresholds(p: Pipeline, settings: Settings, *, mock_retriever: bool) -> None:
    sim, rrf = settings.not_found_min_sim, settings.not_found_min_rrf
    if mock_retriever:
        sim = mock.MOCK_MIN_SIM if sim is None else sim
        rrf = mock.MOCK_MIN_RRF if rrf is None else rrf
    if sim is None or rrf is None:
        log.warning("NOT_FOUND_MIN_SIM / NOT_FOUND_MIN_RRF unset: retrieval gate disabled, "
                    "refusals rely on the generator + verifier only")
        return
    p.min_sim, p.min_rrf = sim, rrf


# --- errors -------------------------------------------------------------------


def error_response(trace_id: str, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(trace_id=trace_id, error=ErrorBody(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=ERROR_STATUS.get(code, 500))


def trace_id_of(request: Request) -> str:
    return getattr(request.state, "trace_id", None) or obs.resolve_trace_id(request.headers)


# --- middleware -----------------------------------------------------------------


class LoggingCORSMiddleware(CORSMiddleware):
    """Starlette CORS, plus a WARN for every rejected origin so a WebView origin
    mismatch is obvious in the relay log in ten seconds."""

    def is_allowed_origin(self, origin: str) -> bool:
        allowed = super().is_allowed_origin(origin)
        if not allowed:
            log.warning("CORS rejected origin %r -- if this is the WebView, add it to "
                        "ALLOWED_ORIGINS", origin)
        return allowed


class OptionsMiddleware:
    """2xx for any OPTIONS the CORS layer did not answer as a preflight."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            await Response(status_code=204, headers={"allow": "GET, POST, OPTIONS"})(
                scope, receive, send)
            return
        await self.app(scope, receive, send)


class TraceMiddleware:
    """Sets request.state.trace_id, echoes it as x-trace-id, and turns any unhandled
    exception into the contract error shape *inside* CORS so the browser can read it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        trace_id = obs.resolve_trace_id(headers)
        scope.setdefault("state", {})["trace_id"] = trace_id
        started = False

        async def send_with_trace(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [*message.get("headers", []),
                                      (b"x-trace-id", trace_id.encode("latin-1"))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            log.exception("unhandled error (trace %s)", trace_id)
            if started:
                raise
            await error_response(trace_id, "internal", "internal relay error")(
                scope, receive, send_with_trace)


# --- app factory ------------------------------------------------------------------


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    obs.init_sentry(settings)
    pipe = pipeline or build_pipeline(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        if pipe.real_db:
            try:
                await pipe.db.init_pool()
            except Exception as exc:  # noqa: BLE001 - boot anyway; /v1/health says db: down
                log.error("db init_pool failed: %s", type(exc).__name__)
        yield
        close = getattr(pipe.db, "close_pool", None)
        if pipe.real_db and close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                log.warning("db close_pool failed")

    app = FastAPI(title="Margin relay", version=obs.version(settings), lifespan=lifespan,
                  docs_url="/v1/docs", openapi_url="/v1/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.pipeline = pipe

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only: never echo request input (transcripts, audio).
        parts = [f"{'.'.join(str(x) for x in e.get('loc', ()) if x != 'body')}: {e.get('msg')}"
                 for e in exc.errors()]
        return error_response(trace_id_of(request), "bad_request", "; ".join(parts)[:300])

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "internal" if exc.status_code >= 500 else "bad_request"
        resp = error_response(trace_id_of(request), code, str(exc.detail))
        resp.status_code = exc.status_code
        return resp

    from .routes import ask, deviation, health, ingest, procedures

    for module in (health, ask, deviation, procedures, ingest):
        app.include_router(module.router)

    # Added innermost first: CORS is outermost, so even error responses carry CORS headers.
    app.add_middleware(TraceMiddleware)
    app.add_middleware(OptionsMiddleware)
    origins = settings.allowed_origins_list
    if not origins and not settings.allowed_origin_regex:
        log.warning("ALLOWED_ORIGINS is empty: every browser origin will be rejected")
    app.add_middleware(LoggingCORSMiddleware, allow_origins=origins,
                       allow_origin_regex=settings.allowed_origin_regex or None,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=ALLOWED_HEADERS,
                       expose_headers=["x-trace-id"], allow_credentials=False, max_age=600)

    log.info("Margin relay %s up: mock_mode=%s mocked=%s origins=%s", obs.version(settings),
             settings.mock_mode, pipe.mocked or "none", origins or "-")
    return app
