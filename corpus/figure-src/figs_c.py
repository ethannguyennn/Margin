from lib import *
from h import *

# ======================= SOP-240 food display =======================

@fig("fig-240-case", "Display cases")
def _(f):
    f.box(20, 45, 270, 230, "", rx=8, sw=3)
    f.text(155, 66, "PASTRY CASE", 16, bold=True)
    f.text(155, 86, "room temperature", 13)
    for i, t in enumerate(["Croissants", "Muffins", "Bagels", "Cookies"]):
        x = 32 + (i % 2) * 124
        y = 104 + (i // 2) * 68
        f.box(x, y, 114, 56, t, 14, rx=6)
    f.text(155, 250, "tongs only, allergen labels", 13)
    f.box(306, 45, 250, 230, "", rx=8, sw=3)
    f.text(431, 66, "COLD CASE", 16, bold=True)
    f.text(431, 86, "41°F or below", 13, bold=True)
    for i, t in enumerate(["Breakfast\nsandwiches", "Egg bites", "Yogurt\nparfaits", "Fruit cups"]):
        x = 318 + (i % 2) * 114
        y = 104 + (i // 2) * 68
        f.box(x, y, 106, 56, t, 14, rx=6)
    f.text(431, 250, "temp log at open and close", 13)


@fig("fig-240-warming", "Toaster oven 350°F: warming times")
def _(f):
    X = lambda m: 190 + m * 50
    rows = [("Croissant", 3), ("Muffin", 2), ("Bagel (toasted)", 2), ("Breakfast sandwich", 6)]
    for i, (lab, m) in enumerate(rows):
        y = 70 + i * 40
        f.text(15, y, lab, 14, anchor="start")
        f.rect(X(0), y - 11, m * 50, 22, fill=HATCH if i < 3 else DOTS)
        f.text(X(m) + 8, y, f"{m} min", 14, anchor="start", bold=True)
    f.line(X(0), 232, X(7), 232, sw=2)
    for m in range(8):
        f.line(X(m), 232, X(m), 240, sw=2)
        f.text(X(m), 254, str(m), 13)
    f.text(288, 277, "Sandwich is done at 165°F inside. Probe it.", 13)


@fig("fig-240-markdown", "Pastry day timeline")
def _(f):
    X = lambda h: 40 + h * 500 / 14
    timeline_zones(f, 40, 540, 110, 40, [X(0), X(12), X(14)], ["#fff", DOTS])
    f.text(X(6), 88, "Full price", 16, bold=True)
    f.text(X(13), 88, "50% off", 15, bold=True)
    for h, t, a, dx in [(0, "6:00 AM\nopen", "start", -2), (12, "6:00 PM", "middle", -22), (14, "8:00 PM\nclose", "end", 2)]:
        f.line(X(h), 150, X(h), 162, sw=2)
        f.text(X(h) + dx, 184, t, 14, anchor=a)
    f.text(288, 235, "6:00 PM: mark remaining pastries 50% off.", 15)
    f.text(288, 260, "At close: discard what is left. No day-old sales.", 15)


@fig("fig-240-sandwich-temp", "Breakfast sandwich: 165°F")
def _(f):
    f.box(80, 180, 140, 34, "", rx=14)
    f.rect(75, 158, 150, 22, fill=HATCH, sw=2)
    f.box(80, 120, 140, 38, "", rx=18)
    f.line(150, 94, 150, 190, sw=5)
    f.circle(150, 70, 24, "165°F", 13, fill="#fff", bold=True)
    f.text(255, 80, "Cook until the inside reads 165°F.", 14, anchor="start")
    f.text(255, 120, "Probe the center, not the edge.", 14, anchor="start")
    f.text(255, 160, "Wipe the probe with a sanitizer\nwipe between uses.", 14, anchor="start")
    f.text(255, 210, "Handle with tongs or clean gloves.", 14, anchor="start")

# ======================= SOP-250 guest service =======================

@fig("fig-250-complaint", "Handling a complaint")
def _(f):
    f.box(15, 48, 150, 62, "1 LISTEN\nlet them finish", 14)
    f.arrow(165, 79, 213, 79)
    f.box(213, 48, 150, 62, "2 APOLOGIZE\nbriefly, sincerely", 14)
    f.arrow(363, 79, 411, 79)
    f.box(411, 48, 150, 62, "3 FIX IT\nfree remake first", 14)
    f.arrow(486, 110, 486, 148)
    f.diamond(486, 188, 140, 80, "Guest\nhappy?", 14)
    f.arrow(416, 188, 340, 188)
    f.text(378, 176, "yes", 13)
    f.box(190, 165, 150, 46, "Thank them,\nback to work", 14)
    f.arrow(486, 228, 486, 246)
    f.text(502, 238, "no", 13, anchor="start")
    f.box(386, 246, 170, 34, "Get the shift lead", 14, bold=True)


@fig("fig-250-comp-ladder", "Who can comp or refund goods")
def _(f):
    f.stairs(30, 270, 172, 70, 60, [("Cashier", "remake free, up to $5.00"), ("Shift lead", "up to $15.00"),
                                    ("Manager", "over $15.00")], size=14)


@fig("fig-250-escalation", "Upset or unsafe guest")
def _(f):
    f.stairs(30, 270, 172, 80, 55, [("1 Stay calm", "listen, no arguing"), ("2 Shift lead", "hand it over"),
                                    ("3 Unsafe?", "call 911")], size=14)
    f.box(20, 50, 300, 56, "Never raise your voice.\nYou may step away at any time.", 14, dash=True)


@fig("fig-250-lost-found", "Lost and found")
def _(f):
    f.chain(15, 55, 118, 105, 24, ["Item found\nin the café", "Bag + tag:\ndate and\nwhere found", "Shelf in the\nback office", "Kept 30 days,\nthen manager\ndisposes"], size=14)
    f.text(288, 205, "Phones, wallets, keys: give to the shift lead.", 15, bold=True)
    f.text(288, 235, "They go in the safe, not on the shelf.", 15)

# ======================= SOP-260 front of house =======================

@fig("fig-260-floorplan", "Café floor plan")
def _(f):
    f.box(20, 42, 536, 238, "", rx=4, sw=3.5)
    f.box(26, 48, 168, 92, "BACK OF HOUSE\ndish sink, walk-in,\noffice", 13, rx=0)
    f.box(204, 52, 104, 52, "Register", 14, rx=0)
    f.box(308, 52, 150, 52, "Espresso bar", 14, rx=0)
    f.box(468, 52, 82, 52, "Condiment\nbar", 13, rx=0)
    f.text(256, 122, "COUNTER", 12)
    for i in range(4):
        f.circle(80 + i * 78, 205, 20, f"T{i+1}", 14)
    f.box(430, 170, 120, 100, "Restroom", 14, rx=0)
    f.box(240, 262, 80, 18, "FRONT DOOR", 11, rx=0, fill="#fff")
    f.arrow(280, 250, 280, 232)
    f.text(60, 262, "Back door (by BOH)", 12, anchor="start")


@fig("fig-260-lobby-cycle", "Lobby check: every 30 minutes")
def _(f):
    f.box(25, 60, 200, 60, "1 Tables wiped,\nchairs in place", 14)
    f.box(351, 60, 200, 60, "2 Trash emptied\nwhen 3/4 full", 14)
    f.box(351, 190, 200, 60, "3 Restroom checked,\nsign the log", 14)
    f.box(25, 190, 200, 60, "4 Condiment bar\nrestocked", 14)
    f.arrow(225, 90, 351, 90)
    f.arrow(451, 120, 451, 190)
    f.arrow(351, 220, 225, 220)
    f.arrow(125, 190, 125, 120)
    f.text(288, 155, "every\n30 min", 18, bold=True)


@fig("fig-260-table-reset", "Resetting a table")
def _(f):
    f.chain(15, 70, 118, 100, 24, ["1 Clear cups\nand trash", "2 Wipe with the\nsanitizer\ncloth", "3 Let it\nair dry", "4 Chairs\npushed in"], size=14)
    f.text(288, 215, "Cloth lives in the sanitizer bucket", 15)
    f.text(288, 240, "(200 to 400 ppm).", 15)


@fig("fig-260-closing-timeline", "Closing the front of house")
def _(f):
    X = lambda m: 40 + m * 500 / 90
    timeline_zones(f, 40, 540, 115, 36, [X(0), X(15), X(30), X(75), X(90)], ["#fff", DOTS, HATCH, "#fff"])
    for m, t in [(0, "7:30"), (15, "7:45"), (30, "8:00"), (75, "8:45"), (90, "9:00")]:
        f.line(X(m), 151, X(m), 162, sw=2)
        f.text(X(m), 176, t, 13)
    f.text(X(7.5), 92, "open", 14)
    f.text(X(22.5), 85, "last\ncall", 14, bold=True)
    f.text(X(52.5), 92, "closing tasks", 14, bold=True)
    f.text(288, 225, "7:45 last call.  8:00 doors locked.", 15)
    f.text(288, 252, "Target: all closing tasks done by 8:45.", 15)

# ======================= SOP-270 equipment cleaning =======================

@fig("fig-270-ice-machine", "Ice machine: monthly clean")
def _(f):
    snake(f, ["1 Turn off,\ndump all ice", "2 Add ice machine\ncleaner (only the\napproved one)", "3 Run clean\ncycle 20 min",
              "4 Rinse with\nclear water", "5 Sanitize\nquat 200-400 ppm", "6 Restart,\ntoss first batch\nof ice"],
          per_row=3, y0=52, h=82, size=14)


@fig("fig-270-schedule", "Cleaning schedule")
def _(f):
    rows = [("Backflush group heads", 0), ("Steam wand wipe + purge", 0), ("Grinder: brush burr chamber", 0),
            ("Grinder deep clean (Sunday)", 1), ("Batch brewer clean cycle (Sunday)", 1),
            ("Fridge shelves wipe (Wednesday)", 1), ("Ice machine (1st Monday)", 2)]
    cols = ["Daily", "Weekly", "Monthly"]
    cx = [385, 455, 525]
    for c, t in zip(cx, cols):
        f.text(c, 60, t, 13, bold=True)
    f.line(15, 74, 561, 74, sw=3)
    for i, (lab, c) in enumerate(rows):
        y = 94 + i * 25
        f.text(15, y, lab, 13, anchor="start")
        f.line(15, y + 13, 561, y + 13, sw=1)
        xmark(f, cx[c], y, 7)


@fig("fig-270-blender", "Blender wash")
def _(f):
    f.chain(15, 60, 118, 110, 24, ["1 Rinse\nthe jar", "2 Warm water +\nsoap, blend\n10 seconds", "3 Rinse\nclean", "4 Sanitize 60 s,\nair dry"], size=13)
    f.text(288, 215, "After EVERY use. Allergy order? Wash again.", 15)


@fig("fig-270-grinder", "Grinder parts")
def _(f):
    f.poly([(110, 55), (230, 55), (202, 120), (138, 120)], sw=3)
    f.box(128, 120, 84, 62, "", rx=4)
    f.rect(158, 182, 24, 32)
    f.rect(100, 214, 140, 14, fill="#000")
    f.rect(240, 217, 70, 8, fill="#000")
    for (px, py, ly, t) in [(230, 88, 85, "Bean hopper:\ncheck, purge a few grams"), (212, 150, 150, "Burr chamber:\nbrush out every day"),
                            (240, 221, 222, "Portafilter fork")]:
        f.line(px, py, 330, ly, sw=1.5)
        f.text(338, ly, t, 14, anchor="start")
    f.text(338, 258, "Deep clean every\nSunday at close", 13, anchor="start", bold=True)


@fig("fig-270-brewer", "Batch brewer: Sunday clean")
def _(f):
    f.chain(15, 65, 118, 105, 24, ["1 Dump coffee,\nrinse the\ncarafe", "2 Run a cycle\nwith brewer\ncleaner", "3 Run a cycle\nwith plain\nwater", "4 Wipe the\nspray head"], size=14)
    f.text(288, 215, "Daily: rinse the carafe and basket.", 15)
