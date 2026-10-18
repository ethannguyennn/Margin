"""Test-only stand-ins until scaffold-relay arrives. Never imported by production."""
from contextlib import asynccontextmanager
import importlib
from pathlib import Path
import sys
from types import ModuleType

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "relay/src"))


@pytest.fixture
def schema_dependencies(monkeypatch):
    """Use actual shared modules when present; otherwise isolate explicit fixtures."""
    try:
        importlib.import_module("specs_relay.schemas")
    except ModuleNotFoundError as exc:
        if exc.name != "specs_relay.schemas":
            raise
        module = ModuleType("specs_relay.schemas")

        class FixtureChunk(BaseModel):
            chunk_id: str
            doc_id: str
            revision: str
            section: str
            is_step: bool = False
            step_order: int | None = None
            heading: str | None = None
            text: str
            score: float = 0
            sim: float | None = None

        class FixtureStep(BaseModel):
            step_id: str
            label: str
            glance: str
            body: str

        module.Chunk, module.Step = FixtureChunk, FixtureStep
        monkeypatch.setitem(sys.modules, module.__name__, module)
    try:
        importlib.import_module("specs_relay.pipeline.sanitize")
    except ModuleNotFoundError as exc:
        if exc.name not in {"specs_relay.pipeline", "specs_relay.pipeline.sanitize"}:
            raise
        if "specs_relay.pipeline" not in sys.modules:
            package = ModuleType("specs_relay.pipeline")
            package.__path__ = []
            monkeypatch.setitem(sys.modules, package.__name__, package)
        module = ModuleType("specs_relay.pipeline.sanitize")

        def fixture_sanitize(text):
            # Deliberately scoped to glyphs in our synthetic corpus; does not
            # claim to implement or validate Part 4's full sanitizer.
            return text.replace("°", " deg").replace("µ", "u")

        module.sanitize = fixture_sanitize
        monkeypatch.setitem(sys.modules, module.__name__, module)


class Cursor:
    def __init__(self, rows=(), rowcount=1):
        self.rows = list(rows)
        self.rowcount = rowcount

    async def fetchall(self):
        return self.rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None


class RecordingConnection:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self.fail_at = None

    async def execute(self, query, params=(), **kwargs):
        self.calls.append((str(query), params, kwargs))
        if len(self.calls) == self.fail_at:
            raise RuntimeError("injected query failure")
        return Cursor(self.rows)

    @asynccontextmanager
    async def transaction(self):
        try:
            yield self
        except BaseException:
            self.rolled_back = True
            raise


class RecordingPool:
    closed = False

    def __init__(self, connection=None):
        self.conn = connection or RecordingConnection()
        self.checkouts = 0

    @asynccontextmanager
    async def connection(self):
        self.checkouts += 1
        try:
            yield self.conn
        except BaseException:
            self.conn.rolled_back = True
            raise
        else:
            self.conn.committed = True

    async def close(self):
        self.closed = True
