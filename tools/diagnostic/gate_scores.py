"""best_sim / best_rrf from the live retriever for eval questions + walkthrough prompts.
Run from a repo root with PYTHONPATH=relay/src. Embedding calls only, no generation."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "relay/src")
from specs_relay.config import Settings  # noqa: E402
from specs_relay import db  # noqa: E402
from specs_relay.pipeline.generate import gemini_client  # noqa: E402
from specs_relay.pipeline.retrieve import GeminiEmbedder, Retriever  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WALK = [  # (prompt, expected doc or None for off-topic)
    ("getting the register ready before my shift", "SOP-201"), ("closing out the till at the end of the night", "SOP-202"),
    ("the kitchen opening checklist", "SOP-210"), ("pull a good espresso shot", "SOP-220"),
    ("making a cappuccino", "SOP-230"), ("cleaning the espresso machine at close", "SOP-210"),
    ("steaming milk", "SOP-220"), ("handling a refund", "SOP-202"),
    ("changing a flat tire", None), ("filing my taxes", None), ("resetting the wifi router", None),
    ("booking a flight to denver", None), ("replacing a car battery", None), ("training a new puppy", None),
]


async def main():
    s = Settings()
    await db.init_pool(s)
    r = Retriever.from_pool(db.pool(), GeminiEmbedder(gemini_client(s.gemini_api_key), s.gemini_model_embed, s.embed_dim))
    rows = [json.loads(line) for line in (ROOT / "eval/qa.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for q in rows:
        res = await r.retrieve(q["q"], None)
        out.append({"kind": q["expect"], "q": q["q"], "sim": res.best_sim, "rrf": res.best_rrf,
                    "top": res.chunks[0].chunk_id if res.chunks else None})
    for text, doc in WALK:
        res = await r.retrieve(text, None)
        out.append({"kind": "walk:" + (doc or "off"), "q": text, "sim": res.best_sim, "rrf": res.best_rrf,
                    "top": [c.chunk_id for c in res.chunks[:3]]})
    for o in sorted(out, key=lambda o: o["sim"]):
        print(f"{o['sim']:.3f} {o['rrf']:.4f} {o['kind']:14} {o['q'][:60]:60} {o['top']}")
    (Path(__file__).parent / "gate_scores.json").write_text(json.dumps(out, indent=1))


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
