# Windows: psycopg async needs a SelectorEventLoop; uvicorn's CLI picks Proactor.
import asyncio
import sys

import uvicorn

sys.path.insert(0, "relay/src")
from specs_relay.main import create_app  # noqa: E402

server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=8090, log_level="info"))
asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
