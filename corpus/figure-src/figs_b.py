from lib import *
from h import *

LEG = "black = espresso   dots = foam   hatch = syrup/sauce   X = ice"

# ======================= SOP-230 recipes (Medium 16 oz cups) =======================

@fig("fig-230-latte", "Latte (hot)")
def _(f):
    recipe(f, [("2 shots espresso", .14, "solid"), ("steamed milk 12 oz", .70, "none"), ("foam 1/4 in", .06, "dots")],
           "Medium 16 oz", "Syrup, espresso, steam milk, pour")


@fig("fig-230-cappuccino", "Cappuccino")
def _(f):
    recipe(f, [("2 shots espresso", .14, "solid"), ("steamed milk 7 oz", .42, "none"), ("foam 3/4 in", .30, "dots")],
           "Medium 16 oz", "Espresso, steam (6-8 s), pour, spoon foam")


@fig("fig-230-flat-white", "Flat White (S and M only)")
def _(f):
    recipe(f, [("3 shots espresso", .20, "solid"), ("steamed milk 8 oz", .52, "none"), ("microfoam 1/8 in", .03, "dots")],
           "Medium 16 oz", "Espresso, steam (1-2 s), one smooth pour")


@fig("fig-230-americano", "Americano")
def _(f):
    recipe(f, [("hot water 12 oz (195°F)\nFIRST", .74, "none"), ("2 shots espresso\npoured on top", .14, "solid")],
           "Medium 16 oz", "Water first, then pour shots gently on top")


@fig("fig-230-iced-latte", "Iced Latte")
def _(f):
    recipe(f, [("cold milk 8 oz", .42, "none"), ("ice up to the ice line", .34, "cross"), ("2 shots espresso", .12, "solid")],
           "Medium 16 oz", "Syrup + milk, ice, espresso on top, stir", ice_line=.88)


@fig("fig-230-mocha", "Mocha")
def _(f):
    recipe(f, [("3 pumps mocha sauce", .08, "hatch"), ("2 shots espresso", .14, "solid"),
               ("steamed milk 10 oz", .56, "none"), ("whipped cream (optional)", .12, "dots")],
           "Medium 16 oz", "Sauce, espresso, stir, steam milk, whip")


@fig("fig-230-cold-brew", "Cold Brew")
def _(f):
    recipe(f, [("concentrate 6 oz", .36, "hatch"), ("water 6 oz", .36, "none")],
           "Medium 16 oz", "Ice to the line, concentrate, water, stir once", ice_line=.88)


@fig("fig-230-matcha", "Matcha Latte")
def _(f):
    recipe(f, [("matcha 4 g + 2 oz\n175°F water, whisked", .16, "dots"), ("steamed milk 12 oz", .70, "none")],
           "Medium 16 oz", "Sift, whisk slurry (W motion), add milk")


@fig("fig-230-pumps", "Pumps by size")
def _(f):
    f.text(175, 56, "Flavor syrup\n1 pump = 1/4 fl oz", 14, bold=True)
    f.text(425, 56, "Mocha sauce\n1 pump = 1/2 fl oz", 14, bold=True)
    f.line(300, 45, 300, 270, sw=1.5, dash=True)
    for i, (nm, n) in enumerate([("Small", 2), ("Medium", 3), ("Large", 4)]):
        y = 130 + i * 55
        f.text(15, y, nm, 15, anchor="start", bold=True)
        for k in range(n):
            f.circle(110 + k * 28, y, 9, fill="#000")
            f.circle(335 + k * 38, y, 14, fill="#000")
        f.text(232, y, f"{n} pumps", 14, anchor="start")
        f.text(335 + (n - 1) * 38 + 26, y, f"{n} pumps", 14, anchor="start")

# ======================= SOP-231 tea, chai, chocolate, steamer, frappe =======================

@fig("fig-231-tea", "Hot tea: water and steep time")
def _(f):
    for i, (nm, temp, mins) in enumerate([("BLACK", "205°F", "4 min"), ("GREEN", "175°F", "2 min"), ("HERBAL", "212°F", "5 min")]):
        x = 15 + i * 188
        f.box(x, 50, 170, 200, "", rx=10)
        cx = x + 85
        f.text(cx, 82, nm, 18, bold=True)
        f.text(cx, 135, temp, 30, bold=True)
        clock(f, cx - 38, 192, 17)
        f.text(cx + 22, 192, mins, 21)
        f.text(cx, 234, "then remove the bag", 12)
    f.text(288, 272, "One tea bag per cup. Steep, then remove the bag.", 13)


@fig("fig-231-chai", "Chai Latte")
def _(f):
    recipe(f, [("chai concentrate 6 oz", .38, "hatch"), ("steamed milk 8 oz", .50, "none"), ("foam", .06, "dots")],
           "Medium 16 oz", "Concentrate in cup, steam milk, pour")


@fig("fig-231-hot-chocolate", "Hot Chocolate")
def _(f):
    recipe(f, [("3 pumps mocha sauce", .08, "hatch"), ("steamed milk 14 oz", .76, "none"), ("whipped cream", .10, "dots")],
           "Medium 16 oz", "Sauce, hot steamed milk, stir, whip (free)")


@fig("fig-231-steamer", "Steamer (milk + syrup)")
def _(f):
    recipe(f, [("3 pumps syrup", .06, "hatch"), ("steamed milk 12 oz\nto 130°F", .72, "none"), ("foam", .06, "dots")],
           "Medium 16 oz", "Syrup in cup, steam milk to 130°F, pour")


@fig("fig-231-frappe", "Chocolate Frappe (blended)")
def _(f):
    f.chain(15, 55, 100, 110, 11, ["1 Milk into\nblender jar\n4 / 5 / 6 oz", "2 Mocha\nsauce\n2 / 3 / 4\npumps", "3 Ice\n1 / 1.5 / 2\ncups",
                                   "4 BLEND\n30 seconds\non HIGH", "5 Pour,\nwhipped\ncream"], size=13)
    f.text(288, 195, "Sizes in order: Small / Medium / Large", 14)
    f.text(288, 222, "Mocha frappe: add 1 shot of espresso.", 14)
    f.text(288, 250, "Wash the blender after every use.", 14)
