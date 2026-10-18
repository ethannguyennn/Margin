"""DiagramSpec -> lens tiles, a lens-exact preview PNG, and page images for crops.

The lens diagram canvas is 576 x 144 (BUILD-PLAN-V2 section 4), sent as two
288 x 144 image containers side by side. Lit pixels glow green, black is
transparent, 16 grey levels.

- crop: page image -> crop to bbox -> greyscale -> autocontrast -> invert a
  light background (white paper would make the whole tile glow) -> fit inside
  576 x 144 keeping aspect -> Floyd-Steinberg to 16 levels.
- schematic: elements drawn at level 15 with 2 px strokes on black, labels in
  the bundled OFL font at >= 14 px cap height, snapped to 16 levels (no
  dither, so line art stays crisp and compresses well).

Pure functions. The tile byte format is the day-one unknown that Part 2
proves in the simulator; every tile goes through ``encode_tile`` /
``decode_tile`` and ``TILE_FORMAT`` is the one line to change.
"""

from __future__ import annotations

import io
import logging
import math
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

log = logging.getLogger("margin.diagrams")

CANVAS_W, CANVAS_H = 576, 144
TILE_W, TILE_H = 288, 144
LEVELS = 16
STEP = 255 // (LEVELS - 1)  # 17: grey value of one level
STROKE = 2
MIN_CAP_PX = 14
CALLOUT_R = 15
TILE_BUDGET = 8 * 1024
LENS_GREEN = (0x3C, 0xFA, 0x44)  # preview colour of level 15

# "gray8": raw 8-bit grey, row-major, 41,472 bytes per tile (values 0, 17, ..., 255).
# "gray4": raw packed 4-bit, two pixels per byte, left pixel in the high nibble.
# "png":   PNG file bytes of the 8-bit grey tile.
# Part 2 announces which one updateImageRawData accepts; switch here only.
TILE_FORMAT = "gray8"

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "AtkinsonHyperlegible-Bold.ttf"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


@lru_cache(maxsize=1)
def label_font() -> ImageFont.FreeTypeFont:
    """The smallest size of the bundled font whose capital H is >= 14 px tall."""
    for size in range(12, 40):
        f = ImageFont.truetype(str(FONT_PATH), size)
        top, bottom = f.getbbox("H")[1], f.getbbox("H")[3]
        if bottom - top >= MIN_CAP_PX:
            return f
    raise RuntimeError("bundled font never reaches the minimum cap height")


# --- pixel helpers ------------------------------------------------------------------

