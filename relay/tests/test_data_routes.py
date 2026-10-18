"""Published Part 3 HTTP handlers with explicit DB/provider fixtures, not live services."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from part5_support import RecordingConnection, RecordingPool, schema_dependencies
from db.seed import corpus_stats, load_corpus
from eval import run_eval as evaluation
from specs_relay import db
from specs_relay.config import Settings
from specs_relay.main import build_pipeline, create_app
from specs_relay.schemas import Chunk, RetrievalResult

# The industrial HX-2 bank these tests were written against (the demo bank in corpus/ is coffee).
HX2_CORPUS = Path(__file__).parent / "fixtures" / "hx2-corpus"
HX2_QA = HX2_CORPUS.parent / "hx2-qa.jsonl"


def fixture_app():
    settings = Settings(mock_mode=True, _env_file=None)
    pipeline = build_pipeline(settings)
    pipeline.db = db
    return create_app(settings, pipeline), pipeline


@pytest.mark.asyncio
async def test_real_procedure_handlers_serialize_five_docs_and_seven_steps(monkeypatch, schema_dependencies):
    documents, chunks = load_corpus(HX2_CORPUS)
    effective = [{k: d[k] for k in ("doc_id", "title", "revision", "status")}
                 for d in documents if d["status"] == "effective"]
    steps = [c for c in chunks if c["doc_id"] == "SOP-114" and c["revision"] == "C" and c["is_step"]]

    async def rows(query, params=()):
        return steps if "c.is_step" in query else effective

    monkeypatch.setattr(db, "_rows", rows)
    app, pipeline = fixture_app()
    pipeline.retriever = SimpleNamespace(steps_for=db.steps_for)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        response = await client.get("/v1/procedures")
        assert response.status_code == 200 and len(response.json()) == 5
        response = await client.get("/v1/procedures/SOP-114/steps")
        assert response.status_code == 200
        assert [step["label"] for step in response.json()] == [f"4.{i}" for i in range(1, 8)]
        assert response.json()[1]["step_id"] == "SOP-114:C:4.2"
        assert "4 N-m" in response.json()[1]["body"]


@pytest.mark.asyncio
async def test_actual_ask_returns_full_walkthrough_and_writes_event_metrics(monkeypatch, schema_dependencies):
    _, chunks = load_corpus(HX2_CORPUS)
    steps = [c for c in chunks if c["doc_id"] == "SOP-114" and c["revision"] == "C" and c["is_step"]]
    monkeypatch.setattr(db, "_rows", AsyncMock(return_value=steps))
    pool = RecordingPool()
    monkeypatch.setattr(db, "_pool", pool)
    app, pipeline = fixture_app()
    top = Chunk(**steps[1], title="Mounting Bracket Assembly")
    pipeline.retriever = SimpleNamespace(
        steps_for=db.steps_for,
        retrieve=AsyncMock(return_value=RetrievalResult(chunks=[top], best_sim=1, best_rrf=1)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        response = await client.post("/v1/ask", json={
            "session_id": str(uuid4()), "text": "Walk me through mounting bracket assembly"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["walkthrough"]["total"] == len(payload["walkthrough"]["steps"]) == 7
    assert payload["walkthrough"]["index"] == 0
    event = next(params for query, params, _ in pool.conn.calls if "INSERT INTO events" in query)
    assert "total" in event[-1].obj and event[-1].obj["stt"] == 0
    assert event[-2] == "Walk me through mounting bracket assembly"


@pytest.mark.asyncio
async def test_actual_deviation_handler_still_stores_row_when_notifier_raises(monkeypatch):
    pool = RecordingPool(RecordingConnection([{"value": 12}]))
    monkeypatch.setattr(db, "_pool", pool)
    app, pipeline = fixture_app()
    pipeline.notifier = SimpleNamespace(notify=AsyncMock(side_effect=RuntimeError("fixture outage")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        response = await client.post("/v1/deviation", json={
            "session_id": str(uuid4()), "text": "Synthetic bracket gap",
            "doc_id": "SOP-114", "step_id": "SOP-114:C:4.3"})
    assert response.status_code == 200
    assert response.json() == {"deviation_id": "DEV-0012", "notified": False}
    inserted = next(params for query, params, _ in pool.conn.calls if "INSERT INTO deviations" in query)
    assert inserted[-1] is False and pool.conn.committed
    # This test proves route failure handling only. Part 3 must still replace
    # its notify-before-insert orchestration with walkthrough.log_deviation.


@pytest.mark.asyncio
async def test_authenticated_ingest_uses_actual_entry_point_from_another_cwd(monkeypatch, tmp_path):
    from google import genai
    settings = Settings(
        mock_mode=True, admin_token="fixture-admin-token", gemini_api_key="fixture-not-a-real-key",
        gemini_model_embed="fixture-model", embed_dim=3, _env_file=None)
    pipeline = build_pipeline(settings)
    pipeline.db, pipeline.real_db = db, True
    app = create_app(settings, pipeline)
    calls = []

    class FixtureClient:
        def __init__(self, **kwargs):
            self.aio = self
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def embed_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[1, 0, 0]) for _ in kwargs["contents"]])

    async def store(documents, chunks):
        return corpus_stats(documents, chunks)

    monkeypatch.setattr(genai, "Client", FixtureClient)
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    monkeypatch.setattr(db, "upsert_corpus", store)
    monkeypatch.chdir(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        denied = await client.post("/v1/ingest")
        assert denied.status_code == 401 and not calls
        response = await client.post("/v1/ingest", headers={"authorization": "Bearer fixture-admin-token"})
    assert response.status_code == 200
    # The real entry point ingests the shipped demo bank in corpus/, in batches of 32.
    shipped = len(load_corpus(HX2_CORPUS.parents[3] / "corpus")[1])
    assert sum(row["chunks"] for row in response.json()["result"]) == shipped
    assert [len(call["contents"]) for call in calls] == [min(32, shipped - i) for i in range(0, shipped, 32)]


@pytest.mark.asyncio
async def test_evaluator_runs_against_actual_mock_relay_and_labels_evidence(capsys):
    settings = Settings(mock_mode=True, _env_file=None)
    app = create_app(settings)
    cases = evaluation.load_cases(HX2_QA)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        results, evidence = await evaluation.run_suite(client, cases, evaluation.citation_index(HX2_CORPUS), allow_mock=True)
    metrics = evaluation.print_report(results, evidence)
    assert metrics["cases"] == 36
    assert evidence == "MOCK/FIXTURE ONLY"
    assert "Specs [MOCK/FIXTURE ONLY]" in capsys.readouterr().out
