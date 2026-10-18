"""Diagram renderer: golden images (exact pixel match), tile format, levels, budget.

Regenerate the goldens deliberately, after looking at them:
    MARGIN_UPDATE_GOLDEN=1 pytest relay/tests/test_render.py
"""

import io
import json
import os
import zlib
from pathlib import Path

import pytest
from PIL import Image

from margin_relay.diagrams import render as R

FIX = Path(__file__).parent / "fixtures" / "diagrams"
REPO = Path(__file__).resolve().parents[2]
SEAL_FIGURE = REPO / "corpus" / "materials" / "figures" / "SOP-150-figure-1.png"
MATERIALS = REPO / "corpus" / "materials"
UPDATE = os.environ.get("MARGIN_UPDATE_GOLDEN") == "1"


def spec(name):
    return json.loads((FIX / f"{name}.spec.json").read_text("utf-8"))


def preview_image(tiles):
    return Image.open(io.BytesIO(R.preview_png(tiles)))


def golden(name, tiles):
    path = FIX / f"{name}.golden.png"
    got = preview_image(tiles)
    if UPDATE:
        got.save(path)
    want = Image.open(path).convert("RGB")
    assert got.size == want.size == (576, 144)
    assert got.tobytes() == want.tobytes(), f"{name} differs from its golden; regenerate deliberately"


@pytest.fixture(scope="module")
def crop_tiles():
    return R.render(spec("crop-sop150-nut-order"), SEAL_FIGURE.read_bytes())


@pytest.fixture(scope="module")
def schematic_tiles():
    return R.render(spec("schematic-sop153-star"), None)


def test_golden_crop(crop_tiles):
    golden("crop-sop150-nut-order", crop_tiles)


def test_golden_schematic(schematic_tiles):
    golden("schematic-sop153-star", schematic_tiles)


@pytest.mark.parametrize("which", ["crop_tiles", "schematic_tiles"])
def test_two_tiles_of_16_levels_in_gray8(which, request):
    tiles = request.getfixturevalue(which)
    assert R.TILE_FORMAT == "gray8"
    assert len(tiles) == 2
    for t in tiles:
        assert len(t) == 288 * 144
        assert set(t) <= {i * 17 for i in range(16)}


def test_light_paper_is_inverted(crop_tiles):
    # White paper must not glow: most of the lens stays dark.
    pixels = b"".join(crop_tiles)
    assert sum(1 for v in pixels if v == 0) / len(pixels) > 0.7


def test_dark_source_is_not_inverted():
    dark = Image.new("L", (400, 200), 10)
    dark.paste(240, (150, 50, 250, 150))  # a lit square on a dark background
    buf = io.BytesIO()
    dark.save(buf, "PNG")
    tiles = R.render({"kind": "crop", "bbox": (0, 0, 1, 1)}, buf.getvalue())
    canvas = Image.new("L", (576, 144))
    for slot, t in enumerate(tiles):
        canvas.paste(R.decode_tile(t), (slot * 288, 0))
    assert canvas.getpixel((288, 72)) == 255   # the square stays lit
    assert canvas.getpixel((200, 10)) == 0       # the background stays dark


def test_schematic_tiles_fit_the_budget(schematic_tiles):
    for t in schematic_tiles:
        assert len(zlib.compress(t, 1)) < R.TILE_BUDGET


def test_label_font_has_14px_caps():
    f = R.label_font()
    top, bottom = f.getbbox("H")[1], f.getbbox("H")[3]
    assert bottom - top >= 14


def test_preview_is_lens_green_on_black(schematic_tiles):
    im = preview_image(schematic_tiles)
    assert im.mode == "RGB" and im.size == (576, 144)
    raw = im.tobytes()
    colours = {tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)}
    assert (0, 0, 0) in colours and R.LENS_GREEN in colours
    assert all(r <= g and b <= g for r, g, b in colours)


def test_dither_is_exact_on_flat_levels():
    flat = Image.new("L", (32, 8), 17 * 9)
    assert set(R.dither(flat).tobytes()) == {153}


@pytest.mark.parametrize("fmt", ["gray8", "gray4", "png"])
def test_tile_formats_round_trip(fmt, monkeypatch, schematic_tiles):
    monkeypatch.setattr(R, "TILE_FORMAT", "gray8")
    tile = R.decode_tile(schematic_tiles[0])
    monkeypatch.setattr(R, "TILE_FORMAT", fmt)
    data = R.encode_tile(tile)
    assert R.decode_tile(data).tobytes() == tile.tobytes()
    if fmt == "gray4":
        assert len(data) == 288 * 144 // 2
        left, right = tile.getpixel((0, 0)) // 17, tile.getpixel((1, 0)) // 17
        assert data[0] == left << 4 | right


def test_crop_without_page_image_is_an_error():
    with pytest.raises(ValueError):
        R.render({"kind": "crop", "bbox": (0, 0, 1, 1)}, None)


def test_schematic_clamps_off_canvas_coordinates():
    tiles = R.render({"kind": "schematic", "elements": [
        {"type": "line", "x": -50, "y": -50, "x2": 9000, "y2": 9000}]}, None)
    assert len(tiles) == 2


# --- page images ------------------------------------------------------------------------

def test_page_image_pdf():
    png = R.page_image((MATERIALS / "SOP-150-pump-seal-swap.pdf").read_bytes(), "application/pdf", 2)
    im = Image.open(io.BytesIO(png))
    assert im.mode == "L" and im.width == 1275 and abs(im.height - 1650) <= 1  # Letter at 150 dpi
    with pytest.raises(ValueError):
        R.page_image((MATERIALS / "SOP-150-pump-seal-swap.pdf").read_bytes(), "application/pdf", 3)


def test_page_image_photo_and_docx():
    jpg = R.page_image((MATERIALS / "SOP-152-valve-lineup-photo.jpg").read_bytes(), "image/jpeg", 1)
    assert Image.open(io.BytesIO(jpg)).mode == "L"
    docx = R.page_image((MATERIALS / "SOP-151-filter-change.docx").read_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 1)
    assert Image.open(io.BytesIO(docx)).size == (640, 400)
