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

    async def latency_summary(intent=None, *, exclude_intent=None):
        calls.append(("summary", intent, exclude_intent))
        return ROWS if intent is None else ROWS[:1]

    fake = types.ModuleType("specs_relay.db")
    fake.init_pool, fake.close_pool, fake.latency_summary = init_pool, close_pool, latency_summary
    monkeypatch.setitem(sys.modules, "specs_relay.db", fake)
    monkeypatch.setattr(sys.modules["specs_relay"], "db", fake, raising=False)
    import asyncio
    assert asyncio.run(latency.fetch()) == ROWS
    assert calls == ["init", ("summary", None, None), ("summary", None, "command"),
                     ("summary", "command", None), "close"]
    calls.clear()
    report = asyncio.run(latency.fetch_report())
    assert report == {"all": ROWS, "answers": ROWS, "commands": ROWS[:1]}


def test_main_prints_answers_and_commands_separately(monkeypatch, capsys):
    async def fetch_report():
        return {"all": ROWS, "answers": ROWS, "commands": ROWS[:1]}

    monkeypatch.setattr(latency, "fetch_report", fetch_report)
    assert latency.main() == 0
    out = capsys.readouterr().out
    assert "all events" in out and "every intent except command" in out and "voice commands" in out
    assert out.count("relay p50 total") == 2  # no budget verdict on the command table
