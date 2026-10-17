"""`make latency`: p50/p95 per stage from the Timescale `events` hypertable.

    python -m margin_relay.latency [--hours 24] [--outcome answered] [--all-outcomes]

Reads DATABASE_URL from config. Relay-side only: the pitch number (end-of-speech
to glance on the lens) adds the app's upload and render spans, which live in Sentry.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping
from typing import Any

from .config import get_settings
from .obs import STAGES

COLUMNS = (*STAGES, "total")
# A text request never runs STT and a gated not_found never runs generate/verify:
# zeros there are "stage skipped", not "stage was instant", so they are excluded.
SKIPPABLE = {"stt", "embed", "retrieve", "generate", "verify"}

QUERY = """
SELECT latency_ms FROM events
WHERE ts > now() - %(hours)s::float8 * interval '1 hour'
  AND (%(outcome)s::text IS NULL OR outcome = %(outcome)s::text)
ORDER BY ts DESC
LIMIT 100000
"""


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (same as Postgres percentile_cont)."""
    if not values:
        return math.nan
    data = sorted(values)
    pos = (len(data) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def summarize(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    """{stage: {n, p50, p95}} from latency_ms dicts."""
    samples: dict[str, list[float]] = {c: [] for c in COLUMNS}
    for row in rows:
        if isinstance(row, str):
            row = json.loads(row)
        for col in COLUMNS:
            value = row.get(col)
            if value is None:
                continue
            value = float(value)
            if col in SKIPPABLE and value <= 0:
                continue
            samples[col].append(value)
    return {c: {"n": len(v), "p50": percentile(v, 0.50), "p95": percentile(v, 0.95)}
            for c, v in samples.items()}


def render(summary: dict[str, dict[str, float]]) -> str:
    def ms(x: float) -> str:
        return "-" if math.isnan(x) else f"{x:.0f}"

    lines = [f"{'stage':<10}{'n':>7}{'p50 ms':>9}{'p95 ms':>9}", "-" * 35]
    for col in COLUMNS:
        s = summary[col]
        lines.append(f"{col:<10}{s['n']:>7}{ms(s['p50']):>9}{ms(s['p95']):>9}")
    return "\n".join(lines)


def fetch(hours: float, outcome: str | None) -> list[Any]:
    import psycopg

    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL is not set (make latency reads the events hypertable)")
    with psycopg.connect(settings.database_url.get_secret_value(), connect_timeout=10) as conn:
        rows = conn.execute(QUERY, {"hours": hours, "outcome": outcome}).fetchall()
    return [r[0] for r in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--outcome", default="answered")
    ap.add_argument("--all-outcomes", action="store_true")
    args = ap.parse_args(argv)
    outcome = None if args.all_outcomes else args.outcome
    rows = fetch(args.hours, outcome)
    print(f"events, last {args.hours:g} h, outcome={outcome or 'any'}: {len(rows)} rows")
    summary = summarize(rows)
    print(render(summary))
    p50 = summary["total"]["p50"]
    if not math.isnan(p50):
        verdict = "within" if p50 <= 3000 else "OVER"
        print(f"relay p50 total {p50:.0f} ms ({verdict} the 3 s end-of-speech-to-glance budget; "
              "add app upload + render from Sentry for the full number)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
