from lib import *
from h import *

# ======================= SOP-201 =======================

@fig("fig-201-order-flow", "Order flow at the register")
def _(f):
    snake(f, ["1 Greet\nwithin 10 s", "2 Take the\nguest's name",
              "3 Ring in:\nsize, drink,\nmilk, modifiers",
              "4 Repeat order\nback + total", "5 Offer ONE\nsuggestion", "6 Take\npayment"],
          per_row=3, y0=52, h=80, size=15)


@fig("fig-201-sizes", "Cup sizes")
def _(f):
    for cx, h, name, oz in [(110, 100, "Small", "12 oz"), (288, 130, "Medium", "16 oz"), (466, 160, "Large", "20 oz")]:
        f.cup(cx, 215 - h, h, 90 + h * 0.25, 70 + h * 0.2, layers=())
        f.text(cx, 234, name, 16, bold=True)
        f.text(cx, 254, oz, 15)
    f.text(288, 277, "Flat White: Small and Medium only", 13)


@fig("fig-201-float", "Opening float: $150.00")
def _(f):
    items = [("2 x $20", "$40.00"), ("3 x $10", "$30.00"), ("6 x $5", "$30.00"),
             ("30 x $1", "$30.00"), ("2 rolls\nquarters", "$20.00")]
    for i, (a, b) in enumerate(items):
        x = 18 + i * 108
        f.box(x, 55, 100, 115, "", rx=6)
        f.text(x + 50, 92, a, 15, bold=True)
        f.line(x + 10, 130, x + 90, 130, sw=1.5)
        f.text(x + 50, 151, b, 16)
    f.text(288, 205, "Total = $150.00", 22, bold=True)
    f.text(288, 245, "Off by any amount? Tell the shift lead before opening.", 14)


@fig("fig-201-wait", "Wait time targets")
def _(f):
    x0, px = 40, 62.5
    X = lambda m: x0 + m * px
    f.rect(X(0), 105, 4 * px, 44, fill="#fff")
    f.rect(X(4), 105, 2 * px, 44, fill=DOTS)
    f.rect(X(6), 105, 2 * px, 44, fill=HATCH)
    f.text(X(2), 78, "Ready within\n4 min of payment", 14, bold=True)
    f.text(X(5), 78, "4-6 min:\nhurry", 14)
    f.text(X(7), 78, "Over 6 min:\napologize", 14, bold=True)
    for m, lab in [(0, "0"), (4, "4 min"), (6, "6 min"), (8, "8")]:
        f.line(X(m), 149, X(m), 160, sw=2)
        f.text(X(m), 175, lab, 14)
    f.text(288, 218, "Over 6 minutes: apologize and tell the shift lead.", 15)
    f.text(288, 243, "The shift lead may comp a drip coffee.", 15)


@fig("fig-201-mobile", "Mobile orders")
def _(f):
    f.chain(15, 75, 118, 105, 24, ["Orange banner\nappears\non the POS", "Accept within\n60 seconds",
                                    "Make the\ndrink", "Hand off by\norder NUMBER\n(not name)"], size=14)
    f.text(288, 225, "Mobile orders are handed off by number.", 15)

# ======================= SOP-202 =======================

@fig("fig-202-bill-check", "Checking a bill")
def _(f):
    f.box(15, 115, 100, 50, "Guest hands\nover a bill", 13)
    f.arrow(115, 140, 130, 140)
    f.diamond(185, 140, 110, 72, "$100\nbill?", 13)
    f.arrow(185, 104, 185, 87)
    f.text(200, 96, "yes", 12, anchor="start")
    f.box(120, 45, 130, 42, "Refuse. Max\nbill is $50", 13)
    f.arrow(240, 140, 268, 140)
    f.text(254, 128, "no", 12)
    f.box(268, 115, 104, 50, "Test the $50\nwith the pen", 13)
    f.arrow(372, 140, 385, 140)
    f.diamond(445, 140, 120, 72, "Mark\ncolor?", 13)
    f.arrow(445, 104, 445, 90)
    f.box(380, 47, 176, 43, "Amber / yellow:\ngenuine, accept", 13)
    f.arrow(445, 176, 445, 196)
    f.box(355, 196, 210, 80, "Dark brown / black:\nask for another\npayment method,\ncall shift lead", 13)