def snap(img: Image.Image) -> Image.Image:
    """Nearest of the 16 levels, no dither."""
    return img.point(lambda v: min(255, (v + STEP // 2) // STEP * STEP))


def dither(img: Image.Image) -> Image.Image:
    """Floyd-Steinberg to 16 levels in integer arithmetic (deterministic on every Pillow)."""
    w, h = img.size
    px = img.tobytes()
    err = [0] * (w + 2)  # error carried into the current row (index shifted by 1)
    nxt = [0] * (w + 2)
    out = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            v = px[row + x] + err[x + 1] // 16
            q = min(255, max(0, (v + STEP // 2) // STEP * STEP))
            out[row + x] = q
            e = v - q
            err[x + 2] += e * 7
            nxt[x] += e * 3
            nxt[x + 1] += e * 5
            nxt[x + 2] += e
        err, nxt = nxt, [0] * (w + 2)
    return Image.frombytes("L", (w, h), bytes(out))


def fit(img: Image.Image) -> Image.Image:
    """Scale (up or down) to fit 576 x 144 keeping aspect, centred on black."""
    scale = min(CANVAS_W / img.width, CANVAS_H / img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    canvas = Image.new("L", (CANVAS_W, CANVAS_H), 0)
    canvas.paste(img.resize(size, Image.LANCZOS), ((CANVAS_W - size[0]) // 2, (CANVAS_H - size[1]) // 2))
    return canvas


# --- tile format ------------------------------------------------------------------------

def encode_tile(tile: Image.Image) -> bytes:
    if tile.size != (TILE_W, TILE_H) or tile.mode != "L":
        raise ValueError("tiles are 288 x 144 greyscale")
    if TILE_FORMAT == "gray8":
        return tile.tobytes()
    if TILE_FORMAT == "gray4":
        raw = tile.tobytes()
        return bytes((raw[i] // STEP) << 4 | (raw[i + 1] // STEP) for i in range(0, len(raw), 2))
    if TILE_FORMAT == "png":
        buf = io.BytesIO()
        tile.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    raise ValueError(f"unknown TILE_FORMAT {TILE_FORMAT}")


def decode_tile(data: bytes) -> Image.Image:
    if TILE_FORMAT == "gray8":
        return Image.frombytes("L", (TILE_W, TILE_H), data)
    if TILE_FORMAT == "gray4":
        raw = bytearray()
        for b in data:
            raw += bytes(((b >> 4) * STEP, (b & 0x0F) * STEP))
        return Image.frombytes("L", (TILE_W, TILE_H), bytes(raw))
    if TILE_FORMAT == "png":
        return Image.open(io.BytesIO(data)).convert("L")
    raise ValueError(f"unknown TILE_FORMAT {TILE_FORMAT}")


def split_tiles(canvas: Image.Image) -> list[bytes]:
    tiles = []
    for slot in range(2):
        tile = canvas.crop((slot * TILE_W, 0, (slot + 1) * TILE_W, TILE_H))
        data = encode_tile(tile)
        packed = len(zlib.compress(data, 1))
        log.info("diagram tile %d: %d bytes %s, %d bytes deflated (LZ4 proxy)", slot, len(data), TILE_FORMAT, packed)
        if packed > TILE_BUDGET:
            log.warning("diagram tile %d is %d bytes deflated, over the %d byte budget", slot, packed, TILE_BUDGET)
        tiles.append(data)
    return tiles


# --- crop -------------------------------------------------------------------------------

def render_crop(page: Image.Image, bbox: Any) -> Image.Image:
    x0, y0, x1, y1 = (float(v) for v in bbox)
    w, h = page.size
    box = (math.floor(x0 * w), math.floor(y0 * h), math.ceil(x1 * w), math.ceil(y1 * h))
    img = ImageOps.autocontrast(page.convert("L").crop(box), cutoff=1)
    if sum(img.tobytes()) / (img.width * img.height) > 127.5:  # light paper -> invert
        img = ImageOps.invert(img)
    return dither(fit(img))


# --- schematic --------------------------------------------------------------------------

def _clamp(x: Any, hi: int) -> int:
    return max(0, min(hi, int(x)))


def render_schematic(elements: list[Any]) -> Image.Image:
    canvas = Image.new("L", (CANVAS_W, CANVAS_H), 0)
    d = ImageDraw.Draw(canvas)
    f = label_font()
    for el in elements:
        kind = _get(el, "type")
        x, y = _clamp(_get(el, "x", 0), CANVAS_W - 1), _clamp(_get(el, "y", 0), CANVAS_H - 1)
        x2 = _clamp(_get(el, "x2") if _get(el, "x2") is not None else x, CANVAS_W - 1)
        y2 = _clamp(_get(el, "y2") if _get(el, "y2") is not None else y, CANVAS_H - 1)
        label = _get(el, "label") or ""
        if kind in ("line", "arrow"):
            d.line((x, y, x2, y2), fill=255, width=STROKE)
            if kind == "arrow" and (x2, y2) != (x, y):
                a = math.atan2(y2 - y, x2 - x)
                for side in (-1, 1):
                    t = a + math.pi - side * math.radians(28)
                    d.line((x2, y2, round(x2 + 11 * math.cos(t)), round(y2 + 11 * math.sin(t))), fill=255, width=STROKE)
        elif kind == "rect":
            d.rectangle((min(x, x2), min(y, y2), max(x, x2), max(y, y2)), outline=255, width=STROKE)
        elif kind == "circle":
            r = int(_get(el, "r") or CALLOUT_R)
            d.ellipse((x - r, y - r, x + r, y + r), outline=255, width=STROKE)
        elif kind == "callout":
            r = max(CALLOUT_R, int(_get(el, "r") or CALLOUT_R))
            d.ellipse((x - r, y - r, x + r, y + r), outline=255, width=STROKE)
            if label:
                d.text((x, y), label, font=f, fill=255, anchor="mm")
            continue
        if label and kind in ("text", "rect", "circle", "line", "arrow"):
            d.text((x, y) if kind == "text" else (x2 + 4, y2), label, font=f, fill=255,
                   anchor="lt" if kind == "text" else "lm")
    return snap(canvas)


# --- the DiagramRenderer Protocol --------------------------------------------------------

class DiagramRenderer:
    def render(self, spec: Any, page_image: bytes | None) -> list[bytes]:
        """1-2 tiles in ``TILE_FORMAT`` (always 2 today: slot 0 left, slot 1 right)."""
        kind = _get(spec, "kind")
        if kind == "crop":
            if page_image is None:
                raise ValueError("a crop diagram needs the page image")
            canvas = render_crop(Image.open(io.BytesIO(page_image)), _get(spec, "bbox"))
        elif kind == "schematic":
            canvas = render_schematic(list(_get(spec, "elements") or []))
        else:
            raise ValueError(f"unknown diagram kind {kind!r}")
        return split_tiles(canvas)

    def preview_png(self, tiles: list[bytes]) -> bytes:
        """576 x 144 PNG coloured like the lens: level 15 is G2 green, 0 is black."""
        grey = Image.new("L", (CANVAS_W, CANVAS_H), 0)
        for slot, data in enumerate(tiles[:2]):
            grey.paste(decode_tile(data), (slot * TILE_W, 0))
        r, g, b = (grey.point(lambda v, c=c: round(v * c / 255)) for c in LENS_GREEN)
        buf = io.BytesIO()
        Image.merge("RGB", (r, g, b)).save(buf, "PNG")
        return buf.getvalue()

    def page_image(self, data: bytes, mime: str, page: int) -> bytes:
        """PNG (greyscale) of one page, for crops. ``page`` is 1-based.

        PDF: the page rendered at 150 dpi. PNG/JPEG: the photo itself (page 1).
        DOCX: the ``page``-th embedded image in document order (DOCX has no
        pages; extract.py numbers DOCX figures the same way).
        """
        mime = (mime or "").split(";")[0].strip().lower()
        if mime == "application/pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            try:
                if not 1 <= page <= len(pdf):
                    raise ValueError(f"page {page} is not in this PDF")
                img = pdf[page - 1].render(scale=150 / 72).to_pil()
            finally:
                pdf.close()
        elif mime in ("image/png", "image/jpeg"):
            if page != 1:
                raise ValueError("an image material has one page")
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            from ..convert.extract import docx_images

            images = docx_images(data)
            if not 1 <= page <= len(images):
                raise ValueError(f"image {page} is not in this DOCX")
            img = Image.open(io.BytesIO(images[page - 1]))
        else:
            raise ValueError(f"no page images for {mime}")
        buf = io.BytesIO()
        img.convert("L").save(buf, "PNG")
        return buf.getvalue()


_renderer = DiagramRenderer()
render = _renderer.render
preview_png = _renderer.preview_png
page_image = _renderer.page_image
