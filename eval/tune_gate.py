"""Calibrate the cheap retrieval gate on the current QA bank and real database.

Only embedding/retrieval runs, never generation. Ambiguous cases must reach the
generator's clarification path, so they are protected just like answerable cases.
The report is development-bank calibration, not an independent quality evaluation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_eval import load_cases
from specs_relay import db
from specs_relay.config import Settings
from specs_relay.pipeline.generate import gemini_client
from specs_relay.pipeline.retrieve import GeminiEmbedder, Retriever, should_refuse, tune_gate


def calibration(samples: list[dict]) -> dict:
    if not samples or not any(s['protected'] for s in samples) or not any(not s['protected'] for s in samples):
        raise ValueError('Calibration needs both protected and unanswerable questions')
    sim, rrf, refused = tune_gate([(s['best_sim'], s['best_rrf'], s['protected']) for s in samples])
    return {'NOT_FOUND_MIN_SIM': sim, 'NOT_FOUND_MIN_RRF': rrf,
            'protected_false_refusals': sum(should_refuse(s['best_sim'], s['best_rrf'], sim, rrf)
                                            for s in samples if s['protected']),
            'cheap_refusals': refused, 'refusal_candidates': sum(not s['protected'] for s in samples)}


async def collect(cases: list[dict]) -> dict:
    settings = Settings()
    samples = []
    client = gemini_client(settings.gemini_api_key)
    retriever = Retriever(db.RetrievalStore(), GeminiEmbedder(client, settings.gemini_model_embed, settings.embed_dim))
    try:
        await db.init_pool(settings)
        for index, case in enumerate(cases, 1):
            result = await retriever.retrieve(case['q'], case.get('request_revision'))
            samples.append({'id': case['id'], 'question': case['q'], 'category': case['category'],
                            'protected': case['expect'] == 'answered' or case.get('needs_clarification', False),
                            'best_sim': result.best_sim, 'best_rrf': result.best_rrf})
            print(f'Retrieved {index}/{len(cases)}', flush=True)
        return {'evidence': 'LIVE EMBEDDINGS + CLOUD POSTGRES; no generation',
                'scope': 'development QA bank, not independent validation',
                'embedding_model': settings.gemini_model_embed, 'embed_dim': settings.embed_dim,
                'documents': await db.list_procedures(), 'thresholds': calibration(samples), 'samples': samples}
    finally:
        await db.close_pool()
        await client.aio.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qa', type=Path, default=ROOT / 'eval/qa.jsonl')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    options = {'loop_factory': asyncio.SelectorEventLoop} if sys.platform == 'win32' else {}
    try:
        report = asyncio.run(collect(load_cases(args.qa)), **options)
    except Exception as exc:
        # Provider errors may contain request details: don't dump credentials into reports.
        print(f'Calibration incomplete ({type(exc).__name__}); no thresholds changed.', file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps(report['thresholds']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
