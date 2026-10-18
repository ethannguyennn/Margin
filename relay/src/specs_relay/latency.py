"""`make latency`: p50/p95 per stage from the Timescale `events` hypertable.

    python -m specs_relay.latency

Reads through Part 5's ``db.latency_summary()`` (db.py is the only module that
opens connections), using DATABASE_URL from config. Relay-side only: the pitch
number (end-of-speech to glance on the lens) adds the app's upload and render.
"""

from __future__ import annotations

import asyncio
import math
import sys
from collections.abc import Iterable, Mapping
from typing import Any

from .obs import STAGES

ORDER = (*STAGES, "total")
BUDGET_MS = 3000


def _ms(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{float(value):.0f}"


def render(rows: Iterable[Mapping[str, Any]]) -> str:
    """Table from latency_summary rows: {stage, samples, p50_ms, p95_ms}."""
    by_stage = {r["stage"]: r for r in rows}
    stages = [s for s in ORDER if s in by_stage] + sorted(set(by_stage) - set(ORDER))
    lines = [f"{'stage':<10}{'n':>7}{'p50 ms':>9}{'p95 ms':>9}", "-" * 35]
    for stage in stages:
        r = by_stage[stage]
        lines.append(f"{stage:<10}{r['samples']:>7}{_ms(r['p50_ms']):>9}{_ms(r['p95_ms']):>9}")
    if not stages:
        lines.append("(no events yet)")
    return "\n".join(lines)


def verdict(rows: Iterable[Mapping[str, Any]]) -> str | None:
    total = next((r for r in rows if r["stage"] == "total"), None)
    if total is None or total["p50_ms"] is None:
        return None
    p50 = float(total["p50_ms"])
    word = "within" if p50 <= BUDGET_MS else "OVER"
    return (f"relay p50 total {p50:.0f} ms ({word} the {BUDGET_MS // 1000} s "
            "end-of-speech-to-glance budget; add app upload + render for the full number)")


async def fetch() -> list[dict]:
    """All events, one summary (kept for callers that want a single table)."""
    return (await fetch_report())["all"]


async def fetch_report() -> dict[str, list[dict]]:
    """Three summaries in one pool session: all events, answers (every intent but
    ``command``) and voice commands (TODO section 1: report commands separately)."""
    try:
        from . import db
    except ImportError as exc:
        raise SystemExit(f"specs_relay.db is not available: {exc}") from exc
    await db.init_pool()
    try:
        return {
            "all": [dict(r) for r in await db.latency_summary()],
            "answers": [dict(r) for r in await db.latency_summary(exclude_intent="command")],
            "commands": [dict(r) for r in await db.latency_summary(intent="command")],
        }
    finally:
        await db.close_pool()


def main() -> int:
    # psycopg's async pool cannot run on Windows' default Proactor loop (same fix as db/seed.py).
    # asyncio.Runner takes loop_factory on 3.11; asyncio.run() only gained it in 3.12.
    win = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    try:
        with asyncio.Runner(**win) as runner:
            report = runner.run(fetch_report())
    except ValueError as exc:  # e.g. DATABASE_URL not set
        print(f"make latency: {exc}", file=sys.stderr)
        return 1
    titles = {
        "all": "all events (stages that did not run are excluded, not counted as 0 ms)",
        "answers": "answers and refusals (every intent except command)",
        "commands": "voice commands (target: STT + < 50 ms relay work)",
    }
    for key, title in titles.items():
        print(f"\n{title}")
        print(render(report[key]))
        line = verdict(report[key]) if key != "commands" else None
        if line:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