@fig("fig-202-refund-ladder", "Refund approval ladder")
def _(f):
    f.box(20, 50, 290, 56, "Within 24 hours, with receipt.\nAfter 24 hours: manager only.", 13, dash=True)
    f.stairs(30, 270, 172, 70, 60, [("Cashier", "$0.01-$10.00"),
                                    ("Shift lead", "$10.01-$25.00 (PIN)"),
                                    ("Manager", "over $25.00 (PIN)")])


@fig("fig-202-cash-drop", "Cash drop")
def _(f):
    f.chain(15, 70, 118, 120, 24, ["Drawer holds\nover $400.00", "Remove $200.00\nin $20 and\n$10 bills", "Put it through\nthe safe slot",
                                   "Record it on\nthe drop log"], size=14)
    f.text(288, 235, "Do it together with the shift lead.", 15)


@fig("fig-202-variance", "Till variance (count vs POS)")
def _(f):
    cuts = [40, 190, 360, 540]
    timeline_zones(f, 40, 540, 110, 40, cuts, ["#fff", DOTS, HATCH])
    for x, t in [(115, "Up to $2.00"), (275, "$2.00 to $5.00"), (450, "Over $5.00")]:
        f.text(x, 88, t, 15, bold=True)
    for x, t in [(115, "Note it on\nthe close form"), (275, "Tell shift lead\nnow, then recount"), (450, "Also needs a\nmanager signature")]:
        f.text(x, 195, t, 14)
    f.text(288, 255, "Variance = how far over or short you are vs the POS report", 13)


@fig("fig-202-close-till", "Closing the till")
def _(f):
    f.chain(15, 65, 100, 125, 11, ["1 End of Day\nreport\n(print 2)", "2 Count cash\ntwice in the\nback office", "3 Leave\n$150.00\nfloat",
                                   "4 Compare to\nthe POS\n(variance)", "5 Two people\nseal bag,\nsign, safe"], size=13)
    f.text(288, 235, "Rest of the cash goes in the bank bag.", 15)


@fig("fig-202-void-window", "Void or refund?")
def _(f):
    cuts = [40, 200, 420, 540]
    timeline_zones(f, 40, 540, 100, 40, cuts, ["#fff", DOTS, HATCH])
    f.text(120, 76, "VOID", 16, bold=True)
    f.text(310, 76, "REFUND", 16, bold=True)
    f.text(480, 76, "MANAGER", 16, bold=True)
    for x, t in [(40, "Payment"), (200, "5 min"), (420, "24 hours")]:
        f.line(x, 140, x, 152, sw=2)
        f.text(x if x > 40 else 52, 168, t, 14)
    f.text(120, 215, "Cashier voids\n(reason code)", 14)
    f.text(310, 215, "Refund to original payment,\nreceipt needed, approval\nlevel by amount", 14)
    f.text(480, 215, "Only a manager\napproves", 14)

# ======================= SOP-210 =======================

@fig("fig-210-handwash", "Handwashing: 20 seconds")
def _(f):
    f.chain(15, 70, 100, 105, 11, ["1 WET\nwarm water\n100°F or\nhotter", "2 SOAP", "3 SCRUB\n20 seconds", "4 RINSE",
                                   "5 DRY\nsingle-use\npaper towel"], size=14)
    f.text(288, 225, "Wash at shift start, after cash, restroom, trash,\ntouching face, hair or phone, between allergy orders.", 13)


@fig("fig-210-opening-timeline", "Opening: 5:15 to 6:00 AM")
def _(f):
    px = 500 / 45
    X = lambda m: 40 + m * px
    f.rect(X(0), 125, 30 * px, 30, fill=HATCH)
    f.rect(X(30), 125, 15 * px, 30, fill="#fff")
    f.text(15, 66, "5:15 arrive,\nclock in,\nespresso ON", 13, anchor="start")
    f.text(X(15), 108, "warm-up 30 min: NO shots", 14, bold=True)
    f.text(X(37.5), 100, "shots OK;\nopen at 6:00", 14, bold=True)
    for m, t in [(0, "5:15"), (30, "5:45"), (45, "6:00")]:
        f.line(X(m), 155, X(m), 166, sw=2)
        f.text(X(m), 180, t, 14)
    f.box(40, 202, 500, 72, "", dash=True, rx=6)
    f.text(290, 238, "Meanwhile: log fridge temps (41°F or below), set grinder,\nbrew drip, fill ice, sanitizer bucket 200-400 ppm, restock", 13)


