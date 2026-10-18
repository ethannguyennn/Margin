"""Extraction. Markdown, DOCX and the PDF text layer run for real on the
committed synthetic materials; Gemini paths use a fake reader/client (wiring
only; real Gemini output is exercised by eval/conversion)."""

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from specs_relay.convert import extract as X

MAT = Path(__file__).resolve().parents[2] / "corpus" / "materials"
PDF = (MAT / "SOP-150-pump-seal-swap.pdf").read_bytes()
DOCX = (MAT / "SOP-151-filter-change.docx").read_bytes()
JPG = (MAT / "SOP-152-valve-lineup-photo.jpg").read_bytes()
MD = (MAT / "SOP-153-quick-start.md").read_bytes()


def run(data, mime, reader=None):
    return asyncio.run(X.extract_dict(data, mime, "mat-1", reader))


class FakeReader:
    def __init__(self, text="1. Close suction valve V1.", figures=(), fail=False):
        self.text, self.figs, self.fail = text, list(figures), fail
        self.transcribed, self.figured = [], []

    async def transcribe(self, image, mime):
        self.transcribed.append(mime)
        if self.fail:
            raise TimeoutError
        return {"text": self.text, "figures": self.figs}

    async def figures(self, image, mime):
        self.figured.append(mime)
        if self.fail:
            raise TimeoutError
        return {"figures": self.figs}


# --- markdown / text -------------------------------------------------------------------

def test_markdown_is_verbatim():
    out = run(MD, "text/markdown")
    assert out["pages"] == [{"page": 1, "text": MD.decode("utf-8")}]
    assert out["figures"] == []


def test_non_utf8_text_is_rejected():
    with pytest.raises(X.ExtractionError):
        run(b"\xff\xfe\x00bad", "text/plain")


# --- DOCX ------------------------------------------------------------------------------

def test_docx_paragraphs_tables_and_figure():
    out = run(DOCX, X.MIME_DOCX)
    text = out["pages"][0]["text"]
    assert "# SOP-151 Filter Element Change" in text
    assert "WARNING: Relieve line pressure before opening the filter bowl." in text
    assert "| Bowl clamp screw | M5 | 3 N-m |" in text
    assert "| Drain plug | M10 | 8 N-m |" in text
    assert "4. Replace the filter element with a new element HX2-420 (25 µm rating)." in text
    assert text.index("Torque values") < text.index("| Fastener") < text.index("4 Procedure")
    assert out["figures"] == [{"page": 1, "bbox": (0.0, 0.0, 1.0, 1.0),
                               "caption": "Figure 1. Filter bowl, element and clamp screws.", "figure_id": "F1"}]


def test_docx_images_in_document_order():
    images = X.docx_images(DOCX)
    assert len(images) == 1
    assert Image.open(io.BytesIO(images[0])).size == (640, 400)


# --- PDF ------------------------------------------------------------------------------

def test_pdf_text_layer_is_verbatim_per_page():
    out = run(PDF, "application/pdf")
    p1, p2 = (p["text"] for p in out["pages"])
    assert "WARNING: Isolate power and drain the pump before opening the seal housing." in p1
    assert "3.1 Remove the four M6 gland nuts with the 10 mm socket." in p1
    assert p2.startswith("3.4 Refit the gland plate and torque the four M6 gland nuts to 4 N-m")
    assert "1200 rpm" in p2


def test_pdf_figures_come_from_gemini_only_on_pages_with_images():
    reader = FakeReader(figures=[{"box_2d": [300, 60, 700, 940], "caption": "Figure 1. Seal housing."}])
    out = run(PDF, "application/pdf", reader)
    assert reader.figured == ["image/png"]     # page 1 has the figure; page 2 is text only
    assert reader.transcribed == []            # the text layer is never re-transcribed
    assert out["figures"] == [{"page": 1, "bbox": (0.06, 0.3, 0.94, 0.7),
                               "caption": "Figure 1. Seal housing.", "figure_id": "F1"}]
    assert "3.1 Remove the four M6 gland nuts" in out["pages"][0]["text"]


