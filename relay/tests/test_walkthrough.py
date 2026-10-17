from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from part5_support import RecordingConnection, RecordingPool, schema_dependencies
from db.seed import load_corpus
from margin_relay import db, walkthrough
from margin_relay.notify import ConsoleNotifier, get_notifier


def test_every_corpus_step_preserves_its_full_sanitized_text(schema_dependencies):
    _, chunks = load_corpus()
    steps = [walkthrough.step_from_chunk(c) for c in chunks if c["is_step"]]
    assert len(steps) == 35
    assert all(0 < len(s.glance) < 60 and 0 < len(s.body) < 450 for s in steps)
    assert all(s.label == s.step_id.split(":")[2] for s in steps)
    cleaning = next(s for s in steps if s.step_id == "SOP-120:B:4.1")
    assert "degC" in cleaning.body and "°" not in cleaning.body
    filtering = next(s for s in steps if s.step_id == "SOP-120:B:4.2")
    assert "5 um" in filtering.body and "µ" not in filtering.body
    fastening = next(s for s in steps if s.step_id == "SOP-114:C:4.2")
    assert fastening.body.endswith("do not click twice.")


def test_oversized_body_is_rejected_instead_of_cutting_off_a_warning(schema_dependencies):
    with pytest.raises(ValueError, match="sanitized body"):
        walkthrough.step_from_chunk({"chunk_id": "SOP-114:C:4.2", "section": "4.2",
                                     "heading": "Fastening", "text": "1. " + "a" * 450})


@pytest.mark.asyncio
async def test_walkthrough_returns_all_steps_and_pins_revision(monkeypatch, schema_dependencies):
    _, chunks = load_corpus()
    steps = [walkthrough.step_from_chunk(c) for c in chunks
             if c["doc_id"] == "SOP-114" and c["revision"] == "C" and c["is_step"]]
    monkeypatch.setattr(db, "document_for", AsyncMock(return_value={
        "doc_id": "SOP-114", "revision": "C", "title": "Mounting Bracket Assembly"}))
    lookup = AsyncMock(return_value=steps)
    monkeypatch.setattr(db, "steps_for", lookup)
    result = await walkthrough.build_walkthrough("SOP-114")
    lookup.assert_awaited_once_with("SOP-114", "C")
    assert result["total"] == 7 and result["index"] == 0
    assert len(result["steps"]) == 7
    assert result["steps"][3]["label"] == "4.4"
    assert result["steps"][-1]["step_id"] == "SOP-114:C:4.7"


@pytest.mark.asyncio
async def test_missing_procedure_has_no_fake_walkthrough(monkeypatch):
    monkeypatch.setattr(db, "document_for", AsyncMock(return_value=None))
    with pytest.raises(LookupError):
        await walkthrough.build_walkthrough("SOP-999")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "false"])
async def test_deviation_is_committed_before_notification_and_survives_failure(monkeypatch, failure):
    connection = RecordingConnection([{"value": 7}])
    pool = RecordingPool(connection)
    monkeypatch.setattr(db, "_pool", pool)

    class FailingNotifier:
        async def notify(self, deviation_id, text):
            inserts = [c for c in connection.calls if "INSERT INTO deviations" in c[0]]
            assert len(inserts) == 1 and connection.committed
            assert deviation_id == "DEV-0007" and text == "Bracket gap failed"
            if failure == "exception":
                raise RuntimeError("provider unavailable")
            return False

    result = await walkthrough.log_deviation(
        None, "Bracket gap failed", "SOP-114", "SOP-114:C:4.3", notifier=FailingNotifier())
    assert result == {"deviation_id": "DEV-0007", "notified": False}
    insert = next(c for c in connection.calls if "INSERT INTO deviations" in c[0])
    assert insert[1][-1] is False
    assert not any("UPDATE deviations" in c[0] for c in connection.calls)


@pytest.mark.asyncio
async def test_console_success_persists_notification_status(monkeypatch, caplog):
    pool = RecordingPool(RecordingConnection([{"value": 8}]))
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(notifier="console"))
    with caplog.at_level("INFO"):
        result = await walkthrough.log_deviation(None, "Synthetic test observation")
    assert result == {"deviation_id": "DEV-0008", "notified": True}
    assert "DEV-0008" in caplog.text
    assert any("UPDATE deviations" in query and params == (True, "DEV-0008")
               for query, params, _ in pool.conn.calls)


@pytest.mark.asyncio
async def test_status_write_failure_returns_the_stored_false_status(monkeypatch):
    monkeypatch.setattr(db, "next_deviation_id", AsyncMock(return_value="DEV-0009"))
    insert = AsyncMock()
    monkeypatch.setattr(db, "insert_deviation", insert)
    monkeypatch.setattr(db, "set_deviation_notified", AsyncMock(side_effect=RuntimeError("DB went away")))
    result = await walkthrough.log_deviation(None, "test", notifier=ConsoleNotifier())
    assert result["notified"] is False and insert.await_count == 1


@pytest.mark.asyncio
async def test_insert_failure_never_sends_an_alert(monkeypatch):
    monkeypatch.setattr(db, "next_deviation_id", AsyncMock(return_value="DEV-0010"))
    monkeypatch.setattr(db, "insert_deviation", AsyncMock(side_effect=RuntimeError("insert failed")))
    notifier = SimpleNamespace(notify=AsyncMock())
    with pytest.raises(RuntimeError):
        await walkthrough.log_deviation(None, "test", notifier=notifier)
    notifier.notify.assert_not_awaited()


def test_photon_is_not_enabled_without_a_verified_implementation():
    with pytest.raises(ValueError, match="Photon"):
        get_notifier(SimpleNamespace(notifier="photon"))
