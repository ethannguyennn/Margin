"""Higher-level helpers for the figures."""
import math
from lib import *

DOTS, HATCH, CROSS = "url(#dots)", "url(#hatch)", "url(#cross)"


def snake(f, labels, per_row=3, y0=50, h=76, size=14, gap=24, x0=15, total=546, ymax=262):
    n = len(labels)
    rows = math.ceil(n / per_row)
    w = (total - (per_row - 1) * gap) / per_row
    rowgap = max(30, (ymax - y0 - rows * h) / (rows - 1)) if rows > 1 else 0
    for i, lab in enumerate(labels):
        r, c = divmod(i, per_row)
        x = x0 + c * (w + gap)
        y = y0 + r * (h + rowgap)
        f.box(round(x, 1), round(y, 1), round(w, 1), h, lab, size=size)
        last_in_row = c == per_row - 1 or i == n - 1
        if not last_in_row:
            f.arrow(x + w, y + h / 2, x + w + gap, y + h / 2)
        elif i < n - 1:
            xl = x + w / 2
            xf = x0 + w / 2
            f.parrow([(xl, y + h), (xl, y + h + rowgap / 2), (xf, y + h + rowgap / 2), (xf, y + h + rowgap)])


def clock(f, cx, cy, r=16):
    f.circle(cx, cy, r, sw=2.5)
    f.line(cx, cy, cx, cy - r * 0.65, sw=2.5)
    f.line(cx, cy, cx + r * 0.45, cy, sw=2.5)


def xmark(f, cx, cy, s=9):
    f.line(cx - s, cy - s, cx + s, cy + s, sw=3.5)
    f.line(cx - s, cy + s, cx + s, cy - s, sw=3.5)


def recipe(f, layers, sub, order, ice_line=None, cx=125, top=48, h=190):
    wt, wb = 130, 96
    f.cup(cx, top, h, wt, wb, layers=layers, size=15, ice_line=ice_line, label_dx=44)
    if ice_line is not None:
        yl = top + h - ice_line * h
        f.text(cx - wt / 2 - 12, yl, "ice\nline", 13, anchor="end")
    f.text(cx, 266, sub, 15, bold=True)
    f.text(237, 266, order, 13, anchor="start")


def timeline_zones(f, x0, x1, y, hh, cuts, fills):
    """cuts: list of x positions incl. both ends; fills: fill per zone."""
    for i, fl in enumerate(fills):
        f.rect(cuts[i], y, cuts[i + 1] - cuts[i], hh, fill=fl, sw=2.5)


def table(f, x, y, colw, rowh, rows, size=13, header=True):
    for r, row in enumerate(rows):
        cx = x
        for c, cell in enumerate(row):
            f.rect(cx, y + r * rowh, colw[c], rowh, sw=2 if not (header and r == 0) else 3)
            f.text(cx + colw[c] / 2, y + r * rowh + rowh / 2, cell, size, bold=(header and r == 0))
            cx += colw[c]