@fig("fig-210-temps", "Temperature cheat sheet")
def _(f):
    f.rect(80, 45, 20, 225, rx=10)
    f.circle(90, 272, 14, fill="#000")
    T = lambda t: 270 - 1.25 * (t - 30)
    rows = [(41, 256, "41°F   Fridges: 41°F or below"), (100, 192, "100°F   Handwash water: minimum"),
            (110, 168, "110°F   Sink wash water"), (130, 145, "130°F   Kid's temp milk"),
            (152.5, 122, "150-155°F   Whole and 2% milk"), (160, 98, "160°F   Extra hot. NEVER above!"),
            (175, 74, "175°F   Matcha slurry water"), (200, 52, "200°F   Espresso brew water")]
    for t, ly, txt in rows:
        y = T(t)
        f.line(100, y, 140, y, sw=2.5)
        f.line(140, y, 160, ly, sw=1.5)
        f.text(168, ly, txt, 15, anchor="start", bold=(t == 160))


@fig("fig-210-sink", "Three-compartment sink")
def _(f):
    f.chain(15, 65, 118, 125, 24, ["1 WASH\nsoapy water\n110°F", "2 RINSE\nclear water", "3 SANITIZE\nquat\n200-400 ppm\n60 seconds",
                                   "4 AIR DRY\ndo not\ntowel dry"], size=14)
    f.text(288, 232, "Order: wash, rinse, sanitize, air dry.", 15)


@fig("fig-210-backflush", "Backflush the group heads")
def _(f):
    f.chain(15, 48, 160, 80, 33, ["Blind basket +\n3 g cleaner", "10 s ON / 10 s OFF\nrepeat 5 times", "Repeat 5 times\nwith plain water"], size=14)
    d = "M40,250 "
    for i in range(5):
        x = 40 + i * 100
        d += f"L{x},215 L{x+50},215 L{x+50},250 L{x+100},250 "
    f.path(d, sw=3)
    f.text(65, 200, "ON 10 s", 13)
    f.text(115, 270, "OFF 10 s", 13)
    f.text(420, 270, "5 cycles", 13)


@fig("fig-210-shelf-life", "Shelf life after opening")
def _(f):
    rows = [("Milks, half-and-half", 7, HATCH), ("Cold brew concentrate", 14, HATCH), ("Whipped cream", 14, HATCH),
            ("Matcha (opened)", 30, DOTS), ("Mocha sauce", 60, DOTS), ("Flavor syrups", 90, DOTS)]
    for i, (lab, d, pat) in enumerate(rows):
        y = 62 + i * 28
        f.text(20, y, lab, 14, anchor="start")
        f.rect(215, y - 10, d * 3.3, 20, fill=pat, sw=2)
        f.text(215 + d * 3.3 + 8, y, f"{d} days", 13, anchor="start")
    f.text(288, 232, "Drip coffee: discard after 60 MINUTES", 15, bold=True)
    f.rect(30, 256, 22, 14, fill=HATCH, sw=1.5)
    f.text(58, 263, "Fridge 41°F or below", 13, anchor="start")
    f.rect(270, 256, 22, 14, fill=DOTS, sw=1.5)
    f.text(298, 263, "Room temp / sealed, dry", 13, anchor="start")


@fig("fig-210-closing-flow", "Closing: back of house")
def _(f):
    snake(f, ["1 Last call\n7:45 PM", "2 Café closes\n8:00 PM", "3 Discard drip\nand leftover milk",
              "4 Three-sink:\nwash, rinse,\nsanitize", "5 Trash, sweep,\nmop", "6 Lock back door,\nmachine and\nlights off, alarm"],
          per_row=3, y0=52, h=82, size=14)

# ======================= SOP-220 =======================

@fig("fig-220-espresso-specs", "The espresso standard")
def _(f):
    f.chain(15, 62, 160, 100, 33, ["18.0 g\nground coffee\n(+/- 0.5 g)", "Machine\n200°F, 9 bar", "36 g espresso\nin 25 to 30 s"], size=15)
    f.text(288, 205, "Small and Medium = one double (2 shots)", 15)
    f.text(288, 230, "Large = double + single (3 shots)", 15)
    f.text(288, 258, "Single shot: 9.0 g in, 18 g out", 14)


