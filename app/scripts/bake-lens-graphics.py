"""Bake the lens copy of every corpus/illustrations.json view into src/assets/lens/<id>.png.

The glasses host decodes *encoded* image bytes (PNG/JPEG) itself; raw pixel buffers only
work in the simulator. So the 288x144 lens images are pre-rendered here, at build time,
and the app inlines the PNG bytes: no canvas, no fetch, no decode on the phone.

Each catalog crop holds one whole view with a margin. The source art packs several views
side by side, so a crop edge cut *inside* the art can still catch a sliver of the
neighbouring view (half a label, the edge of another object). Those slivers are removed:
small pieces of linework touching an interior crop edge. Edges that are the art's own
border are left alone, and so is anything large (a counter running under the view).
Where neighbouring art overlaps a view's box (a label above one object, a part of the next
beside it), the catalog lists those regions under "erase" ([x, y, w, h] fractions of the
source art); they are blanked before cropping. The phone shows the plain crop.

Re-run after changing the art or the catalog:  python app/scripts/bake-lens-graphics.py
(needs Pillow)
"""
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

APP = Path(__file__).resolve().parents[1]
W, H = 288, 144
LIT = 64             # threshold: drop low-level texture so the monochrome lens shows crisp linework
SLIVER_SHARE = 0.06  # a piece under 6 % of the view's lit pixels, touching an interior edge, is a sliver
EPS = 1e-6
WORD_GAP = 5          # pieces closer than this many pixels are judged together (the letters of a label)


def pieces(img: Image.Image) -> list[list[tuple[int, int]]]:
    """Groups of lit pixels, joining pieces closer than WORD_GAP so a cut label counts as one."""
    w, h = img.size
    lit = img.load()
    px = img.filter(ImageFilter.MaxFilter(WORD_GAP)).load()  # grouping only; pixels come from `lit`
    seen = [[False] * w for _ in range(h)]
    out = []
    for y in range(h):
        for x in range(w):
            if seen[y][x] or not px[x, y]:
                continue
            group, queue = [], deque([(x, y)])
            seen[y][x] = True
            while queue:
                cx, cy = queue.popleft()
                group.append((cx, cy))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and px[nx, ny]:
                            seen[ny][nx] = True
                            queue.append((nx, ny))
            out.append([p for p in group if lit[p]])
    return out


def drop_slivers(img: Image.Image, crop: list[float]) -> tuple[Image.Image, int]:
    """Remove small pieces touching a crop edge that lies inside the source art."""
    x, y, w, h = crop
    interior = {"left": x > EPS, "top": y > EPS, "right": x + w < 1 - EPS, "bottom": y + h < 1 - EPS}
    groups = pieces(img)
    total = sum(len(g) for g in groups) or 1
    px = img.load()
    dropped = 0
    for g in groups:
        if len(g) >= SLIVER_SHARE * total:
            continue
        xs, ys = [p[0] for p in g], [p[1] for p in g]
        touches = ((interior["left"] and min(xs) == 0) or (interior["top"] and min(ys) == 0)
                   or (interior["right"] and max(xs) == img.width - 1)
                   or (interior["bottom"] and max(ys) == img.height - 1))
        if touches:
            for p in g:
                px[p] = 0
            dropped += 1
    return img, dropped


def bake(g: dict) -> tuple[Image.Image, int]:
    if g.get("lens"):  # corpus figures ship their own 288x144 4-bit lens render
        return Image.open(APP.parent / "corpus/figures/g2" / g["lens"]), 0
    art = Image.open(APP / "src/assets/sops" / g["file"]).convert("RGB")
    for ex, ey, ew, eh in g.get("erase", []):
        ImageDraw.Draw(art).rectangle((ex * art.width, ey * art.height, (ex + ew) * art.width,
                                       (ey + eh) * art.height), fill=(0, 0, 0))
    x, y, w, h = g["crop"]
    sw, sh = art.width * w, art.height * h
    view = art.crop((round(x * art.width), round(y * art.height), round(x * art.width + sw), round(y * art.height + sh)))
    scale = min(W / sw, H / sh)
    view = view.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.LANCZOS)
    # Rec. 709 luma, then a hard threshold to the lens's lit/unlit linework.
    grey = view.convert("L", (0.2126, 0.7152, 0.0722, 0)).point(lambda v: 255 if v >= LIT else 0)
    grey, dropped = drop_slivers(grey, g["crop"])
    lens = Image.new("L", (W, H), 0)
    lens.paste(grey, ((W - grey.width) // 2, (H - grey.height) // 2))
    return lens, dropped


if __name__ == "__main__":
    for g in json.loads((APP.parent / "corpus/illustrations.json").read_text(encoding="utf-8")):
        lens, dropped = bake(g)
        out = APP / "src/assets/lens" / f"{g['id']}.png"
        out.parent.mkdir(exist_ok=True)
        lens.save(out, optimize=True)
        print(out.relative_to(APP), out.stat().st_size, "bytes,", dropped, "edge slivers removed")
