"""Deploy main over existing SSH key authentication; never copy local secrets."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def destination(value: str) -> str:
    # Keep this an SSH destination, never an option or a shell expression.
    if not re.fullmatch(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("VM_HOST must be an SSH host alias or user@hostname")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="")
    args = parser.parse_args()
    host = args.host or os.environ.get("VM_HOST") or dotenv_values(ROOT / ".env").get("VM_HOST") or ""
    try:
        host = destination(host)
    except ValueError as exc:
        parser.error(str(exc) + "; configure VM_HOST in .env or pass VM_HOST=... to make")
    # Refuse accidental feature-branch deployments or tracked VM edits. Pull is
    # fast-forward only; .env stays exclusively on the VM. No compose down.
    command = ('cd /root/specs && test "$(git branch --show-current)" = main '
               '&& git diff --quiet && git diff --cached --quiet '
               '&& git pull --ff-only origin main && make deploy')
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
                          cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