def test_pdf_figure_call_failure_keeps_the_text_layer():
    out = run(PDF, "application/pdf", FakeReader(fail=True))
    assert "3.1 Remove the four M6" in out["pages"][0]["text"]
    assert out["figures"] == []


def scanned_pdf():
    page = Image.new("L", (850, 1100), 255)
    buf = io.BytesIO()
    page.save(buf, "PDF", resolution=100)
    return buf.getvalue()


def test_scanned_pdf_page_is_transcribed():
    reader = FakeReader(text="1. Close suction valve V1.")
    out = run(scanned_pdf(), "application/pdf", reader)
    assert reader.transcribed == ["image/png"]
    assert out["pages"] == [{"page": 1, "text": "1. Close suction valve V1."}]


def test_scanned_page_without_a_reader_is_a_failed_page():
    assert run(scanned_pdf(), "application/pdf")["pages"] == [{"page": 1, "text": "[page 1 failed to read]"}]


# --- photos -----------------------------------------------------------------------------

def test_photo_goes_through_transcription():
    reader = FakeReader(text="1. Close suction valve V1 (handle across the pipe).",
                        figures=[{"box_2d": [500, 100, 800, 900], "caption": "Figure 1. Valve handle positions."}])
    out = run(JPG, "image/jpeg", reader)
    assert reader.transcribed == ["image/jpeg"]
    assert out["pages"][0]["text"].startswith("1. Close suction valve V1")
    assert out["figures"][0]["bbox"] == (0.1, 0.5, 0.9, 0.8)


def test_photo_timeout_is_a_failed_page_never_a_guess():
    out = run(JPG, "image/jpeg", FakeReader(fail=True))
    assert out["pages"] == [{"page": 1, "text": "[page 1 failed to read]"}]
    assert out["figures"] == []


def test_unsupported_type():
    with pytest.raises(X.ExtractionError):
        run(b"GIF89a", "image/gif")


@pytest.mark.parametrize("box, want", [
    ([0, 0, 1000, 1000], (0.0, 0.0, 1.0, 1.0)),
    ([250, 100, 750, 400], (0.1, 0.25, 0.4, 0.75)),
    ([-5, 0, 1200, 500], (0.0, 0.0, 0.5, 1.0)),
    ([500, 500, 400, 600], None),
    (["a", 1, 2, 3], None),
    ([1, 2, 3], None),
])
def test_box_from_2d(box, want):
    assert X.box_from_2d(box) == want


# --- GeminiReader request shape (fake client) --------------------------------------------

class FakeModels:
    def __init__(self, payload, delay=0.0):
        self.payload, self.delay, self.requests = payload, delay, []

    async def generate_content(self, *, model, contents, config):
        self.requests.append(NS(model=model, contents=contents, config=config))
        await asyncio.sleep(self.delay)
        return NS(text=json.dumps(self.payload))


def test_reader_requests_verbatim_structured_output():
    models = FakeModels({"text": "x", "figures": []})
    reader = X.GeminiReader(NS(aio=NS(models=models)), "model-from-config")
    asyncio.run(reader.transcribe(b"\x89PNG", "image/png"))
    req = models.requests[0]
    part, prompt = req.contents
    assert req.model == "model-from-config"
    assert part.inline_data.mime_type == "image/png"
    assert "verbatim" in prompt and "[illegible]" in prompt and "Never guess" in prompt
    assert "[ymin, xmin, ymax, xmax] normalized to 0-1000" in prompt
    assert req.config.temperature == 0.0
    assert req.config.response_json_schema == X.PAGE_SCHEMA


def test_reader_hard_timeout():
    reader = X.GeminiReader(NS(aio=NS(models=FakeModels({}, delay=0.5))), "m", timeout=0.01)
    out = asyncio.run(X.extract_dict(JPG, "image/jpeg", "m1", reader))
    assert out["pages"][0]["text"] == "[page 1 failed to read]"


def test_reader_needs_a_model():
    with pytest.raises(ValueError):
        X.GeminiReader(NS(), "")
