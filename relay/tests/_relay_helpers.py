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


# --- v2 helpers ---------------------------------------------------------------------

PORTAL_TOKEN = "portal-test-token"
PORTAL = {"authorization": f"Bearer {PORTAL_TOKEN}"}


def v2_client(**overrides: Any) -> tuple[TestClient, Any]:
    """Mock relay with the portal enabled. Enter it (`with client:`) so background
    conversion jobs keep one event loop alive between requests."""
    values: dict[str, Any] = {"portal_token": PORTAL_TOKEN}
    values.update(overrides)
    return make_client(**values)


def device(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def wait_material(client: TestClient, material_id: str, timeout: float = 10.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/v1/materials/{material_id}", headers=PORTAL).json()
        if body.get("status") != "converting" or time.monotonic() > deadline:
            return body
        time.sleep(0.02)


def pair_and_claim(client: TestClient, worker: str = "Bay 3") -> dict:
    pairing = client.post("/v1/devices/pair", json={"session_id": sid()}).json()
    claimed = client.post("/v1/devices/claim", headers=PORTAL,
                          json={"pair_code": pairing["pair_code"], "worker_name": worker})
    assert claimed.status_code == 200, claimed.text
    return pairing
