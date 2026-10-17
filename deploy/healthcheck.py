"""Relay health probe (stdlib only). Used by the compose healthcheck and `make health`.

    python healthcheck.py [--url URL] [--kill] [--verbose]

Exit 0 when GET /v1/health answers 200 within a few tries. With --kill (inside the
container), a relay that is up but no longer answering gets SIGTERM on PID 1 so the
restart policy brings it back: plain Docker only restarts containers that exit,
never ones that are merely "unhealthy". Never kills during the first 60 s of boot.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

BOOT_GRACE_S = 60.0


def probe(url: str, tries: int = 3, timeout: float = 3.0, verbose: bool = False) -> bool:
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", "replace")
                if verbose:
                    print(f"{resp.status} {body}")
                    print(f"x-trace-id: {resp.headers.get('x-trace-id')}")
                if resp.status == 200 and json.loads(body).get("ok") is not None:
                    return True
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if verbose:
                print(f"attempt {attempt}: {exc}", file=sys.stderr)
        if attempt < tries:
            time.sleep(2.0)
    return False


def pid1_uptime_s() -> float:
    """Seconds since PID 1 started (Linux /proc); huge if unknown, so --kill still works."""
    try:
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        with open("/proc/1/stat") as f:
            start_ticks = float(f.read().rsplit(")", 1)[1].split()[19])
        return uptime - start_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return float("inf")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080/v1/health")
    ap.add_argument("--kill", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if probe(args.url, verbose=args.verbose):
        return 0
    if args.kill and pid1_uptime_s() > BOOT_GRACE_S:
        print("relay unresponsive: SIGTERM to PID 1 so the restart policy restarts it",
              file=sys.stderr)
        os.kill(1, signal.SIGTERM)
    return 1


if __name__ == "__main__":
    sys.exit(main())
