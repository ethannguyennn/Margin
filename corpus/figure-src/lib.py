"""Tiny black-and-white SVG diagram library (576x288 canvas = G2 lens size)."""
import html

W, H = 576, 288
FONT = "DejaVu Sans, Verdana, sans-serif"
FIGS = {}  # id -> (title, builder)


def fig(fid, title):
    def deco(fn):
        FIGS[fid] = (title, fn)
        return fn
    return deco


class Fig:
    def __init__(self, fid, title):
        self.fid, self.title, self.el = fid, title, []
        if title:
            self.text(20, 24, title, size=18, anchor="start", bold=True)

    def add(self, s):
        self.el.append(s)

    # ---------- primitives ----------
    def text(self, x, y, t, size=15, anchor="middle", bold=False, italic=False):
        lines = str(t).split("\n")
        n = len(lines)
        wt = ' font-weight="bold"' if bold else ""
        st = ' font-style="italic"' if italic else ""
        for i, line in enumerate(lines):
            yy = y + (i - (n - 1) / 2) * size * 1.22 + size * 0.35
            self.add(
                f'<text x="{x:.1f}" y="{yy:.1f}" font-family="{FONT}" font-size="{size}" '
                f'text-anchor="{anchor}"{wt}{st} fill="#000">{html.escape(line)}</text>'
            )

    def rect(self, x, y, w, h, fill="none", sw=2.5, rx=0, dash=False):
        d = ' stroke-dasharray="7 5"' if dash else ""
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="#000" stroke-width="{sw}"{d}/>'
        )

    def box(self, x, y, w, h, label="", size=15, bold=False, rx=8, dash=False, fill="none", sw=2.5):
        self.rect(x, y, w, h, fill=fill, sw=sw, rx=rx, dash=dash)
        if label:
            self.text(x + w / 2, y + h / 2, label, size, bold=bold)

    def line(self, x1, y1, x2, y2, sw=2.5, dash=False):
        d = ' stroke-dasharray="7 5"' if dash else ""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="{sw}"{d}/>')

    def arrow(self, x1, y1, x2, y2, sw=2.5, dash=False):
        d = ' stroke-dasharray="7 5"' if dash else ""
        self.add(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="{sw}"{d} '
            f'marker-end="url(#ah)"/>'
        )

    def parrow(self, pts, sw=2.5):
        p = " ".join(f"{x},{y}" for x, y in pts)
        self.add(f'<polyline points="{p}" fill="none" stroke="#000" stroke-width="{sw}" marker-end="url(#ah)"/>')

    def poly(self, pts, fill="none", sw=2.5, close=True):
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        tag = "polygon" if close else "polyline"
        self.add(f'<{tag} points="{p}" fill="{fill}" stroke="#000" stroke-width="{sw}" stroke-linejoin="round"/>')

    def circle(self, cx, cy, r, label="", size=14, fill="none", sw=2.5, bold=False):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="#000" stroke-width="{sw}"/>')
        if label:
            self.text(cx, cy, label, size, bold=bold)

    def diamond(self, cx, cy, w, h, label="", size=13):
        self.poly([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)])
        if label:
            self.text(cx, cy, label, size)

    def path(self, d, sw=2.5, fill="none", arrow=False):
        m = ' marker-end="url(#ah)"' if arrow else ""
        self.add(f'<path d="{d}" fill="{fill}" stroke="#000" stroke-width="{sw}"{m}/>')

    # ---------- composites ----------
    def chain(self, x0, y, w, h, gap, labels, size=14, bold_first_line=False):
        """Row of boxes joined by arrows."""
        for i, lab in enumerate(labels):
            x = x0 + i * (w + gap)
            self.box(x, y, w, h, lab, size=size)
            if i < len(labels) - 1:
                self.arrow(x + w, y + h / 2, x + w + gap, y + h / 2)

    def cup(self, cx, top, h, wt, wb, layers=(), size=14, ice_line=None, label_dx=34):
        """Side-view cup. layers: (label, fraction, pattern) bottom->top. Labels on the right."""
        def edge(yy):
            u = (yy - top) / h
            w = wt + (wb - wt) * u
            return cx - w / 2, cx + w / 2

        fills = {"none": "#fff", "dots": "url(#dots)", "hatch": "url(#hatch)",
                 "cross": "url(#cross)", "solid": "#000"}
        bottom = top + h
        y = bottom
        labels = []
        for lab, frac, pat in layers:
            y2 = y - frac * h
            l1, r1 = edge(y)
            l2, r2 = edge(y2)
            self.add(
                f'<polygon points="{l1:.1f},{y:.1f} {r1:.1f},{y:.1f} {r2:.1f},{y2:.1f} {l2:.1f},{y2:.1f}" '
                f'fill="{fills[pat]}" stroke="#000" stroke-width="1.5"/>'
            )
            if lab:
                mid = (y + y2) / 2
                labels.append([mid, lab, edge(mid)[1]])
            y = y2
        l0, r0 = edge(top)
        lb, rb = edge(bottom)
        self.poly([(l0, top), (lb, bottom), (rb, bottom), (r0, top)], sw=3.5, close=False)
        if ice_line is not None:
            yl = bottom - ice_line * h
            a, b = edge(yl)
            self.line(a - 10, yl, b + 10, yl, sw=2, dash=True)
        # spread labels top->bottom so they never overlap
        labels.sort(key=lambda t: t[0])
        prev = -1e9
        xl = cx + wt / 2 + label_dx
        for item in labels:
            mid, lab, ex = item
            nl = lab.count("\n") + 1
            need = nl * size * 1.25 / 2
            ly = max(mid, prev + need + 4)
            self.add(
                f'<polyline points="{ex:.1f},{mid:.1f} {xl - 8:.1f},{mid:.1f} {xl - 4:.1f},{ly:.1f}" '
                f'fill="none" stroke="#000" stroke-width="1.5"/>'
            )
            self.text(xl, ly, lab, size=size, anchor="start")
            prev = ly + need

    def stairs(self, x0, base, step_w, step_h0, step_dh, steps, size=15):
        for i, (a, b) in enumerate(steps):
            h = step_h0 + i * step_dh
            x = x0 + i * step_w
            self.rect(x, base - h, step_w, h, sw=2.5)
            self.text(x + step_w / 2, base - h + 24, a, size=size, bold=True)
            self.text(x + step_w / 2, base - h + 50, b, size=size - 1)

    # ---------- output ----------
    def svg(self):
        defs = (
            '<defs>'
            '<marker id="ah" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="9" refX="10" refY="4.5" orient="auto">'
            '<path d="M0,0 L11,4.5 L0,9 z" fill="#000"/></marker>'
            '<pattern id="dots" width="8" height="8" patternUnits="userSpaceOnUse">'
            '<circle cx="4" cy="4" r="1.4" fill="#000"/></pattern>'
            '<pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse">'
            '<path d="M-1,9 L9,-1" stroke="#000" stroke-width="1.6"/></pattern>'
            '<pattern id="cross" width="12" height="12" patternUnits="userSpaceOnUse">'
            '<path d="M0,0 L12,12 M12,0 L0,12" stroke="#000" stroke-width="1.2"/></pattern>'
            '</defs>'
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'{defs}<rect width="{W}" height="{H}" fill="#fff"/>' + "".join(self.el) + "</svg>"
        )
