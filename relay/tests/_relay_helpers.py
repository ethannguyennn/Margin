"""Shared helpers for Part 3's tests (kept out of conftest.py so other parts' test
files can never collide with it)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

from margin_relay.config import Settings
from margin_relay.main import Pipeline, build_pipeline, create_app

ORIGIN = "http://localhost:5174"
DEVICE_ORIGIN = "https://evenhub.device.example"  # stand-in until the real one is read off a device


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(mock_mode=True, allowed_origins=f"{ORIGIN},{DEVICE_ORIGIN}",
                                  sentry_dsn_relay="", admin_token=None)
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_client(pipeline: Pipeline | None = None, **overrides: Any) -> tuple[TestClient, Any]:
    settings = make_settings(**overrides)
    app = create_app(settings, pipeline=pipeline or build_pipeline(settings))
    return TestClient(app, raise_server_exceptions=False), app


def sid() -> str:
    return str(uuid.uuid4())


def ask(client: TestClient, text: str, session_id: str | None = None, **extra: Any):
    return client.post("/v1/ask", json={"session_id": session_id or sid(), "text": text, **extra})
