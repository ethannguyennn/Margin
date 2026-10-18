from lib import *
from h import *

# ======================= SOP-280 receiving and inventory =======================

@fig("fig-280-delivery-week", "Delivery week")
def _(f):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    w, g = 74, 4
    for i, d in enumerate(days):
        x = 15 + i * (w + g)
        f.box(x, 48, w, 28, d, 14, rx=4, bold=True, sw=3)
    f.box(15, 84, 7 * w + 6 * g, 36, "Pastry: EVERY day, before 6:00 AM", 14, rx=4, bold=True)
    items = {0: "Milk and\ndairy\n6:30-8:00", 2: "Dry goods,\ncups, lids", 3: "Milk and\ndairy\n6:30-8:00", 6: "Inventory\ncount at\nclose"}
    for i in range(7):
        x = 15 + i * (w + g)
        f.box(x, 130, w, 110, items.get(i, ""), 12, rx=4)
    f.text(288, 262, "Check every delivery before you sign.", 14)


@fig("fig-280-receiving-flow", "Receiving a delivery")
def _(f):
    f.box(15, 118, 100, 54, "Delivery\narrives", 14)
    f.arrow(115, 145, 135, 145)
    f.box(135, 118, 120, 54, "Count it\nagainst the\ninvoice", 13)
    f.arrow(255, 145, 275, 145)
    f.diamond(345, 145, 140, 92, "Dairy\n41°F or\nbelow?", 13)
    f.arrow(415, 145, 450, 145)
    f.text(432, 133, "yes", 12)
    f.box(450, 112, 110, 66, "Put away\nnow, FIFO", 14)
    f.arrow(345, 191, 345, 214)
    f.text(360, 203, "no", 12, anchor="start")
    f.box(240, 214, 210, 62, "Refuse it. Note it on\nthe invoice. Tell\nthe manager.", 13)


@fig("fig-280-fifo", "First in, first out")
def _(f):
    dates = ["Oct 3", "Oct 3", "Oct 5", "Oct 10", "Oct 10", "Oct 12"]
    for i, d in enumerate(dates):
        x = 40 + i * 83
        f.box(x, 90, 74, 80, d, 14, rx=4, bold=(i < 3), sw=3.5 if i < 3 else 2)
    f.text(40, 70, "FRONT", 15, anchor="start", bold=True)
    f.text(538, 70, "BACK", 15, anchor="end", bold=True)
    f.arrow(250, 195, 60, 195)
    f.text(155, 218, "take from here (oldest)", 14)
    f.arrow(340, 195, 520, 195)
    f.text(430, 218, "new stock goes behind", 14)
    f.text(288, 258, "Label every item with its date.", 14)


@fig("fig-280-par", "Par levels and reorder point")
def _(f):
    rows = [("Whole milk", 8, 3, "gal"), ("Oat milk", 12, 4, "cartons"), ("Espresso beans", 20, 8, "lb"),
            ("16 oz hot cups", 6, 2, "sleeves"), ("Mocha sauce", 6, 2, "bottles")]
    for i, (n, par, ro, u) in enumerate(rows):
        y = 70 + i * 40
        f.text(15, y, n, 14, anchor="start")
        f.rect(150, y - 11, 240, 22, sw=2.5)
        f.rect(150, y - 11, 240 * ro / par, 22, fill=HATCH, sw=2.5)
        f.text(402, y, f"par {par}, reorder at {ro} {u}", 12, anchor="start")
    f.text(288, 268, "Hatched part = at or below this, put it on the order list.", 13)


@fig("fig-280-waste-log", "Waste log")
def _(f):
    rows = [["Date", "Item", "Qty", "Reason", "Initials"],
            ["Oct 12", "Oat milk", "1 carton", "past 7 days", "EN"],
            ["Oct 12", "Drip coffee", "1 carafe", "60 min", "EN"],
            ["", "", "", "", ""]]
    table(f, 20, 55, [90, 130, 100, 130, 86], 40, rows, size=14)
    f.text(288, 240, "Write down everything you throw away.", 15, bold=True)
    f.text(288, 264, "Sample entries shown.", 13)

# ======================= SOP-290 safety =======================

@fig("fig-290-pass", "Fire extinguisher: P.A.S.S.")
def _(f):
    f.chain(15, 55, 118, 105, 24, ["P  PULL\nthe pin", "A  AIM at the\nbase of the\nfire", "S  SQUEEZE\nthe handle", "S  SWEEP side\nto side"], size=14)
    f.text(288, 195, "Extinguisher: on the wall by the back door.", 15, bold=True)
    f.text(288, 225, "Fire too big? Do not fight it:", 14)
    f.text(288, 248, "leave, call 911, meet at the parking lot corner.", 14)


@fig("fig-290-burn", "Burn first aid")
def _(f):
    f.chain(15, 60, 118, 105, 24, ["1 Cool under\ncool running\nwater", "2 At least\n10 MINUTES", "3 Tell the\nshift lead", "4 Report to the\nmanager the\nsame day"], size=14)
    f.text(288, 205, "Severe burn or not sure? Call 911.", 15, bold=True)
    f.text(288, 232, "First aid kit: under the back counter by the dish sink.", 13)


