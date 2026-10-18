from __future__ import annotations

import sys
import types

from specs_relay import latency

ROWS = [
    {"stage": "generate", "samples": 3, "p50_ms": 1200.0, "p95_ms": 1380.0},
    {"stage": "total", "samples": 3, "p50_ms": 1300.0, "p95_ms": 2290.0},
    {"stage": "stt", "samples": 3, "p50_ms": 0.0, "p95_ms": 540.0},
]


def test_render_orders_stages_and_formats():
    table = latency.render(ROWS)
    lines = table.splitlines()
    assert [ln.split()[0] for ln in lines[2:]] == ["stt", "generate", "total"]
    assert "1200" in table and "2290" in table


def test_render_empty():
    assert "no events" in latency.render([])


def test_verdict_against_budget():
    assert "within" in latency.verdict(ROWS)
    assert "OVER" in latency.verdict([{"stage": "total", "samples": 1, "p50_ms": 3500,
                                       "p95_ms": 3500}])
    assert latency.verdict([]) is None


def test_fetch_reads_through_db_latency_summary(monkeypatch):
    calls = []

    async def init_pool():
        calls.append("init")

    async def close_pool():
        calls.append("close")

    async def latency_summary():
        calls.append("summary")
        return ROWS

    fake = types.ModuleType("specs_relay.db")
    fake.init_pool, fake.close_pool, fake.latency_summary = init_pool, close_pool, latency_summary
    monkeypatch.setitem(sys.modules, "specs_relay.db", fake)
    monkeypatch.setattr(sys.modules["specs_relay"], "db", fake, raising=False)
    import asyncio
    assert asyncio.run(latency.fetch()) == ROWS
    assert calls == ["init", "summary", "close"]
