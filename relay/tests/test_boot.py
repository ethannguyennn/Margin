"""Boot + factory: MOCK_MODE=1 with nothing real present, and the MOCK_MODE=0 wiring
against Part 4's actual module surface (faked here, so this needs no key or DB)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import types

import pytest

from _relay_helpers import ask, make_client, make_settings
from margin_relay import main
from margin_relay.schemas import Chunk, Draft, DraftCitation, IntentResult, VerifyResult

BLOCKED = [
    "margin_relay.db", "margin_relay.notify", "margin_relay.walkthrough",
    *[f"margin_relay.pipeline.{m}" for m in
      ("transcribe", "intent", "retrieve", "generate", "verify", "sanitize")],
    "google.genai", "psycopg", "psycopg_pool", "pgvector",
]

BOOT_SCRIPT = textwrap.dedent("""
    import importlib.abc, json, sys, uuid
    BLOCKED = json.loads(sys.argv[1])

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if any(name == b or name.startswith(b + ".") for b in BLOCKED):
                raise ImportError(f"blocked for test: {name}")
            return None

    sys.meta_path.insert(0, Block())
    from fastapi.testclient import TestClient
    from margin_relay.config import Settings
    from margin_relay.main import create_app

    app = create_app(Settings(_env_file=None))   # MOCK_MODE comes from the environment
    c = TestClient(app)
    health = c.get("/v1/health").json()
    answer = c.post("/v1/ask", json={"session_id": str(uuid.uuid4()),
                                     "text": "how tight is the m5 on the mounting bracket"}).json()
    leaked = sorted(m for m in sys.modules if any(m == b or m.startswith(b + ".") for b in BLOCKED))
    print(json.dumps({"health": health, "outcome": answer.get("outcome"), "leaked": leaked,
                      "mocked": app.state.pipeline.mocked}))
