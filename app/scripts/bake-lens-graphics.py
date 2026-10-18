"""Bake the lens copy of every corpus/illustrations.json view into src/assets/lens/<id>.png.

The glasses host decodes *encoded* image bytes (PNG/JPEG) itself; raw pixel buffers only
work in the simulator. So the 288x144 lens images are pre-rendered here, at build time,
and the app inlines the PNG bytes: no canvas, no fetch, no decode on the phone.
Same crop, fit and threshold the app used to do at runtime. Re-run after changing the art
or the catalog:  python app/scripts/bake-lens-graphics.py   (needs Pillow)
"""
import json
from pathlib import Path

from PIL import Image

APP = Path(__file__).resolve().parents[1]
W, H = 288, 144

for g in json.loads((APP.parent / "corpus/illustrations.json").read_text(encoding="utf-8")):
    art = Image.open(APP / "src/assets/sops" / g["file"]).convert("RGB")
    x, y, w, h = g["crop"]
    sw, sh = art.width * w, art.height * h
    view = art.crop((round(x * art.width), round(y * art.height), round(x * art.width + sw), round(y * art.height + sh)))
    scale = min(W / sw, H / sh)
    view = view.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.LANCZOS)
    # Rec. 709 luma; drop low-level texture so the monochrome lens shows crisp linework.
    grey = view.convert("L", (0.2126, 0.7152, 0.0722, 0)).point(lambda v: 255 if v >= 64 else 0)
    lens = Image.new("L", (W, H), 0)
    lens.paste(grey, ((W - grey.width) // 2, (H - grey.height) // 2))
    out = APP / "src/assets/lens" / f"{g['id']}.png"
    out.parent.mkdir(exist_ok=True)
    lens.save(out, optimize=True)
    print(out.relative_to(APP), out.stat().st_size, "bytes")
