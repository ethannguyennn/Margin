"""The workspace (org) a request acts for. An admin's workspace code opens the portal;
a lens joins a workspace by entering that code in the Even app. Every SOP belongs to
one workspace, and retrieval, procedures and devices only see the current one.

Set per request by auth (portal code, device token) and read by db.py. ``None``
means unscoped: requests with no credential (tests, eval, the browser preview) see
every workspace, exactly like the single-tenant relay did.
"""

from __future__ import annotations

from contextvars import ContextVar

DEFAULT_ORG = "default"

_current: ContextVar[str | None] = ContextVar("specs_org", default=None)


def current() -> str | None:
    return _current.get()


def use(org_id: str | None) -> None:
    _current.set(org_id)
