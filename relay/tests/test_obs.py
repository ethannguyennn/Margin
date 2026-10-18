"""Observability: stage timing, trace continuation, the relay span tree."""

from __future__ import annotations

import base64
import time

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from _relay_helpers import make_client, make_settings, sid
from specs_relay import obs

APP_TRACE = "771a43a4192642f0b136d5159a501700"
APP_SPAN = "b0e6f15b45c36b12"
SENTRY_TRACE = f"{APP_TRACE}-{APP_SPAN}-1"
BAGGAGE = f"sentry-trace_id={APP_TRACE},sentry-sample_rate=1.0,sentry-sampled=true"


class FakeClock:
    """Deterministic perf_counter: real sleeps make timing asserts flaky under load."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms / 1000.0


def test_stage_records_self_time_and_accumulates(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(obs.time, "perf_counter", clock)
    timer = obs.start_timer()
    with obs.stage("retrieve"):
        clock.advance(20)
        with obs.stage("embed"):
            clock.advance(30)
    with obs.stage("generate"):
        clock.advance(10)
    with obs.stage("generate"):  # the retry accumulates
        clock.advance(10)
    clock.advance(5)  # orchestration overhead outside any stage
    lat = timer.latency()
    assert lat.embed == 30
    assert lat.retrieve == 20  # embed is not double-counted inside retrieve
    assert lat.generate == 20
    assert lat.total == 75
    assert lat.stt == 0 and lat.verify == 0


def test_stage_without_timer_is_harmless():
    obs._timer.set(None)
    with obs.stage("verify"):
        pass


def test_resolve_trace_id_prefers_incoming_header():
    assert obs.resolve_trace_id({"sentry-trace": SENTRY_TRACE}) == APP_TRACE
    assert obs.resolve_trace_id({"sentry-trace": APP_TRACE}) == APP_TRACE
    fresh = obs.resolve_trace_id({"sentry-trace": "garbage"})
    assert len(fresh) == 32 and fresh != APP_TRACE


def test_response_continues_app_trace_without_sentry():
    client, _ = make_client()
    r = client.post("/v1/ask", json={"session_id": sid(), "text": "how tight is the m5"},
                    headers={"sentry-trace": SENTRY_TRACE, "baggage": BAGGAGE})
    assert r.json()["trace_id"] == APP_TRACE and r.headers["x-trace-id"] == APP_TRACE
    r = client.post("/v1/ask", json={"session_id": "bad"}, headers={"sentry-trace": SENTRY_TRACE})
    assert r.json()["trace_id"] == APP_TRACE  # errors too


def test_init_sentry_options(monkeypatch):
    seen = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    assert obs.init_sentry(make_settings(sentry_dsn_relay="")) is False and not seen
    assert obs.init_sentry(make_settings(sentry_dsn_relay="https://k@o0.ingest.sentry.io/1",
                                         sentry_environment="demo", git_sha="abc123"))
    assert seen["traces_sample_rate"] == 1.0 and seen["enable_logs"] is True
    assert seen["send_default_pii"] is False and seen["environment"] == "demo"
    assert seen["release"] == "specs-relay@0.1.0+abc123"
    assert seen["trace_propagation_targets"] == []
    names = {type(i).__name__ for i in seen["integrations"]}
    assert {"FastApiIntegration", "StarletteIntegration", "LoggingIntegration"} <= names


class CaptureTransport(Transport):
    def __init__(self):
        super().__init__()
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)

    def transactions(self):
        out = []
        for env in self.envelopes:
            for item in env.items:
                if item.type == "transaction":
                    out.append(item.payload.json)
        return out


@pytest.fixture
def sentry_capture():
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    transport = CaptureTransport()
    # default_integrations=False: the auto-enabled httpx integration would patch the
    # TestClient itself and inject the test's own sentry-trace into later tests.
    sentry_sdk.init(dsn="https://public@o0.ingest.sentry.io/1", transport=transport,
                    traces_sample_rate=1.0, default_integrations=False,
                    integrations=[StarletteIntegration(), FastApiIntegration()])
    yield transport
    sentry_sdk.init(dsn=None, default_integrations=False)


def test_relay_span_tree_joins_the_app_trace(sentry_capture):
    client, _ = make_client()
    pcm = base64.b64encode(b"\x00\x00" * 16000).decode()
    r = client.post("/v1/ask", headers={"sentry-trace": SENTRY_TRACE, "baggage": BAGGAGE},
                    json={"session_id": sid(), "audio": {"format": "pcm_s16le",
                                                         "sample_rate": 16000, "channels": 1,
                                                         "data_b64": pcm}})
    assert r.status_code == 200 and r.json()["outcome"] == "answered"
    sentry_sdk.flush()
    txns = [t for t in sentry_capture.transactions() if "ask" in t.get("transaction", "")]
    assert txns, "no /v1/ask transaction captured"
    t = txns[-1]
    trace = t["contexts"]["trace"]
    assert trace["trace_id"] == APP_TRACE  # same trace as the app's `ask` transaction
    assert trace["parent_span_id"] == APP_SPAN  # child of the app's upload span
    assert r.json()["trace_id"] == APP_TRACE
    ops = [s["op"] for s in t["spans"]]
    for name in ("stt", "embed", "retrieve", "generate", "verify"):
        assert name in ops, f"missing span {name}: {ops}"
