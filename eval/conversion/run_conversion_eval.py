"""Conversion eval: every synthetic material through the real
extract -> convert -> verify_step -> render, no HTTP.

    python eval/conversion/run_conversion_eval.py --model <GEMINI_MODEL_CONVERT>
    python eval/conversion/run_conversion_eval.py --only SOP-153 --force-hallucination

Reports per material: steps found vs expected, values preserved (every
must_contain), steps failing verification, diagrams produced, and the gate,
the fabrication count: values (number+unit, part codes) in a step that appear
nowhere in the material. Exit 1 if any *passing* step contains a fabricated
value -- the regression that must never ship. Exit 0 otherwise; --strict also
exits 2 when steps, values or expected diagrams are missing.

Keys come from the relay config (.env). The model comes from --model or
GEMINI_MODEL_CONVERT in that config; no default model ID is guessed.
--force-hallucination rewrites 4 N-m to 5 N-m in every model step (not in its
quotes) before verification, to show the verifier catching it.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import subprocess
import sys
import time

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "relay" / "src"))

from specs_relay.convert.structure import GeminiConverter  # noqa: E402
from specs_relay.diagrams import render as R  # noqa: E402
from specs_relay.pipeline.verify import iter_number_tokens, normalize  # noqa: E402

CONVERTED_UNITS = ("in-lb", "ft-lb", "degf", "deg f", "psi", "inch", "kgf", "lbf")


def step_text(step: dict) -> str:
    return " ".join(step.get(k) or "" for k in ("glance", "body", "warning", "checkpoint"))


def diagram_text(step: dict) -> list[str]:
    d = step.get("diagram") or {}
    out = [d.get("alt") or ""]
    for el in d.get("elements") or []:
        label = el.get("label") or ""
        if el.get("type") == "callout" and label.strip().isdigit() and len(label.strip()) <= 2:
            continue  # sequence markers, as in verify_step
        out.append(label)
    return out


def fabricated(step: dict, material_tokens: set[str]) -> list[str]:
    seen, bad = set(), []
    for text in [step_text(step), *diagram_text(step)]:
        for tok, shown in iter_number_tokens(text):
            if tok not in material_tokens and tok not in seen and tok != f"{step.get('label')}|":
                seen.add(tok)
                bad.append(shown)
    return bad


def contains(text: str, value: str) -> bool:
    return f" {normalize(value)} " in f" {normalize(text)} "


def match_steps(expected: list[dict], steps: list[dict]) -> list[dict | None]:
    by_label = {s["label"]: s for s in steps}
    return [by_label.get(e["label"]) or (steps[i] if i < len(steps) else None) for i, e in enumerate(expected)]


class Hallucinating:
    """Wraps a structurer: 4 N-m -> 5 N-m in glance/body of every returned step."""

    def __init__(self, inner):
        self.inner = inner

    @property
    def calls(self):
        return self.inner.calls

    async def call(self, prompt, images):
        out = await self.inner.call(prompt, images)
        for s in out.get("steps") or []:
            for k in ("glance", "body"):
                if isinstance(s.get(k), str):
                    s[k] = s[k].replace("4 N-m", "5 N-m")
        return out


async def convert_one(conv: GeminiConverter, exp: dict, out_dir: Path) -> dict:
    """Real Gemini extract + convert; saves material_text.json and draft.json before scoring."""
    data = (ROOT / exp["material"]).read_bytes()
    t0 = time.perf_counter()
    reader_calls0, struct_calls0 = conv.reader.calls, conv.structurer.calls
    text = await conv.extract_dict(data, exp["mime"], exp["doc_id"])
    draft = await conv.convert_dict(text, exp["doc_id"], exp["revision"], exp["title"])
    mat_dir = out_dir / exp["doc_id"]
    mat_dir.mkdir(parents=True, exist_ok=True)
    (mat_dir / "material_text.json").write_text(json.dumps(text, indent=2, ensure_ascii=False), "utf-8")
    (mat_dir / "draft.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False, default=list), "utf-8")
    calls = {"extract": conv.reader.calls - reader_calls0, "structure": conv.structurer.calls - struct_calls0}
    return score(exp, text, draft, out_dir, round(time.perf_counter() - t0, 1), calls)


def load_saved(exp: dict, saved: Path) -> tuple[dict, dict]:
    mat_dir = saved / exp["doc_id"]
    text = json.loads((mat_dir / "material_text.json").read_text("utf-8"))
    draft = json.loads((mat_dir / "draft.json").read_text("utf-8"))
    for f in text["figures"]:
        f["bbox"] = tuple(f["bbox"])
    for s in draft["steps"]:
        if s.get("diagram") and s["diagram"].get("bbox") is not None:
            s["diagram"]["bbox"] = tuple(s["diagram"]["bbox"])
    return text, draft


def score(exp: dict, text: dict, draft: dict, out_dir: Path, seconds: float | None, calls: dict | None) -> dict:
    """No API calls: re-verify every step, render every diagram, compute the metrics."""
    from specs_relay.convert.verify_step import step_failures

    data = (ROOT / exp["material"]).read_bytes()
    for s in draft["steps"]:  # always re-verify with the current verifier
        reasons = step_failures(s, text)
        s["verify"] = {"ok": not reasons, "reason": "; ".join(reasons) or None, "citations": []}

    material ="\n".join(p["text"] for p in text["pages"]) + "\n" + "\n".join(f["caption"] for f in text["figures"])
    material_tokens = {tok for tok, _ in iter_number_tokens(material)}
    steps = draft["steps"]

    # Diagrams: render every step that has one, so the supervisor sees each preview.
    mat_dir = out_dir / exp["doc_id"]
    mat_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[str, dict] = {}
    figures = {f["figure_id"]: f for f in text["figures"]}
    for s in steps:
        d = s.get("diagram")
        if not d:
            continue
        try:
            page = None
            if d["kind"] == "crop":
                fig = figures.get(d.get("figure_id"))
                if fig is None or d.get("bbox") is None:
                    raise ValueError("crop has no valid figure/bbox")
                page = R.page_image(data, exp["mime"], fig["page"])
            tiles = R.render(d, page)
            png = R.preview_png(tiles)
            (mat_dir / f"step-{s['label']}.png").write_bytes(png)
            rendered[s["label"]] = {"kind": d["kind"], "tile_bytes": [len(t) for t in tiles],
                                    "wire_bytes": [R.tile_wire_bytes(t) for t in tiles], "format": R.TILE_FORMAT}
        except Exception as e:  # report, do not hide
            rendered[s["label"]] = {"kind": d.get("kind"), "error": f"{type(e).__name__}: {e}"}

    matched = match_steps(exp["steps"], steps)
    values = []
    for e, s in zip(exp["steps"], matched):
        for v in e["must_contain"]:
            values.append({"label": e["label"], "value": v, "ok": s is not None and contains(step_text(s), v)})
    diagrams = []
    for want in exp["diagrams"]:
        s = matched[want["step"] - 1] if want["step"] - 1 < len(matched) else None
        r = rendered.get(s["label"]) if s else None
        ok = bool(s and s.get("diagram") and s["diagram"]["kind"] == want["kind"] and s["verify"]["ok"]
                  and r and "error" not in r)
        diagrams.append({**want, "label": s["label"] if s else None, "ok": ok})
    fab = []
    for s in steps:
        bad = fabricated(s, material_tokens)
        if bad:
            fab.append({"label": s["label"], "passing": s["verify"]["ok"], "values": bad})
    out_text = " ".join(step_text(s) for s in steps).lower()
    converted = [u for u in CONVERTED_UNITS if u in out_text and u not in material.lower()]

    return {
        "doc_id": exp["doc_id"],
        "material": exp["material"],
        "seconds": seconds,
        "gemini_calls": calls,
        "pages": len(text["pages"]),
        "failed_pages": sum("failed to read" in p["text"] for p in text["pages"]),
        "figures": len(text["figures"]),
        "steps_expected": len(exp["steps"]),
        "steps_found": len(steps),
        "labels": [s["label"] for s in steps],
        "values_total": len(values),
        "values_preserved": sum(v["ok"] for v in values),
        "values_missing": [v for v in values if not v["ok"]],
        "failing_steps": [{"label": s["label"], "reason": s["verify"]["reason"]} for s in steps if not s["verify"]["ok"]],
        "diagrams_expected": len(diagrams),
        "diagrams_expected_ok": sum(d["ok"] for d in diagrams),
        "diagrams_detail": diagrams,
        "diagrams_rendered": rendered,
        "doc_warnings": draft["warnings"],
        "fabricated": fab,
        "fabricated_in_passing_steps": sum(len(f["values"]) for f in fab if f["passing"]),
        "converted_units": converted,
    }


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", help="Gemini model ID (default: GEMINI_MODEL_CONVERT from config)")
    ap.add_argument("--only", action="append", help="doc_id to run (repeatable)")
    ap.add_argument("--out", default=str(HERE / "results"), help="report + previews directory")
    ap.add_argument("--force-hallucination", action="store_true")
    ap.add_argument("--from-saved", metavar="DIR",
                    help="re-score real outputs saved by an earlier run (DIR/<doc_id>/*.json); no API calls")
    ap.add_argument("--model-label", help="with --from-saved: the model that produced the saved outputs")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    if args.force_hallucination:
        out_dir = out_dir / "forced-hallucination"
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = [json.loads(p.read_text("utf-8")) for p in sorted(HERE.glob("*.expected.json"))]
    expected = [e for e in expected if not args.only or e["doc_id"] in args.only]

    conv = None
    if args.from_saved:
        model = args.model_label or "saved outputs (model not recorded)"
    else:
        from specs_relay.config import get_settings
        from specs_relay.pipeline.generate import gemini_client

        settings = get_settings()
        model = args.model or getattr(settings, "gemini_model_convert", "")
        if not model:
            print("No model: pass --model or set GEMINI_MODEL_CONVERT (Part 3's config).", file=sys.stderr)
            return 1
        conv = GeminiConverter(gemini_client(settings.gemini_api_key), model)
        if args.force_hallucination:
            conv.structurer = Hallucinating(conv.structurer)

    report = {"date": dt.date.today().isoformat(), "model": model, "commit": git_commit(),
              "source": f"saved: {args.from_saved}" if args.from_saved else "live Gemini",
              "forced_hallucination": args.force_hallucination, "results": []}
    results = report["results"]
    for exp in expected:
        print(f"{'scoring' if args.from_saved else 'converting'} {exp['doc_id']} ({exp['material']}) ...", flush=True)
        try:
            if args.from_saved:
                text, draft = load_saved(exp, Path(args.from_saved))
                if args.force_hallucination:
                    for s in draft["steps"]:
                        for k in ("glance", "body"):
                            s[k] = (s.get(k) or "").replace("4 N-m", "5 N-m")
                results.append(score(exp, text, draft, out_dir, None, None))
            else:
                results.append(await convert_one(conv, exp, out_dir))
        except Exception as e:  # record it and keep going; an error is never a pass
            results.append({"doc_id": exp["doc_id"], "material": exp["material"],
                            "error": f"{type(e).__name__}: {e}"[:300]})
        (out_dir / "report.json").write_text(json.dumps(report, indent=2), "utf-8")

    print()
    for r in [r for r in results if "error" in r]:
        print(f"{r['doc_id']:9} ERROR {r['error']}")
    results = [r for r in results if "error" not in r]
    print(f"{'material':9} {'steps':>7} {'values':>8} {'failing':>8} {'diagrams':>9} {'fabricated':>11} {'calls':>6} {'sec':>6}")
    for r in results:
        print(f"{r['doc_id']:9} {r['steps_found']:>3}/{r['steps_expected']:<3} "
              f"{r['values_preserved']:>3}/{r['values_total']:<4} {len(r['failing_steps']):>8} "
              f"{r['diagrams_expected_ok']:>4}/{r['diagrams_expected']:<4} "
              f"{r['fabricated_in_passing_steps']:>5} pass/{sum(len(f['values']) for f in r['fabricated']):<3} "
              f"{sum((r['gemini_calls'] or {}).values()) if r['gemini_calls'] else '-':>6} "
              f"{r['seconds'] if r['seconds'] is not None else '-':>6}")
        for f in r["failing_steps"]:
            print(f"    step {f['label']} FAILS: {f['reason']}")
        for v in r["values_missing"]:
            print(f"    step {v['label']} missing value: {v['value']}")
        for d in r["diagrams_detail"]:
            if not d["ok"]:
                print(f"    expected {d['kind']} diagram on step {d['step']} not produced")
        for label, info in r["diagrams_rendered"].items():
            if "error" in info:
                print(f"    step {label} diagram error: {info['error']}")
        if r["converted_units"]:
            print(f"    CONVERTED UNITS in output: {r['converted_units']}")
    gate = sum(r["fabricated_in_passing_steps"] for r in results)
    print(f"\nfabricated values in passing steps: {gate}  (gate: must be 0)")

    print(f"report: {out_dir / 'report.json'}")

    if gate:
        return 1
    errored = len(report["results"]) != len(results)
    incomplete = errored or any(r["steps_found"] != r["steps_expected"] or r["values_preserved"] != r["values_total"]
                     or r["diagrams_expected_ok"] != r["diagrams_expected"] for r in results)
    return 2 if args.strict and incomplete else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
