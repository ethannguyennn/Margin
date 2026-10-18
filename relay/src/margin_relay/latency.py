"""`make latency`: p50/p95 per stage from the Timescale `events` hypertable.

    python -m margin_relay.latency

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
    try:
        from . import db
    except ImportError as exc:
        raise SystemExit(f"margin_relay.db is not available: {exc}") from exc
    await db.init_pool()
    try:
        return [dict(r) for r in await db.latency_summary()]
    finally:
        await db.close_pool()


def main() -> int:
    try:
        rows = asyncio.run(fetch())
    except ValueError as exc:  # e.g. DATABASE_URL not set
        print(f"make latency: {exc}", file=sys.stderr)
        return 1
    print("events (all requests; a stage that did not run records 0 ms)")
    print(render(rows))
    line = verdict(rows)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
