"""Paced, scored v3 loop checks. Importing this module never sends requests."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eval import run_eval


def cases():
    bank = {case["id"]: case for case in run_eval.load_cases(ROOT / "eval/qa.jsonl")}
    selected = [bank[key] for key in ("v3-w2", "v3-w3", "v3-w4", "v3-w5", "v3-c5", "v3-f1", "v3-p1")]
    selected.extend([
        {**bank["v3-c5"], "id": "gap-syrup", "q": "How many pumps of syrup?",
         "turns": [{"q": "cappuccino", "expect": "answered", "doc_id": "SOP-230",
                    "revision": "C", "section": "1.3", "must_contain": ["2", "3", "4"]}]},
        {**bank["v3-w4"], "id": "gap-standards", "q": "Pull up the espresso standards."},
        {**bank["v3-w2"], "id": "gap-cash-count", "q": "I need to do the cash count for closing."},
        {**bank["v3-w3"], "id": "gap-opening", "q": "Let's start the back of house opening."},
        {**bank["v3-w3"], "id": "gap-cleaning", "q": "Open the cleaning procedure.",
         "section": "5.1", "scope_end": "5.4"},
    ])
    return selected


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="http://127.0.0.1:8090")
    parser.add_argument("--pace", type=float, default=6)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    async with httpx.AsyncClient(base_url=args.relay.rstrip("/"), timeout=90) as client:
        results, evidence = await run_eval.run_suite(client, cases(), run_eval.citation_index(), pace=args.pace)
        health = (await client.get("/v1/health?verbose=1")).json() if args.output else {}
    metrics = run_eval.print_report(results, evidence)
    if args.output:
        args.output.write_text(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
            "relay": args.relay, "models": health.get("models"), "evidence": evidence,
            "metrics": metrics, "results": [asdict(r) for r in results]}, indent=2) + "\n", encoding="utf-8")
    return run_eval.exit_code(metrics)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"Gap probe unavailable ({type(exc).__name__}); no passing live evidence.", file=sys.stderr)
        raise SystemExit(1)
