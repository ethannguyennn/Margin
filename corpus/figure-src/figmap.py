"""Attach every figure to a SOP: (sop, '##' number, fig id, caption with the key facts)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
import importlib, lib
for m in ("figs_a", "figs_b", "figs_c", "figs_d"):
    importlib.import_module(m)

CORPUS = os.path.join(os.path.dirname(__file__), "..")

MAP = [
 # ---- SOP-201
 ("SOP-201", 2, "fig-201-float", "Opening float is $150.00: 2 x $20 = $40.00, 3 x $10 = $30.00, 6 x $5 = $30.00, 30 x $1 = $30.00, and 2 rolls of quarters = $20.00. If it is off by any amount, tell the shift lead before opening."),
 ("SOP-201", 3, "fig-201-order-flow", "Order flow: 1 greet within 10 seconds, 2 take the guest's name, 3 ring in size, drink, milk, then modifiers, 4 repeat the order back with the total, 5 offer one suggestion, 6 take payment."),
 ("SOP-201", 4, "fig-201-sizes", "Cup sizes: Small is 12 oz, Medium is 16 oz, Large is 20 oz. Flat White is sold in Small and Medium only."),
 ("SOP-201", 6, "fig-201-wait", "Wait time targets: ready within 4 minutes of payment is the target. Between 4 and 6 minutes, hurry. Over 6 minutes, apologize and tell the shift lead, who may comp a drip coffee."),
 ("SOP-201", 6, "fig-201-mobile", "Mobile orders: an orange banner appears on the POS, accept within 60 seconds, make the drink, and hand it off by order number, not by name."),
 # ---- SOP-202
 ("SOP-202", 2, "fig-202-bill-check", "Checking a bill: refuse any $100 bill because the largest bill we accept is $50. Mark every $50 with the counterfeit pen. Amber or yellow means genuine. Dark brown or black means it may be counterfeit: ask for another payment method and call the shift lead."),
 ("SOP-202", 3, "fig-202-cash-drop", "Cash drop: when the drawer holds more than $400.00, do a drop with the shift lead. Remove $200.00 in $20 and $10 bills, put it through the safe slot, and record it on the drop log."),
 ("SOP-202", 5, "fig-202-void-window", "Void or refund: a cashier may void before payment is finalized or within 5 minutes after payment. After that it is a refund, which needs the receipt and is available within 24 hours. After 24 hours only a manager may approve."),
 ("SOP-202", 5, "fig-202-refund-ladder", "Refund approval ladder: Cashier approves $0.01 to $10.00. Shift lead (PIN) approves $10.01 to $25.00. Manager (PIN) approves over $25.00. Within 24 hours with receipt; after 24 hours manager only."),
 ("SOP-202", 7, "fig-202-close-till", "Closing the till: 1 print two End of Day reports, 2 count cash twice in the back office, 3 leave $150.00 float in the drawer bag, 4 compare to the POS report, 5 two people seal the bank bag, both sign the close log, and the drawer goes in the safe."),
 ("SOP-202", 7, "fig-202-variance", "Till variance: up to $2.00 over or short is noted on the close form. Over $2.00 is reported to the shift lead right away and recounted. Over $5.00 also needs a manager signature."),
 # ---- SOP-210
 ("SOP-210", 2, "fig-210-handwash", "Handwashing: 1 wet hands with warm water of at least 100°F, 2 soap, 3 scrub for 20 seconds, 4 rinse, 5 dry with a single-use paper towel."),
 ("SOP-210", 3, "fig-210-opening-timeline", "Opening timeline: arrive 5:15 AM, clock in, turn on the espresso machine. It warms up for 30 minutes, so no shots before 5:45 AM. The café opens at 6:00 AM. Meanwhile log fridge temperatures, set the grinder, brew drip, fill ice, set up the sanitizer bucket, and restock."),
 ("SOP-210", 4, "fig-210-temps", "Temperature cheat sheet: fridges 41°F or below, handwash water at least 100°F, sink wash water 110°F, kid's temp milk 130°F, whole and 2 percent milk 150 to 155°F, extra hot and the maximum 160°F (never above), matcha slurry water 175°F, espresso brew water 200°F."),
 ("SOP-210", 4, "fig-210-shelf-life", "Shelf life after opening: milks and half-and-half 7 days, cold brew concentrate 14 days, whipped cream 14 days, matcha 30 days, mocha sauce 60 days, flavor syrups 90 days. Drip coffee is discarded after 60 minutes."),
 ("SOP-210", 5, "fig-210-backflush", "Backflush: insert the blind basket with 3 g of cleaner, run 10 seconds on and 10 seconds off, five times. Then repeat five times with plain water."),
 ("SOP-210", 6, "fig-210-sink", "Three-compartment sink: 1 wash in soapy water at 110°F, 2 rinse in clear water, 3 sanitize in quat at 200 to 400 ppm for 60 seconds, 4 air dry and do not towel dry."),
 ("SOP-210", 6, "fig-210-closing-flow", "Closing, back of house: 1 last call 7:45 PM, 2 close 8:00 PM, 3 discard drip and leftover milk, 4 three-compartment sink, 5 trash, sweep and mop, 6 lock the back door, turn off the espresso machine and lights, set the alarm."),
 # ---- SOP-220
 ("SOP-220", 2, "fig-220-espresso-specs", "Espresso standard: 18.0 g of ground coffee (plus or minus 0.5 g) at 200°F and 9 bar gives 36 g of espresso in 25 to 30 seconds. Small and Medium use a double (2 shots). Large uses a double plus a single (3 shots). A single is 9.0 g in and 18 g out."),
 ("SOP-220", 3, "fig-220-dialin-steps", "Dial-in steps: 1 purge 3 seconds, 2 dose 18.0 g, 3 tamp about 30 lb and level, 4 pull the shot and start the timer, 5 stop at 36 g, 6 adjust the grind one notch, 7 record on the dial-in sheet. Dial in at opening and every 4 hours."),
 ("SOP-220", 3, "fig-220-dialin-scale", "Shot time scale: under 22 seconds, grind finer. 22 to 25 seconds, taste it. 25 to 30 seconds is good. 30 to 33 seconds, taste it. Over 33 seconds, grind coarser. Change one notch at a time and discard the first 2 shots after any change."),
 ("SOP-220", 4, "fig-220-milk-temps", "Milk temperatures: almond 130 to 140°F, soy 140 to 150°F, oat 140 to 150°F, whole and 2 percent 150 to 155°F, kid's temp 130°F, extra hot 160°F. Never exceed 160°F."),
 ("SOP-220", 4, "fig-220-steam-stages", "Steaming: stretch with the tip just under the surface (2 to 4 seconds latte, 6 to 8 seconds cappuccino, 1 to 2 seconds flat white), then spin with the tip deeper until the milk reaches its target temperature. Start with cold milk at 38 to 41°F, then wipe, purge, swirl, and pour within 30 seconds."),
 ("SOP-220", 5, "fig-220-troubleshoot", "Troubleshooting: under 22 seconds, grind finer. Over 33 seconds, grind coarser. Spurting stream, redistribute and tamp level. Big bubbles, shorten the stretch. Thin milk, stretch longer. Milk over 160°F, discard and restart."),
 # ---- SOP-230
 ("SOP-230", 1, "fig-230-pumps", "Pumps by size: flavor syrup is 2, 3, 4 pumps for Small, Medium, Large and one pump is 1/4 fl oz. Mocha sauce is 2, 3, 4 pumps for Small, Medium, Large and one pump is 1/2 fl oz."),
 ("SOP-230", 2, "fig-230-latte", "Medium latte: 2 shots of espresso, 12 oz of steamed milk, and about 1/4 inch of foam. Syrup goes in first if flavored."),
 ("SOP-230", 3, "fig-230-cappuccino", "Medium cappuccino: 2 shots of espresso, 7 oz of steamed milk, and 3/4 inch of foam."),
 ("SOP-230", 4, "fig-230-flat-white", "Medium flat white: 3 shots of espresso, 8 oz of steamed milk, and 1/8 inch of microfoam. Made in Small and Medium only."),
 ("SOP-230", 5, "fig-230-americano", "Medium americano: 12 oz of hot water at 195°F goes in first, then 2 shots of espresso poured gently on top."),
 ("SOP-230", 6, "fig-230-iced-latte", "Medium iced latte: 8 oz of cold milk, ice up to the ice line, then 2 shots of espresso on top. Stir."),
 ("SOP-230", 7, "fig-230-mocha", "Medium mocha: 3 pumps of mocha sauce, 2 shots of espresso, 10 oz of steamed milk, and optional whipped cream."),
 ("SOP-230", 8, "fig-230-cold-brew", "Medium cold brew: ice up to the ice line, 6 oz of concentrate, then 6 oz of water, and stir once."),
 ("SOP-230", 9, "fig-230-matcha", "Medium matcha latte: 4 g of matcha whisked with 2 oz of 175°F water, then 12 oz of steamed milk."),
 # ---- SOP-231
 ("SOP-231", 2, "fig-231-tea", "Tea: black tea 205°F for 4 minutes, green tea 175°F for 2 minutes, herbal tea 212°F for 5 minutes. One tea bag per cup, then remove the bag."),
 ("SOP-231", 3, "fig-231-chai", "Medium chai latte: 6 oz of chai concentrate and 8 oz of steamed milk with a little foam."),
 ("SOP-231", 4, "fig-231-hot-chocolate", "Medium hot chocolate: 3 pumps of mocha sauce and 14 oz of steamed milk, with optional whipped cream."),
 ("SOP-231", 5, "fig-231-steamer", "Medium steamer: 3 pumps of syrup and 12 oz of milk steamed to 130°F."),
 ("SOP-231", 6, "fig-231-frappe", "Chocolate frappe: milk 4, 5, 6 oz, mocha sauce 2, 3, 4 pumps, and ice 1, 1.5, 2 cups for Small, Medium, Large. Blend 30 seconds on high. A mocha frappe adds one shot of espresso."),
 # ---- SOP-240
 ("SOP-240", 2, "fig-240-case", "The pastry case holds croissants, muffins, bagels, and cookies at room temperature. The cold case holds breakfast sandwiches, egg bites, yogurt parfaits, and fruit cups at 41°F or below. Log the cold case temperature at open and close."),
 ("SOP-240", 4, "fig-240-warming", "Toaster oven at 350°F: croissant 3 minutes, muffin 2 minutes, bagel 2 minutes, breakfast sandwich 6 minutes."),
 ("SOP-240", 4, "fig-240-sandwich-temp", "A breakfast sandwich is done when the inside reads 165°F. Probe the center, and wipe the probe with a sanitizer wipe between uses."),
 ("SOP-240", 5, "fig-240-markdown", "Pastry day: full price from 6:00 AM to 6:00 PM, 50 percent off from 6:00 PM, and throw away everything unsold at 8:00 PM close. No day-old sales."),
 # ---- SOP-250
 ("SOP-250", 3, "fig-250-complaint", "Complaint steps: 1 listen, 2 apologize, 3 fix it with a free remake first. If the guest is happy, thank them. If not, get the shift lead."),
 ("SOP-250", 4, "fig-250-comp-ladder", "Comp authority: cashier up to $5.00 (a free remake counts), shift lead up to $15.00, manager over $15.00."),
 ("SOP-250", 5, "fig-250-escalation", "Upset or unsafe guest: 1 stay calm and listen, 2 get the shift lead, 3 if it is unsafe, call 911. Never raise your voice, and you may step away at any time."),
 ("SOP-250", 6, "fig-250-lost-found", "Lost and found: bag the item and tag it with the date and where it was found, put it on the shelf in the back office, keep it 30 days, then the manager disposes of it. Phones, wallets, and keys go to the shift lead and into the safe."),
 # ---- SOP-260
 ("SOP-260", 2, "fig-260-floorplan", "Café floor plan: back of house in the back left (dish sink, walk-in, office); counter along the back wall with the register, the espresso bar, and the condiment bar; four tables in the seating area; the restroom at the front right; the front door at the center of the front wall."),
 ("SOP-260", 4, "fig-260-lobby-cycle", "Lobby check every 30 minutes: 1 tables wiped and chairs in place, 2 trash emptied when 3/4 full, 3 restroom checked and log signed, 4 condiment bar restocked."),
 ("SOP-260", 5, "fig-260-table-reset", "Table reset: 1 clear cups and trash, 2 wipe with the cloth from the sanitizer bucket (200 to 400 ppm), 3 let it air dry, 4 push the chairs in."),
 ("SOP-260", 6, "fig-260-closing-timeline", "Front of house closing: last call 7:45 PM, doors locked 8:00 PM, all closing tasks done by 8:45 PM."),
 # ---- SOP-270
 ("SOP-270", 2, "fig-270-schedule", "Cleaning schedule: daily is backflush, steam wand, and the grinder burr chamber. Weekly is the Sunday grinder deep clean, the Sunday batch brewer cycle, and the Wednesday fridge shelves. Monthly is the ice machine on the first Monday."),
 ("SOP-270", 3, "fig-270-ice-machine", "Ice machine, monthly: 1 turn off and dump all ice, 2 add the approved ice machine cleaner, 3 run the clean cycle for 20 minutes, 4 rinse with clear water, 5 sanitize with quat at 200 to 400 ppm, 6 restart and throw away the first batch of ice."),
 ("SOP-270", 4, "fig-270-brewer", "Batch brewer, Sunday: 1 dump the coffee and rinse the carafe, 2 run a cycle with brewer cleaner, 3 run a cycle with plain water, 4 wipe the spray head. Rinse the carafe and basket daily."),
 ("SOP-270", 5, "fig-270-blender", "Blender wash after every use: 1 rinse the jar, 2 warm water and soap and blend for 10 seconds, 3 rinse clean, 4 sanitize for 60 seconds and air dry."),
 ("SOP-270", 6, "fig-270-grinder", "Grinder: check the bean hopper and purge a few grams, brush out the burr chamber every day, and clean the portafilter fork. Deep clean every Sunday at close."),
 # ---- SOP-280
 ("SOP-280", 2, "fig-280-delivery-week", "Delivery week: pastries every day before 6:00 AM, milk and dairy Monday and Thursday 6:30 to 8:00 AM, dry goods, cups, and lids on Wednesday, inventory count Sunday at close."),
 ("SOP-280", 3, "fig-280-receiving-flow", "Receiving: count against the invoice, probe the dairy. If it is 41°F or below, put it away right away first in, first out. If not, refuse it, note it on the invoice, and tell the manager."),
 ("SOP-280", 4, "fig-280-fifo", "First in, first out: take from the front (oldest), and put new stock behind. Label every item with its date."),
 ("SOP-280", 5, "fig-280-par", "Par levels and reorder points: whole milk 8 gallons, reorder at 3. Oat milk 12 cartons, reorder at 4. Espresso beans 20 lb, reorder at 8. 16 oz hot cups 6 sleeves, reorder at 2. Mocha sauce 6 bottles, reorder at 2."),
 ("SOP-280", 7, "fig-280-waste-log", "Waste log columns: date, item, quantity, reason, initials. Write down everything you throw away."),
 # ---- SOP-290
 ("SOP-290", 2, "fig-290-where", "Where things are: first aid kit under the back counter by the dish sink, fire extinguisher on the wall by the back door, allergen binder in the drawer under the register, spare paper rolls in the cabinet under the register."),
 ("SOP-290", 3, "fig-290-burn", "Burns: 1 cool under cool running water, 2 for at least 10 minutes, 3 tell the shift lead, 4 report to the manager the same day. Large or severe burns: call 911."),
 ("SOP-290", 5, "fig-290-spill", "Spills: 1 put out the yellow wet-floor sign, 2 wipe up, 3 dry the floor, 4 remove the sign only when the floor is dry. Broken glass: sweep with a dustpan, never by hand."),
 ("SOP-290", 6, "fig-290-pass", "Fire extinguisher P.A.S.S.: Pull the pin, Aim at the base of the fire, Squeeze the handle, Sweep side to side. The extinguisher is on the wall by the back door. If the fire is too big, leave, call 911, and meet at the parking lot corner."),
 ("SOP-290", 6, "fig-290-evac", "Fire evacuation: leave through the front door or the back door and meet at the parking lot corner. Call 911 from outside."),
 ("SOP-290", 7, "fig-290-power", "Power outage: 1 tell the shift lead and call the manager, 2 cash only and write orders on paper, 3 keep fridge doors closed, 4 if over 30 minutes the manager decides whether to close. Dairy above 41°F for over 4 hours is discarded."),
 # ---- SOP-300
 ("SOP-300", 4, "fig-300-time-off", "Time off: submit in the schedule app at least 14 days ahead, the manager answers within 7 days, and approved time off appears on the schedule. Sick or emergency: call the manager at least 2 hours before your shift."),
 ("SOP-300", 5, "fig-300-shift-swap", "Shift swap: 1 ask a teammate, 2 both agree in the schedule app, 3 the manager approves at least 24 hours before the shift, 4 the schedule updates."),
 ("SOP-300", 6, "fig-300-breaks", "Breaks on an 8-hour shift: two 10-minute paid breaks and one 30-minute unpaid meal break. One 10-minute paid break for every 4 hours; a 30-minute unpaid meal break if the shift is over 5 hours."),
 ("SOP-300", 7, "fig-300-uniform", "Uniform check: hair tied back or a cap, name tag, a clean Ember & Oak apron, black pants, and closed, non-slip shoes."),
 ("SOP-300", 8, "fig-300-training", "Training path: shifts 1 to 3 shadow a trainer, shifts 4 to 10 work with a buddy, and the manager checks in at days 30, 60, and 90."),
]


def apply():
    ids = set(lib.FIGS)
    mapped = {m[2] for m in MAP}
    assert ids == mapped, (ids ^ mapped)
    # group by sop
    by = {}
    for sop, parent, fid, cap in MAP:
        by.setdefault(sop, []).append((parent, fid, cap))
    for sop, items in by.items():
        path = os.path.join(CORPUS, sop + "-C.md")
        lines = open(path).read().split("\n")
        text = "\n".join(lines)
        for parent, fid, cap in items:
            if fid in text:
                continue
            lines = text.split("\n")
            start = next(i for i, l in enumerate(lines) if re.match(rf"^## {parent} ", l))
            end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
            last = max(int(re.match(rf"^### {parent}\.(\d+) ", l).group(1)) for l in lines[start:end] if re.match(rf"^### {parent}\.\d+ ", l))
            n = last + 1
            title = lib.FIGS[fid][0]
            block = ["", f"### {parent}.{n} Diagram - {title}", f"![Figure {parent}.{n} - {title}](figures/png/{fid}.png)",
                     f"Figure {parent}.{n} shows: {cap}"]
            # strip trailing blanks inside group, then insert
            ins = end
            while ins > start and lines[ins - 1].strip() == "":
                ins -= 1
            lines[ins:ins] = block
            if ins == len(lines) - len(block):
                pass
            text = "\n".join(lines)
        text = text.rstrip("\n") + "\n"
        # ensure blank line before each '## ' heading
        text = re.sub(r"([^\n])\n(## )", r"\1\n\n\2", text)
        open(path, "w").write(text)
    print("applied", len(MAP), "figures")


if __name__ == "__main__":
    apply()
