from __future__ import annotations

import json
import math

from margin_relay.latency import percentile, render, summarize


def test_percentile_matches_percentile_cont():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([10], 0.95) == 10
    assert math.isclose(percentile(list(range(1, 101)), 0.95), 95.05)
    assert math.isnan(percentile([], 0.5))


def test_summarize_skips_stages_that_did_not_run():
    rows = [
        {"stt": 0, "embed": 90, "retrieve": 150, "generate": 1000, "verify": 20, "total": 1300},
        {"stt": 600, "embed": 110, "retrieve": 170, "generate": 1400, "verify": 30, "total": 2400},
        json.dumps({"stt": 0, "embed": 100, "retrieve": 160, "generate": 0, "verify": 0,
                    "total": 280}),  # gated not_found, row as JSON text
    ]
    s = summarize(rows)
    assert s["stt"]["n"] == 1 and s["stt"]["p50"] == 600
    assert s["generate"]["n"] == 2 and s["generate"]["p50"] == 1200
    assert s["total"]["n"] == 3 and s["total"]["p50"] == 1300
    table = render(s)
    assert "generate" in table and "1200" in table


def test_render_empty():
    assert "-" in render(summarize([]))
