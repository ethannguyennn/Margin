"""Paced regression: six step questions, three independent repetitions (18 asks)."""
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
from tools.diagnostic.voice_loop import ASK


def cases():
    return [{"id": f"clarify-rate-{rep}-{sid}", "category": "regression", "q": question,
             "expect": "answered", "doc_id": "SOP-210", "revision": "C", "section": section,
             "must_contain": [fact], "request_revision": "C",
             "context": {"doc_id": "SOP-210", "step_id": f"SOP-210:C:{section}"}}
            for rep in range(1, 4) for sid, question, section, fact in ASK]


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="http://127.0.0.1:8090")
    parser.add_argument("--pace", type=float, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    async with httpx.AsyncClient(base_url=args.relay.rstrip("/"), timeout=90) as client:
        results, evidence = await run_eval.run_suite(client, cases(), run_eval.citation_index(), pace=args.pace)
        health = (await client.get("/v1/health?verbose=1")).json()
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
        print(f"Step-question regression unavailable ({type(exc).__name__}); no passing live evidence.", file=sys.stderr)
        raise SystemExit(1)
