import os, sys, importlib, math
sys.path.insert(0, os.path.dirname(__file__))
import cairosvg
from PIL import Image, ImageDraw
import lib

OUT = os.path.join(os.path.dirname(__file__), "..", "figures")
for d in ("svg", "png", "g2"):
    os.makedirs(os.path.join(OUT, d), exist_ok=True)

mods = sys.argv[1:] or ["figs_a", "figs_b", "figs_c", "figs_d"]
for m in mods:
    if os.path.exists(os.path.join(os.path.dirname(__file__), m + ".py")):
        importlib.import_module(m)

ids = sorted(lib.FIGS)
for fid in ids:
    title, fn = lib.FIGS[fid]
    f = lib.Fig(fid, title)
    fn(f)
    svg = f.svg()
    open(f"{OUT}/svg/{fid}.svg", "w").write(svg)
    png = f"{OUT}/png/{fid}.png"
    cairosvg.svg2png(bytestring=svg.encode(), write_to=png, output_width=576, output_height=288)
    im = Image.open(png).convert("L")
    g2 = im.resize((288, 144), Image.LANCZOS)
    g2 = Image.eval(g2, lambda p: 255 - p)                 # glasses show light-on-dark
    g2 = Image.eval(g2, lambda p: (p // 16) * 17)          # 4-bit greyscale
    g2.save(f"{OUT}/g2/{fid}.png")
print(len(ids), "figures")

# contact sheets
cols, rows_per = 3, 4
tw, th = 384, 192
per = cols * rows_per
for s in range(0, len(ids), per):
    chunk = ids[s:s + per]
    sheet = Image.new("L", (cols * tw, math.ceil(len(chunk) / cols) * (th + 18)), 255)
    d = ImageDraw.Draw(sheet)
    for i, fid in enumerate(chunk):
        im = Image.open(f"{OUT}/png/{fid}.png").convert("L").resize((tw - 8, th - 4))
        x, y = (i % cols) * tw + 4, (i // cols) * (th + 18)
        sheet.paste(im, (x, y + 16))
        d.rectangle([x - 1, y + 15, x + tw - 8, y + th + 12], outline=0)
        d.text((x, y + 2), fid, fill=0)
    sheet.save(os.path.join(os.path.dirname(__file__), f"sheet_{s // per + 1}.png"))