@fig("fig-290-evac", "Fire: get out")
def _(f):
    f.box(25, 48, 330, 190, "", rx=4, sw=3.5)
    f.text(190, 68, "CAFÉ", 15, bold=True)
    f.text(335, 134, "FRONT door", 12, anchor="end")
    f.text(130, 222, "BACK door", 12)
    f.box(395, 135, 160, 125, "", rx=4, dash=True)
    f.text(475, 153, "parking lot", 13)
    f.circle(475, 205, 38, "MEET\nHERE", 13, bold=True)
    f.parrow([(200, 150), (420, 150), (450, 175)])
    f.parrow([(110, 110), (110, 262), (390, 262), (445, 240)])
    f.text(250, 280, "Call 911 once you are outside.", 13)


@fig("fig-290-power", "Power outage")
def _(f):
    f.chain(15, 55, 118, 105, 24, ["1 Power goes\nout", "2 Tell shift\nlead, call\nmanager", "3 Cash only,\nwrite orders\non paper", "4 Over 30 min:\nmanager decides\nto close"], size=14)
    f.text(288, 205, "Keep fridge doors CLOSED.", 16, bold=True)
    f.text(288, 235, "Dairy above 41°F for over 4 hours: discard.", 14)


@fig("fig-290-spill", "Spills and broken glass")
def _(f):
    f.chain(15, 60, 118, 100, 24, ["1 Yellow\nwet-floor sign\nout NOW", "2 Wipe up\nthe spill", "3 Dry the\nfloor", "4 Remove sign\nonly when the\nfloor is dry"], size=14)
    f.box(40, 190, 496, 62, "Broken glass: sweep with a dustpan.\nNEVER pick it up by hand.", 15, dash=True)


@fig("fig-290-where", "Where things are")
def _(f):
    boxes = [("FIRST AID KIT", "under the back counter\nby the dish sink"), ("FIRE EXTINGUISHER", "on the wall\nby the back door"),
             ("ALLERGEN BINDER", "drawer under\nthe register"), ("SPARE PAPER ROLLS", "cabinet under\nthe register")]
    for i, (a, b) in enumerate(boxes):
        x = 15 + (i % 2) * 280
        y = 50 + (i // 2) * 115
        f.box(x, y, 266, 100, "", rx=8)
        f.text(x + 133, y + 28, a, 16, bold=True)
        f.text(x + 133, y + 68, b, 14)

# ======================= SOP-300 team policies =======================

@fig("fig-300-time-off", "Requesting time off")
def _(f):
    f.chain(15, 55, 160, 90, 33, ["1 Submit in the\nschedule app\n14+ days ahead", "2 Manager answers\nwithin 7 days", "3 Approved:\nit is on the\nschedule"], size=14)
    f.box(40, 185, 496, 70, "Sick or emergency: call the manager at least\n2 hours before your shift. A text alone is not enough.", 14, dash=True)


@fig("fig-300-breaks", "Breaks in an 8-hour shift")
def _(f):
    X = lambda h: 40 + h * 62.5
    f.line(X(0), 140, X(8), 140, sw=3)
    for h in range(9):
        f.line(X(h), 140, X(h), 150, sw=2)
        f.text(X(h), 164, f"{h}", 13)
    f.text(288, 184, "hours into the shift", 12)
    f.rect(X(2) - 6, 124, 12, 32, fill="#000")
    f.rect(X(6) - 6, 124, 12, 32, fill="#000")
    f.rect(X(4) - 16, 124, 32, 32, fill=HATCH)
    f.text(X(2), 96, "10 min\npaid break", 14, bold=True)
    f.text(X(4), 96, "30 min\nunpaid meal", 14, bold=True)
    f.text(X(6), 96, "10 min\npaid break", 14, bold=True)
    f.text(288, 225, "One 10-minute paid break for every 4 hours.", 14)
    f.text(288, 250, "30-minute unpaid meal break on shifts over 5 hours.", 14)


@fig("fig-300-uniform", "Uniform check")
def _(f):
    f.circle(140, 88, 24)
    f.path("M116,82 A24,24 0 0 1 164,82 L170,86 L110,86 Z", sw=2.5, fill="#000")
    f.poly([(104, 118), (176, 118), (184, 190), (96, 190)], sw=2.5)
    f.rect(114, 134, 52, 56, fill=HATCH, sw=2)
    f.rect(120, 124, 16, 8, fill="#fff", sw=2)
    f.rect(112, 190, 28, 58, fill="#000")
    f.rect(142, 190, 28, 58, fill="#000")
    f.rect(104, 248, 38, 12, fill="#000")
    f.rect(140, 248, 38, 12, fill="#000")
    for (px, py, ly, t) in [(164, 76, 62, "Hair tied back or cap"), (136, 128, 112, "Name tag"),
                            (166, 160, 160, "Clean Ember & Oak apron"), (170, 215, 210, "Black pants"),
                            (178, 254, 254, "Closed, non-slip shoes")]:
        f.line(px, py, 262, ly, sw=1.5)
        f.text(270, ly, t, 15, anchor="start")


@fig("fig-300-training", "Training path")
def _(f):
    f.stairs(30, 270, 172, 80, 55, [("Shifts 1-3", "shadow a trainer"), ("Shifts 4-10", "work with a buddy"),
                                    ("Days 30/60/90", "manager check-ins")], size=14)


@fig("fig-300-shift-swap", "Swapping a shift")
def _(f):
    f.chain(15, 60, 118, 105, 24, ["1 Ask a\nteammate", "2 They agree\nin the\nschedule app", "3 Manager\napproves", "4 Schedule\nupdates"], size=14)
    f.text(288, 205, "Manager must approve at least", 15)
    f.text(288, 230, "24 hours before the shift.", 15, bold=True)
