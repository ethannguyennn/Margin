"""Portable diagnostic relay launcher (Python 3.11+, Selector loop on Windows)."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", default="http://127.0.0.1:8090")
    args = parser.parse_args()
    url = urlsplit(args.relay)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("diag-relay starts a local HTTP server; use diag-voice/gap/loop for a remote RELAY")
    if url.path not in {"", "/"} or url.query or url.fragment or url.username or url.password:
        parser.error("RELAY must be a full origin without credentials or a path")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "relay/src"))
    import uvicorn
    from specs_relay.main import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host=url.hostname,
                                         port=url.port or 80, log_level="info"))
    # Runner's loop_factory is supported on 3.11; asyncio.run's requires 3.12.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(server.serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
