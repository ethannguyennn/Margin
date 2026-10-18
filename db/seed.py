"""Synthetic corpus ingestion. CLI: python db/seed.py [--check | --probe-only]."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import date
import json
import math
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay/src"))
from specs_relay import db

HEADING = re.compile(r"^#{2,6}\s+(\d+(?:\.\d+)*)\s+(.+?)\s*$", re.MULTILINE)
ORDERED = re.compile(r"^\s*(\d+)\.\s+", re.MULTILINE)


def parse_document(path: Path) -> tuple[dict, list[dict]]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", raw, re.DOTALL)
    if match is None:
        raise ValueError(f"{path.name}: missing YAML front matter")
    metadata = yaml.safe_load(match[1])
    if not isinstance(metadata, dict) or metadata.get("synthetic") is not True:
        raise ValueError(f"{path.name}: corpus must explicitly declare synthetic: true")
    for key in ("doc_id", "revision", "title", "status"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError(f"{path.name}: missing or invalid {key}")
    if not re.fullmatch(r"SOP-\d{3}", metadata["doc_id"]) or not re.fullmatch(r"[A-Z0-9]+", metadata["revision"]):
        raise ValueError(f"{path.name}: invalid document/revision identifier")
    if metadata["status"] not in {"effective", "superseded", "draft"}:
        raise ValueError(f"{path.name}: invalid status")
    effective_date = metadata.get("effective_date")
    if isinstance(effective_date, str):
        effective_date = date.fromisoformat(effective_date)
    if effective_date is not None and not isinstance(effective_date, date):
        raise ValueError(f"{path.name}: invalid effective_date")
    if metadata["status"] == "effective" and effective_date is None:
        raise ValueError(f"{path.name}: effective revision needs an effective_date")
    document = {key: metadata[key] for key in ("doc_id", "revision", "title", "status")}
    document["effective_date"] = effective_date
    chunks = []
    headings = list(HEADING.finditer(match[2]))
    sections = set()
    for index, heading in enumerate(headings):
        section, title = heading.groups()
        if section in sections:
            raise ValueError(f"{path.name}: duplicate section {section}")
        sections.add(section)
        stop = headings[index + 1].start() if index + 1 < len(headings) else len(match[2])
        text = match[2][heading.end():stop].strip()
        if not text:  # A structural heading such as "4 Procedure" is not a chunk.
            continue
        ordered = ORDERED.findall(text)
        if ordered and len(ordered) != 1:
            raise ValueError(f"{path.name}: use one numbered procedural step per section")
        is_step = bool(ordered)
        chunks.append({
            "chunk_id": f"{metadata['doc_id']}:{metadata['revision']}:{section}",
            "doc_id": metadata["doc_id"], "revision": metadata["revision"], "section": section,
            "heading": title, "text": text, "is_step": is_step,
            "step_order": int(ordered[0]) if is_step else None,
        })
    orders = [chunk["step_order"] for chunk in chunks if chunk["is_step"]]
    if not chunks or not orders or orders != list(range(1, len(orders) + 1)):
        raise ValueError(f"{path.name}: procedural steps must be contiguous and ordered from 1")
    return document, chunks


def load_corpus(path: Path = ROOT / "corpus") -> tuple[list[dict], list[dict]]:
    documents, chunks = [], []
    for source in sorted(path.glob("*.md")):
        document, sections = parse_document(source)
        documents.append(document)
        chunks.extend(sections)
    keys = [(doc["doc_id"], doc["revision"]) for doc in documents]
    if not keys or len(keys) != len(set(keys)):
        raise ValueError("Corpus is empty or contains duplicate document revisions")
    effective = Counter(doc["doc_id"] for doc in documents if doc["status"] == "effective")
    if any(count > 1 for count in effective.values()):
        raise ValueError("Only one effective revision per document is allowed")
    return documents, chunks


def corpus_stats(documents: list[dict], chunks: list[dict]) -> list[dict]:
    return [
        {"doc_id": doc["doc_id"], "revision": doc["revision"], "status": doc["status"],
         "chunks": sum(c["doc_id"] == doc["doc_id"] and c["revision"] == doc["revision"] for c in chunks),
         "steps": sum(c["doc_id"] == doc["doc_id"] and c["revision"] == doc["revision"] and c["is_step"]
                      for c in chunks)}
        for doc in documents
    ]


async def gemini_embeddings(texts: list[str], settings, batch_size: int) -> list[list[float]]:
    from google import genai
    from google.genai import types

    key = db.setting(settings, "GEMINI_API_KEY")
    key = key.get_secret_value() if hasattr(key, "get_secret_value") else key
    model = db.setting(settings, "GEMINI_MODEL_EMBED")
    dimension = db.embedding_dimension(db.setting(settings, "EMBED_DIM"))
    if not key or not model:
        raise ValueError("GEMINI_API_KEY and GEMINI_MODEL_EMBED are required in Part 3 config")
    # Model selection always comes from config. Embedding 2 uses prompt-based
    # task instructions; earlier models use RETRIEVAL_DOCUMENT (Google docs).
    prompt_tasks = "gemini-embedding-2" in model
    config = types.EmbedContentConfig(
        output_dimensionality=dimension,
        **({} if prompt_tasks else {"task_type": "RETRIEVAL_DOCUMENT"}),
    )
    vectors = []
    async with genai.Client(api_key=key).aio as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            # Explicit Content objects prevent Embedding 2 from aggregating
            # multiple chunks into one vector.
            contents = [types.Content(parts=[types.Part.from_text(
                text=("title: none | text: " + text) if prompt_tasks else text
            )]) for text in batch]
            async with asyncio.timeout(30):
                response = await client.models.embed_content(model=model, contents=contents, config=config)
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch):
                raise ValueError("Embedding provider returned the wrong number of vectors")
            for embedding in embeddings:
                values = list(embedding.values or [])
                db.vector_literal(values, dimension)
                norm = math.sqrt(sum(float(value) ** 2 for value in values))
                if not math.isfinite(norm) or norm == 0:
                    raise ValueError("Embedding norm is invalid")
                vectors.append([float(value) / norm for value in values])
    return vectors


async def ingest(corpus_dir: Path = ROOT / "corpus", *, settings=None,
                 embedder=None, batch_size: int = 32) -> list[dict]:
    """Part 3's authenticated ingest route calls this after init_pool.

    All provider work completes before the atomic DB write. The injected
    embedder(texts, settings, batch_size) is for independent fixture tests.
    """
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    documents, chunks = load_corpus(corpus_dir)
    settings = settings if settings is not None else db.get_settings()
    dimension = db.embedding_dimension(db.setting(settings, "EMBED_DIM"))
    titles = {(d["doc_id"], d["revision"]): d["title"] for d in documents}
    texts = [f"{c['doc_id']} rev {c['revision']}: {titles[c['doc_id'], c['revision']]}\n"
             f"Sec {c['section']} {c['heading']}\n{c['text']}" for c in chunks]
    embeddings = await (embedder or gemini_embeddings)(texts, settings, batch_size)
    if len(embeddings) != len(chunks):
        raise ValueError("Embedding count must match chunk count")
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        db.vector_literal(embedding, dimension)
        chunk["embedding"] = embedding
    return await db.upsert_corpus(documents, chunks)


def print_stats(stats: list[dict]) -> None:
    print("Document  Rev  Chunks  Steps")
    for row in stats:
        print(f"{row['doc_id']:<9} {row['revision']:<4} {row['chunks']:>6} {row['steps']:>6}")
    print(f"Total: {sum(row['chunks'] for row in stats)} chunks, {sum(row['steps'] for row in stats)} steps")


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Parse/count only; no config, DB, or API calls")
    mode.add_argument("--probe-only", action="store_true", help="Check actual DB capabilities; roll back probes")
    mode.add_argument("--migrate-only", action="store_true", help="Apply idempotent migrations without seeding")
    mode.add_argument("--probe-v2-only", action="store_true", help="Apply migrations twice in a rollback-only synthetic schema")
    mode.add_argument("--from-drafts", action="store_true", help="Republish approved drafts stored in this database")
    args = parser.parse_args(argv)
    if args.check:
        documents, chunks = load_corpus()
        print("LOCAL CORPUS CHECK ONLY: no rows seeded and no embedding calls made.")
        print_stats(corpus_stats(documents, chunks))
        return 0
    try:
        settings = db.get_settings()
        await db.init_pool(settings)
        if args.probe_v2_only:
            print("V2 synthetic migration probe:", json.dumps(await db.validate_v2_migration(), sort_keys=True))
            return 0
        print("Database capability probe:", json.dumps(await db.validate_capabilities(), sort_keys=True))
        if not args.probe_only:
            before = await db.storage_counts() if args.migrate_only else None
            await db.apply_migrations()
            if args.migrate_only:
                print("Migration row counts:", json.dumps({"before": before, "after": await db.storage_counts()}, sort_keys=True))
            elif args.from_drafts:
                from specs_relay.walkthrough import publish_draft
                for draft in await db.approved_drafts():
                    print(json.dumps(await publish_draft(draft, settings=settings), sort_keys=True))
            elif not args.migrate_only:
                print_stats(await ingest(settings=settings))
        return 0
    finally:
        await db.close_pool()


if __name__ == "__main__":
    try:
        # psycopg async cannot run on Windows' default ProactorEventLoop.
        win = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
        raise SystemExit(asyncio.run(main(), **win))
    except Exception as exc:
        # Provider/connection errors may contain credentials. Do not print them.
        print(f"Seed failed ({type(exc).__name__}); check Part 3 config, credentials, and service access.",
              file=sys.stderr)
        raise SystemExit(1)