@fig("fig-220-dialin-steps", "Dialing in the grinder")
def _(f):
    snake(f, ["1 Purge\n3 seconds", "2 Dose\n18.0 g", "3 Tamp\n~30 lb, level", "4 Pull shot,\nstart timer",
              "5 Stop at\n36 g", "6 Adjust\ngrind 1 notch", "7 Record on\ndial-in sheet"],
          per_row=4, y0=48, h=76, size=14)
    f.text(288, 277, "Dial in at opening and every 4 hours.", 13)


@fig("fig-220-dialin-scale", "Shot time: what to do")
def _(f):
    X = lambda s: 40 + (s - 15) * 20
    cuts = [X(15), X(22), X(25), X(30), X(33), X(40)]
    timeline_zones(f, 40, 540, 115, 46, cuts, [HATCH, DOTS, "#fff", DOTS, HATCH])
    f.text((cuts[0] + cuts[1]) / 2, 85, "Too fast:\ngrind FINER", 14, bold=True)
    f.text((cuts[1] + cuts[2]) / 2, 85, "taste\nit", 12)
    f.text((cuts[2] + cuts[3]) / 2, 85, "GOOD\n25-30 s", 14, bold=True)
    f.text((cuts[3] + cuts[4]) / 2, 85, "taste\nit", 12)
    f.text((cuts[4] + cuts[5]) / 2, 85, "Too slow:\ngrind COARSER", 14, bold=True)
    for s in (22, 25, 30, 33):
        f.line(X(s), 161, X(s), 172, sw=2)
        f.text(X(s), 188, f"{s}", 14)
    f.text(288, 225, "One notch at a time.", 15)
    f.text(288, 250, "Discard the first 2 shots after any change.", 15)


@fig("fig-220-milk-temps", "Steamed milk target temperatures")
def _(f):
    X = lambda t: 190 + (t - 120) * 7
    rows = [("Almond", 130, 140), ("Soy", 140, 150), ("Oat", 140, 150), ("Whole, 2%", 150, 155),
            ("Kid's temp", 130, 130), ("Extra hot", 160, 160)]
    for i, (lab, a, b) in enumerate(rows):
        y = 70 + i * 28
        f.text(20, y, lab, 15, anchor="start")
        if a == b:
            f.circle(X(a), y, 8, fill="#000")
        else:
            f.rect(X(a), y - 9, X(b) - X(a), 18, fill=HATCH)
    f.line(X(160), 52, X(160), 240, sw=2.5, dash=True)
    f.text(X(160), 42, "MAX 160°F", 14, bold=True)
    f.line(X(120), 242, X(170), 242, sw=2)
    for t in range(120, 171, 10):
        f.line(X(t), 242, X(t), 250, sw=2)
        f.text(X(t), 265, f"{t}", 13)


@fig("fig-220-steam-stages", "Steaming milk: stretch, then spin")
def _(f):
    # pitcher 1: stretch
    f.cup(130, 70, 100, 110, 90, layers=(), ice_line=0.6)
    f.line(205, 45, 142, 118, sw=6)
    f.text(130, 205, "1 STRETCH", 15, bold=True)
    f.text(130, 240, "tip just under the surface\n2-4 s latte, 6-8 s cappuccino,\n1-2 s flat white", 13)
    # pitcher 2: spin
    f.cup(430, 70, 100, 110, 90, layers=(), ice_line=0.6)
    f.line(500, 45, 440, 148, sw=6)
    f.path("M392,150 C392,172 470,172 470,150", sw=2.5, arrow=True)
    f.text(430, 205, "2 SPIN", 15, bold=True)
    f.text(430, 240, "tip deeper, whirlpool\nuntil target temperature", 13)
    f.arrow(215, 120, 335, 120)
    f.text(288, 278, "Cold pitcher, milk 38-41°F first. Then wipe, purge, swirl, pour in 30 s.", 12)


@fig("fig-220-troubleshoot", "Troubleshooting")
def _(f):
    rows = [("Under 22 s (sour, thin)", "Grind finer"), ("Over 33 s (bitter)", "Grind coarser"),
            ("Spurting stream", "Redistribute, tamp level"), ("Big bubbles in milk", "Shorter stretch"),
            ("Thin, watery milk", "Stretch longer"), ("Milk over 160°F", "Discard and restart")]
    for i, (a, b) in enumerate(rows):
        y = 46 + i * 39
        f.box(15, y, 268, 33, a, 14, rx=6)
        f.arrow(283, y + 16, 312, y + 16)
        f.box(312, y, 249, 33, b, 14, rx=6, bold=True)
