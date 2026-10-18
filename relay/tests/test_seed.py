from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from part5_support import ROOT, schema_dependencies
from db import seed
from specs_relay import db


def test_corpus_has_five_effective_procedures_and_a_draft_revision():
    documents, chunks = seed.load_corpus()
    assert len(documents) == 6
    assert len({d["doc_id"] for d in documents}) == 5
    assert {(d["doc_id"], d["revision"]) for d in documents if d["status"] == "effective"} == {
        ("SOP-101", "A"), ("SOP-114", "C"), ("SOP-120", "B"), ("SOP-131", "A"), ("SOP-140", "A")}
    assert next(d for d in documents if d["revision"] == "D")["status"] == "draft"
    assert len(chunks) == 59
    assert sum(c["is_step"] for c in chunks) == 35
    assert all(c["chunk_id"] == f"{c['doc_id']}:{c['revision']}:{c['section']}" for c in chunks)
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
    assert all(c["text"] for c in chunks)


def test_revision_change_is_narrow_and_cross_reference_exists():
    _, chunks = seed.load_corpus()
    index = {c["chunk_id"]: c for c in chunks}
    c, d = index["SOP-114:C:4.2"], index["SOP-114:D:4.2"]
    assert c["text"].replace("4 N-m", "5 N-m") == d["text"]
    assert "SOP-131" in c["text"]
    assert "SOP-131:A:4.4" in index
    assert "SOP-114:D:4.8" in index and "SOP-114:C:4.8" not in index
    assert "°" in index["SOP-120:B:4.1"]["text"]
    assert "µ" in index["SOP-120:B:4.2"]["text"]


@pytest.mark.parametrize("old,new,error", [
    ("synthetic: true", "synthetic: false", "synthetic"),
    ("### 4.2", "### 4.1", "duplicate section"),
    ("2. Inspect all six", "9. Inspect all six", "contiguous"),
    ("status: effective", "status: released", "invalid status"),
    ("effective_date: 2026-03-01", "effective_date: null", "effective_date"),
    ("revision: A", "revision: A:B", "identifier"),
])
def test_invalid_corpus_is_rejected(tmp_path, old, new, error):
    raw = (ROOT / "corpus/SOP-101-A.md").read_text(encoding="utf-8").replace(old, new)
    path = tmp_path / "invalid.md"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        seed.parse_document(path)


def test_utf8_bom_crlf_and_structure_only_heading(tmp_path):
    raw = (ROOT / "corpus/SOP-101-A.md").read_text(encoding="utf-8")
    path = tmp_path / "windows.md"
    path.write_bytes(("\ufeff" + raw.replace("\n", "\r\n")).encode("utf-8"))
    document, chunks = seed.parse_document(path)
    assert document["effective_date"].isoformat() == "2026-03-01"
    assert "4" not in {chunk["section"] for chunk in chunks}
    assert chunks[1]["text"].startswith("| Item")
    assert chunks[2]["text"].startswith("> WARNING")


@pytest.mark.asyncio
async def test_ingestion_repeats_stable_ids_and_content(monkeypatch):
    settings = SimpleNamespace(embed_dim=3)
    writes = []

    async def embeddings(texts, config, batch_size):
        assert config is settings and batch_size == 32
        assert len(texts) == 59 and "Sec 4.2" in " ".join(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]

    async def upsert(documents, chunks):
        writes.append((documents, chunks))
        return seed.corpus_stats(documents, chunks)

    monkeypatch.setattr(db, "upsert_corpus", upsert)
    first = await seed.ingest(settings=settings, embedder=embeddings)
    second = await seed.ingest(settings=settings, embedder=embeddings)
    assert first == second and writes[0] == writes[1]
    # This checks ingestion identity; SQL idempotence is covered only by the
    # opt-in live database suite, not claimed from an in-memory fixture.


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[], [[1, 0]], [[0, 0, 0]], [[float("nan"), 0, 1]]])
async def test_invalid_embeddings_never_reach_database(monkeypatch, vectors):
    write = AsyncMock()
    monkeypatch.setattr(db, "upsert_corpus", write)

    async def embed(texts, settings, size):
        return vectors if not vectors else vectors * len(texts)

    with pytest.raises(ValueError):
        await seed.ingest(settings=SimpleNamespace(embed_dim=3), embedder=embed)
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model,prompt_tasks", [("gemini-embedding-001", False), ("gemini-embedding-2", True)])
async def test_sdk_batches_separate_content_objects_and_normalizes(monkeypatch, model, prompt_tasks):
    from google import genai
    calls = []

    class Client:
        def __init__(self, **kwargs):
            self.aio = self
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def embed_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[3.0, 4.0, 0.0])
                                              for _ in kwargs["contents"]])

    monkeypatch.setattr(genai, "Client", Client)
    vectors = await seed.gemini_embeddings(
        ["alpha", "beta", "gamma"], SimpleNamespace(
            gemini_api_key="fixture-only-not-a-key", gemini_model_embed=model, embed_dim=3), 2)
    assert [len(c["contents"]) for c in calls] == [2, 1]
    assert all(c["config"].output_dimensionality == 3 for c in calls)
    assert calls[0]["contents"][0].parts[0].text == ("title: none | text: alpha" if prompt_tasks else "alpha")
    assert (calls[0]["config"].task_type is None) == prompt_tasks
    assert vectors == [[0.6, 0.8, 0.0]] * 3


@pytest.mark.asyncio
async def test_check_cli_needs_no_settings(monkeypatch, capsys):
    monkeypatch.setattr(db, "get_settings", lambda: pytest.fail("check mode read config"))
    assert await seed.main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "no rows seeded" in output and "59 chunks, 35 steps" in output