""")


def run_boot(mock_mode: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("GEMINI", "DATABASE_URL", "SENTRY", "NOT_FOUND",
                                        "ALLOWED_ORIGIN", "MOCK_MODE"))}
    env["MOCK_MODE"] = mock_mode
    out = subprocess.run([sys.executable, "-c", BOOT_SCRIPT, json.dumps(BLOCKED)], env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_mock_mode_boots_with_no_db_no_key_no_pipeline_modules():
    r = run_boot("1")
    assert r["health"] == {"ok": True, "mock": True, "db": "mock", "version": r["health"]["version"]}
    assert r["outcome"] == "answered"
    assert r["leaked"] == []  # nothing real was even imported


def test_real_mode_with_nothing_present_still_boots_on_mocks():
    r = run_boot("0")
    assert r["health"]["ok"] is True and r["health"]["mock"] is True
    assert r["health"]["db"] == "mock"
    assert {"db", "intent", "retrieve", "generate", "transcribe"} <= set(r["mocked"])
    assert r["outcome"] == "answered"


def test_mock_mode_never_imports_real_modules(monkeypatch):
    def forbidden(name):
        raise AssertionError(f"MOCK_MODE=1 imported {name}")

    monkeypatch.setattr(main, "_import", forbidden)
    p = main.build_pipeline(make_settings(mock_mode=True))
    assert p.mocked == ["all"] and not p.real_db


# --- MOCK_MODE=0 wiring against Part 4's module surface -------------------------------


def _fake_part4_and_part5(monkeypatch) -> dict:
    """Modules shaped exactly like Part 4's branch (Retriever(store, embedder) with
    embed()/q_embedding, GeminiGenerator.from_settings, gemini_client, intent str +
    deviation_text) and a Part 5 db module exposing get_pool()."""
    seen: dict = {"pool_stores": []}
    chunk = Chunk(chunk_id="SOP-114:C:4.2", doc_id="SOP-114", revision="C", section="4.2",
                  text="Torque all four M5 bracket screws to 4 N-m in a star pattern.")

    def mod(name: str, **attrs):
        m = types.ModuleType(f"margin_relay.{name}")
        m.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, f"margin_relay.{name}", m)
        return m

    intent = mod("pipeline.intent",
                 classify_intent=lambda t: ("deviation" if "log deviation" in t else
                                            "walkthrough" if "walk me through" in t else
                                            "question"),
                 deviation_text=lambda t: t.replace("log deviation", "").strip())
    mod("pipeline.sanitize", sanitize=lambda s: s.replace("·", "-"))
    mod("pipeline.verify", verify=lambda d, c: VerifyResult(ok=True, citations=[
        __import__("margin_relay.schemas", fromlist=["Citation"]).Citation(
            chunk_id=chunk.chunk_id, doc_id="SOP-114", revision="C", section="4.2",
            quote=d.citations[0].quote)]))

    class GeminiGenerator:
        def __init__(self, client, model):
            self.client, self.model = client, model

        @classmethod
        def from_settings(cls, settings, client=None):
            seen["generator_client"] = client
            return cls(client, settings.gemini_model_generate)

        async def generate(self, query, chunks, feedback=None):
            return Draft(answerable=True, glance="Torque M5 to 4 N·m", body="4 N-m.",
                         citations=[DraftCitation(chunk_id=chunks[0].chunk_id, quote="4 N-m")])

    mod("pipeline.generate", GeminiGenerator=GeminiGenerator,
        gemini_client=lambda key: seen.setdefault("client", object()))

    class PgStore:
        def __init__(self, pool):
            seen["pool_stores"].append(pool)

        async def vector_top(self, q, k, rev):
            return []

    class GeminiEmbedder:
        def __init__(self, client, model, dim):
            seen["embedder"] = (client, model, dim)

    class Retriever:
        def __init__(self, store, embedder):
            self.store, self.embedder = store, embedder

        async def embed(self, query):
            seen["embedded"] = query
            return [0.1]

        async def retrieve(self, query, revision, q_embedding=None):
            from margin_relay.schemas import RetrievalResult
            seen["q_embedding"] = q_embedding
            await self.store.vector_top(q_embedding, 20, revision)
            return RetrievalResult(chunks=[chunk], best_sim=0.9, best_rrf=0.03)

        async def steps_for(self, doc_id, revision):
            return []

    mod("pipeline.retrieve", Retriever=Retriever, GeminiEmbedder=GeminiEmbedder, PgStore=PgStore)

    class GeminiTranscriber:
        @classmethod
        def from_settings(cls, settings, client=None):
            seen["transcriber_client"] = client
            return cls()

        async def transcribe(self, pcm, sample_rate):
            return "how tight"

    mod("pipeline.transcribe", GeminiTranscriber=GeminiTranscriber)

    events: list = []
    devs: list = []

    class RetrievalStore:  # Part 5: Part 4's raw-row Store over db.py's own pool
        def __init__(self):
            seen["pool_stores"].append(self)

        async def vector_top(self, q, k, rev):
            seen["vector_top"] = (q, k, rev)
            return []

    async def write_event(**kw):
        events.append(kw)

    async def ok():
        return "ok"

    async def noop():
        return None

    mod("db", RetrievalStore=RetrievalStore, write_event=write_event, ping=ok,
        init_pool=noop, close_pool=noop, list_procedures=lambda: [])

    class ConsoleNotifier:
        async def notify(self, deviation_id, text):
            return True

    notify_pkg = mod("notify", get_notifier=lambda settings=None: ConsoleNotifier())
    notify_pkg.__path__ = []

    async def build_walkthrough(doc_id, revision=None):
        return {"doc_id": doc_id, "revision": "C", "title": "Mounting Bracket Assembly",
                "total": 1, "index": 0,
                "steps": [{"step_id": "SOP-114:C:4.1", "label": "4.1",
                           "glance": "Prepare and seat the bracket", "body": "Disconnect power."}]}

    async def log_deviation(session_id, text, doc_id=None, step_id=None, *, notifier=None):
        devs.append({"text": text, "doc_id": doc_id, "step_id": step_id})
        return {"deviation_id": "DEV-0042", "notified": await notifier.notify("DEV-0042", text)}

    mod("walkthrough", build_walkthrough=build_walkthrough, log_deviation=log_deviation)
    seen.update(events=events, devs=devs, intent=intent)
    return seen


def test_real_mode_wires_part4_and_part5(monkeypatch):
    seen = _fake_part4_and_part5(monkeypatch)
    settings = make_settings(mock_mode=False, gemini_model_generate="gen-from-env",
                             gemini_model_embed="embed-from-env", embed_dim=768,
                             not_found_min_sim=0.5, not_found_min_rrf=0.02)
    p = main.build_pipeline(settings)
    assert p.mocked == [] and p.real_db
    assert seen["embedder"] == (seen["client"], "embed-from-env", 768)
    assert seen["generator_client"] is seen["client"]  # one shared Gemini client
    assert seen["transcriber_client"] is seen["client"]
    assert (p.min_sim, p.min_rrf) == (0.5, 0.02)
    assert p.classify("log deviation gap too wide") == IntentResult(intent="deviation",
                                                                   text="gap too wide")

    client, app = make_client(pipeline=p, mock_mode=False)
    with client:
        h = client.get("/v1/health").json()
        assert h == {"ok": True, "mock": False, "db": "ok", "version": h["version"]}
        b = ask(client, "how tight is the m5").json()
        assert b["outcome"] == "answered" and b["glance"] == "Torque M5 to 4 N-m"
        assert seen["embedded"] == "how tight is the m5" and seen["q_embedding"] == [0.1]
        assert len(seen["pool_stores"]) == 1  # db.RetrievalStore(), never Part 4's PgStore
        assert seen["vector_top"] == ([0.1], 20, None)
        assert seen["events"][-1]["outcome"] == "answered"
        d = ask(client, "log deviation gap too wide").json()
        assert d["outcome"] == "logged" and d["glance"] == "Deviation DEV-0042 logged"
        assert seen["devs"][-1]["text"] == "gap too wide"  # via walkthrough.log_deviation
        r = client.post("/v1/deviation", json={"session_id": "6f1c2f1e-8a0b-4c1e-9a55-0b9b0e8f2a11",
                                               "text": "gap", "context": {"doc_id": "SOP-114"}})
        assert r.json() == {"deviation_id": "DEV-0042", "notified": True}
        assert p.walkthrough is sys.modules["margin_relay.walkthrough"]


def test_real_mode_walkthrough_uses_part5_builder(monkeypatch):
    _fake_part4_and_part5(monkeypatch)
    p = main.build_pipeline(make_settings(mock_mode=False, gemini_model_generate="g",
                                          gemini_model_embed="e"))
    client, _ = make_client(pipeline=p, mock_mode=False)
    b = ask(client, "walk me through the bracket").json()
    assert b["outcome"] == "answered" and b["verified"] is True
    assert b["walkthrough"]["title"] == "Mounting Bracket Assembly"
    assert b["walkthrough"]["steps"][0]["step_id"] == "SOP-114:C:4.1"

    async def missing(doc_id, revision=None):
        raise LookupError(doc_id)

    async def too_long(doc_id, revision=None):
        raise ValueError("Step body must have 1..449 characters")

    sys.modules["margin_relay.walkthrough"].build_walkthrough = missing
    assert ask(client, "walk me through the bracket").json()["outcome"] == "not_found"
    sys.modules["margin_relay.walkthrough"].build_walkthrough = too_long
    r = ask(client, "walk me through the bracket")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"


def test_real_mode_deviation_value_error_is_bad_request(monkeypatch):
    _fake_part4_and_part5(monkeypatch)

    async def invalid(session_id, text, doc_id=None, step_id=None, *, notifier=None):
        raise ValueError("step_id must belong to doc_id")

    sys.modules["margin_relay.walkthrough"].log_deviation = invalid
    client, _ = make_client(pipeline=main.build_pipeline(make_settings(mock_mode=False)),
                            mock_mode=False)
    r = client.post("/v1/deviation", json={"session_id": "6f1c2f1e-8a0b-4c1e-9a55-0b9b0e8f2a11",
                                           "text": "gap", "doc_id": "SOP-114",
                                           "step_id": "SOP-120:B:4.1"})
    assert r.status_code == 400 and "belong" in r.json()["error"]["message"]


def test_real_mode_missing_key_falls_back_loudly(monkeypatch, caplog):
    _fake_part4_and_part5(monkeypatch)

    def no_key(_):
        raise ValueError("GEMINI_API_KEY is not set")

    sys.modules["margin_relay.pipeline.generate"].gemini_client = no_key
    p = main.build_pipeline(make_settings(mock_mode=False))
    assert {"generate", "retrieve"} <= set(p.mocked)
    assert "intent" not in p.mocked and p.real_db
    assert "GEMINI_API_KEY is not set" in caplog.text
    client, _ = make_client(pipeline=p, mock_mode=False)
    assert client.get("/v1/health").json()["mock"] is True  # degraded mode is visible


def test_real_mode_unset_thresholds_disable_gate(monkeypatch):
    _fake_part4_and_part5(monkeypatch)
    p = main.build_pipeline(make_settings(mock_mode=False))
    assert p.min_sim == float("-inf") and p.min_rrf == float("-inf")


@pytest.mark.parametrize("value", ["1", "true"])
def test_mock_mode_env_parsing(monkeypatch, value):
    monkeypatch.setenv("MOCK_MODE", value)
    monkeypatch.setenv("NOT_FOUND_MIN_SIM", "")  # empty in .env means unset
    s = main.Settings(_env_file=None)
    assert s.mock_mode is True and s.not_found_min_sim is None
