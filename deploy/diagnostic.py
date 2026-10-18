"""Opt-in live diagnostics; wrappers preserve the other parts' probe ownership."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen
import wave

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "tools/diagnostic"


def origin(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.path not in {"", "/"} or url.query or url.fragment):
        raise argparse.ArgumentTypeError("RELAY must be a full HTTP(S) origin without credentials or a path")
    return value.rstrip("/")


def pace(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError("PACE must be finite seconds >= 0")
    return seconds


def check_live(relay: str) -> None:
    with urlopen(f"{relay}/v1/health", timeout=10) as response:
        health = json.load(response)
    if health.get("ok") is not True or health.get("mock") is not False or health.get("db") != "ok":
        raise RuntimeError("diagnostics require healthy, non-mock asks and db=ok")


def voice_module():
    spec = importlib.util.spec_from_file_location("specs_voice_diagnostic", DIAG / "voice_loop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(module, *args: str) -> None:
    previous = sys.argv
    try:
        sys.argv = [str(DIAG / "voice_loop.py"), *args]
        module.main()
    finally:
        sys.argv = previous


def prepare_voice(module) -> None:
    invoke(module, "prepare")
    if sys.platform == "win32":
        subprocess.run(["powershell.exe", "-NoProfile", "-File", str(DIAG / "tts.ps1")],
                       cwd=ROOT, check=True)
    # On macOS/Linux, use the same synthetic corpus generated on Windows. Check
    # all files before spending quota, including the PCM format expected by the relay.
    for i in range(len(module.ALL)):
        path = DIAG / "wav" / f"{i}.wav"
        if not path.is_file():
            raise RuntimeError(f"missing synthetic wav/{i}.wav; copy the prepared Windows wav/ corpus")
        with wave.open(str(path)) as audio:
            if ((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2)
                    or audio.getnframes() == 0 or audio.getcomptype() != "NONE"):
                raise RuntimeError(f"invalid synthetic audio format: wav/{i}.wav")


def assert_voice_results(path: Path, expected: set[str]) -> None:
    results = json.loads(path.read_text(encoding="utf-8"))
    if set(results) != expected or any(row.get("pass") is not True for row in results.values()):
        raise RuntimeError("voice diagnostic failed or returned incomplete results; see tools/diagnostic/results.json")


def run_voice(relay: str, seconds: float) -> None:
    module = voice_module()
    prepare_voice(module)
    module.RELAY = relay
    results = DIAG / "results.json"
    # Never accept an earlier run's evidence after a failed request.
    results.unlink(missing_ok=True)
    invoke(module, "run", str(seconds))
    assert_voice_results(results, {row[0] for row in module.ALL})


def run_loop(relay: str, seconds: float) -> None:
    module = voice_module()
    prepare_voice(module)
    target = ROOT / "app/tests/zz-diagnostic-loop.test.ts"
    if target.exists():
        raise RuntimeError("app/tests/zz-diagnostic-loop.test.ts already exists; preserve it before running diag-loop")
    env = {**os.environ, "SPECS_DIAG_RELAY": relay, "SPECS_DIAG_PACE_MS": str(round(seconds * 1000)),
           "SPECS_DIAG_TIMEOUT_MS": "50000", "SPECS_DIAG_WAV": (DIAG / "wav").as_uri() + "/"}
    try:
        shutil.copyfile(DIAG / "loop.test.ts", target)
        # Avoid shell quoting and npx network installs; make install supplies Vitest.
        subprocess.run(["node", "node_modules/vitest/vitest.mjs", "run", f"tests/{target.name}",
                        "--disableConsoleIntercept"], cwd=ROOT / "app", env=env, check=True)
    finally:
        target.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["voice", "gap", "loop"])
    parser.add_argument("--relay", type=origin, default="http://127.0.0.1:8090")
    parser.add_argument("--pace", type=pace, default=10.0, help="seconds between requests")
    args = parser.parse_args(argv)
    try:
        if args.check == "gap":
            raise RuntimeError("blocked on Part 2: gap_probe.py needs --relay, --pace, a main guard, and assertion-based exit status")
        check_live(args.relay)
        print(f"Live {args.check} diagnostic: {args.relay}, pace={args.pace:g}s", flush=True)
        {"voice": run_voice, "loop": run_loop}[args.check](args.relay, args.pace)
    except Exception as exc:
        # Do not dump provider request/response bodies or environment values.
        print(f"diagnostic failed: {exc if isinstance(exc, RuntimeError) else type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
