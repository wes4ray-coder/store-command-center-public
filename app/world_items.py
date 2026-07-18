"""
The Company — items, inventory & the in-game general store.

Agents earn coins from REAL platform work; this module gives those coins
somewhere to go, RimWorld/Sims style:

  • a store CATALOG of sized items — small / medium / large — across food,
    house furniture and yard pieces
  • per-agent INVENTORY (`world_inventory`): what they're carrying
  • house/yard PLACEMENT slots (`world_placements`): furniture they buy is
    placed at their home and STAYS there (drawn by the frontend)
  • CONSUMABLES: hungry agents walk to a shop, buy groceries, and eat them —
    eating consumes the item and restores needs

Money loop: every purchase pays the price back into the company fund, so coins
circulate (work → wages → shop → company) instead of only piling up.
Integration is one call — `tick_agent(c, a, now)` from world_sim's per-agent
loop; it may override the agent's state/location for a short shop trip.
"""
import random
import logging

logger = logging.getLogger("store")

# ── the catalog ───────────────────────────────────────────────────────────────
# size: s(mall) / m(edium) / l(arge) — drives price band + drawn footprint.
# spot: food (inventory, consumed) | house | yard (placed permanently).
CATALOG = {
    # food (small consumables — bought on shop trips, eaten when hungry)
    "bread":     {"name": "bread",          "emoji": "🍞", "size": "s", "price": 8,   "spot": "food", "eff": {"hunger": 30}},
    "coffee":    {"name": "coffee",         "emoji": "☕", "size": "s", "price": 6,   "spot": "food", "eff": {"energy": 18, "hunger": 6}},
    "stew":      {"name": "hearty stew",    "emoji": "🍲", "size": "s", "price": 14,  "spot": "food", "eff": {"hunger": 48}},
    "cake":      {"name": "slice of cake",  "emoji": "🍰", "size": "s", "price": 16,  "spot": "food", "eff": {"hunger": 22, "fun": 12}},
    "apple":     {"name": "apple",          "emoji": "🍎", "size": "s", "price": 5,   "spot": "food", "eff": {"hunger": 16}},
    # supplied by HUNTERS — only on the shelf while the stockpile holds venison
    "venison":   {"name": "venison roast",  "emoji": "🍖", "size": "s", "price": 18,  "spot": "food", "eff": {"hunger": 55, "fun": 6}, "stock": "venison"},
    # house furniture
    "book":      {"name": "novel",          "emoji": "📕", "size": "s", "price": 24,  "spot": "house"},
    "houseplant": {"name": "houseplant",    "emoji": "🪴", "size": "s", "price": 30,  "spot": "house"},
    "bookshelf": {"name": "bookshelf",      "emoji": "📚", "size": "m", "price": 70,  "spot": "house"},
    "armchair":  {"name": "armchair",       "emoji": "🛋️", "size": "m", "price": 80,  "spot": "house"},
    "tv":        {"name": "television",     "emoji": "📺", "size": "m", "price": 110, "spot": "house"},
    "piano":     {"name": "piano",          "emoji": "🎹", "size": "l", "price": 180, "spot": "house"},
    "bathtub":   {"name": "bathtub",        "emoji": "🛁", "size": "l", "price": 140, "spot": "house"},
    # yard pieces
    "flowerbed": {"name": "flower bed",     "emoji": "🌷", "size": "s", "price": 35,  "spot": "yard"},
    "lantern":   {"name": "yard lantern",   "emoji": "🏮", "size": "s", "price": 30,  "spot": "yard"},
    "bench":     {"name": "garden bench",   "emoji": "🪑", "size": "m", "price": 55,  "spot": "yard"},
    "grill":     {"name": "barbecue grill", "emoji": "🍖", "size": "m", "price": 85,  "spot": "yard"},
    "statue":    {"name": "lawn statue",    "emoji": "🗿", "size": "l", "price": 160, "spot": "yard"},
    "fountain":  {"name": "yard fountain",  "emoji": "⛲", "size": "l", "price": 220, "spot": "yard"},
}
FOODS = [k for k, v in CATALOG.items() if v["spot"] == "food"]
HOUSE_SLOTS = 4                    # max placed pieces inside a house
YARD_SLOTS = 3                     # max placed pieces in the yard

HUNGRY_EAT = 45                    # eat something below this hunger
HUNGRY_SHOP = 55                   # plan a grocery run below this (when out of food)
SHOP_TRIP_SEC = 22                 # how long the walk-and-buy takes
FURNISH_MIN_COINS = 110            # only shop for furniture with a cushion left over
FURNISH_CHANCE = 0.002             # per tick (~1 purchase every few hours per agent)
_INTERRUPTIBLE = ("leisure", "idle", "skilling", "studying", "praying")

_trips = {}                        # agent_key -> completion timestamp (in-flight shop runs)
_ensured = False


def ensure(c):
    global _ensured
    if _ensured:
        return
    c.executescript("""
    CREATE TABLE IF NOT EXISTS world_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_key TEXT NOT NULL,
        item TEXT NOT NULL,
        qty INTEGER DEFAULT 1,
        acquired_at TEXT DEFAULT (datetime('now')),
        UNIQUE(agent_key, item)
    );
    CREATE TABLE IF NOT EXISTS world_placements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_key TEXT NOT NULL,
        item TEXT NOT NULL,
        spot TEXT NOT NULL,          -- house | yard
        slot INTEGER NOT NULL,
        placed_at TEXT DEFAULT (datetime('now')),
        UNIQUE(agent_key, spot, slot)
    );
    """)
    # movable placements: a saved world-pixel override set by the play-god
    # editor (NULL = the default computed slot position)
    for col in ("ox REAL", "oy REAL"):
        try:
            c.execute(f"ALTER TABLE world_placements ADD COLUMN {col}")
        except Exception:
            pass
    _ensured = True


# ── inventory helpers ─────────────────────────────────────────────────────────
def _add(c, key, item, qty=1):
    c.execute("INSERT INTO world_inventory (agent_key,item,qty) VALUES (?,?,?) "
              "ON CONFLICT(agent_key,item) DO UPDATE SET qty=qty+?", (key, item, qty, qty))


def _consume(c, key, item):
    c.execute("UPDATE world_inventory SET qty=qty-1 WHERE agent_key=? AND item=?", (key, item))
    c.execute("DELETE FROM world_inventory WHERE agent_key=? AND item=? AND qty<=0", (key, item))


def inventory_for(c, key):
    ensure(c)
    out = []
    for r in c.execute("SELECT item, qty FROM world_inventory WHERE agent_key=? ORDER BY item", (key,)):
        it = CATALOG.get(r["item"])
        if it:
            out.append({"item": r["item"], "name": it["name"], "emoji": it["emoji"],
                        "size": it["size"], "qty": r["qty"]})
    return out


def placements(c):
    ensure(c)
    out = []
    for r in c.execute("SELECT agent_key, item, spot, slot, ox, oy FROM world_placements ORDER BY agent_key, spot, slot"):
        it = CATALOG.get(r["item"])
        if it:
            out.append({"agent_key": r["agent_key"], "item": r["item"], "emoji": it["emoji"],
                        "size": it["size"], "spot": r["spot"], "slot": r["slot"],
                        "ox": r["ox"], "oy": r["oy"]})
    return out


def move_placement(c, agent_key, spot, slot, ox, oy):
    """Play-god editor: pin a placed piece at an exact world-pixel point
    (ox/oy None resets it to its default slot position)."""
    ensure(c)
    c.execute("UPDATE world_placements SET ox=?, oy=? WHERE agent_key=? AND spot=? AND slot=?",
              (ox, oy, agent_key, spot, slot))
    return c.rowcount > 0


# ── the economy loop ──────────────────────────────────────────────────────────
def _fund_credit(c, amount):
    """Purchases pay the store — money returns to the company fund."""
    from world_defs import mget, mset
    mset(c, "company_fund", int(float(mget(c, "company_fund", 0) or 0)) + int(amount))


def _clamp(v):
    return max(0, min(100, v))


def _eat(c, a):
    """Eat the most filling food carried. Returns True if something was eaten."""
    rows = c.execute("SELECT item FROM world_inventory WHERE agent_key=? AND qty>0", (a["key"],)).fetchall()
    foods = [r["item"] for r in rows if CATALOG.get(r["item"], {}).get("spot") == "food"]
    if not foods:
        return False
    item = max(foods, key=lambda k: CATALOG[k]["eff"].get("hunger", 0))
    it = CATALOG[item]
    for need, gain in it["eff"].items():
        a[need] = _clamp((a[need] or 0) + gain)
    _consume(c, a["key"], item)
    try:
        from world_defs import log_agent
        log_agent(a["key"], a["name"], f"Ate {it['name']} {it['emoji']} (+{it['eff'].get('hunger', 0)} hunger).")
        import world_mood
        world_mood.add_thought(c, a["key"], "ate a good meal", 4, hours=4, unique=True)
    except Exception:
        pass
    return True


def _buy_groceries(c, a):
    """Complete a shop trip: buy 2-3 random affordable foods. Stock-backed items
    (venison from the hunters) are only on the shelf while the stockpile has
    them — buying one CONSUMES real stockpile, closing the hunt→food loop."""
    import world_skills as _ws
    bought = []
    for _ in range(random.randint(2, 3)):
        affordable = []
        for k in FOODS:
            it = CATALOG[k]
            if it["price"] > (a["coins"] or 0):
                continue
            if it.get("stock") and not _ws.can_afford(c, {it["stock"]: 1}):
                continue                                   # hunters haven't supplied any
            affordable.append(k)
        if not affordable:
            break
        item = random.choice(affordable)
        it = CATALOG[item]
        if it.get("stock"):
            _ws.spend(c, {it["stock"]: 1})                 # the shelf empties for real
        a["coins"] = (a["coins"] or 0) - it["price"]
        _fund_credit(c, it["price"])
        _add(c, a["key"], item)
        bought.append(it["emoji"])
    if bought:
        try:
            from world_defs import log_agent
            log_agent(a["key"], a["name"], f"Bought groceries: {''.join(bought)}.")
        except Exception:
            pass
    return bool(bought)


def _free_slot(c, key, spot):
    cap = HOUSE_SLOTS if spot == "house" else YARD_SLOTS
    used = {r["slot"] for r in c.execute(
        "SELECT slot FROM world_placements WHERE agent_key=? AND spot=?", (key, spot))}
    for i in range(cap):
        if i not in used:
            return i
    return None


def _maybe_furnish(c, a):
    """Occasionally spend a comfortable surplus on a furniture/yard piece."""
    try:                                       # savers vs shoppers — genome-scaled roll
        import world_genome
        _spend = world_genome.genome(a)["spend"]
    except Exception:
        _spend = 1.0
    if (a["coins"] or 0) < FURNISH_MIN_COINS or random.random() > FURNISH_CHANCE * _spend:
        return
    for spot in random.sample(["house", "yard"], 2):
        slot = _free_slot(c, a["key"], spot)
        if slot is None:
            continue
        owned = {r["item"] for r in c.execute(
            "SELECT item FROM world_placements WHERE agent_key=?", (a["key"],))}
        budget = (a["coins"] or 0) - 60                       # keep a living cushion
        options = [k for k, v in CATALOG.items()
                   if v["spot"] == spot and v["price"] <= budget and k not in owned]
        if not options:
            continue
        # lean toward the nicest they can afford, with personal taste (top 3 shuffled)
        options.sort(key=lambda k: -CATALOG[k]["price"])
        item = random.choice(options[:3])
        it = CATALOG[item]
        a["coins"] -= it["price"]
        _fund_credit(c, it["price"])
        c.execute("INSERT OR IGNORE INTO world_placements (agent_key,item,spot,slot) VALUES (?,?,?,?)",
                  (a["key"], item, spot, slot))
        try:
            from world_defs import log_agent, log_town
            log_agent(a["key"], a["name"], f"Bought a {it['name']} {it['emoji']} for the {spot} ({it['price']}🪙).")
            if it["size"] == "l":                              # big purchases make the town feed
                log_town(f"🛍️ {a['name']} bought a {it['name']} {it['emoji']} for their {spot}!")
            import world_mood
            world_mood.add_thought(c, a["key"], f"new {it['name']} at home", 6, hours=12, unique=True)
        except Exception:
            pass
        return


def tick_agent(c, a, now):
    """Per-agent economy tick, called from world_sim.simulate after the state is
    chosen. May override the state with a short shopping trip. Never touches
    working/defending/sleeping agents."""
    ensure(c)

    # 1) in-flight shop trip?
    trip = _trips.get(a["key"])
    if trip:
        if now >= trip:
            del _trips[a["key"]]
            _buy_groceries(c, a)
            if (a["hunger"] or 0) < HUNGRY_EAT:
                _eat(c, a)
        else:
            a["state"], a["location"], a["goal"] = "shopping", "shop", "buying groceries"
            return

    # 2) hungry + carrying food → just eat (anywhere)
    if (a["hunger"] or 0) < HUNGRY_EAT and _eat(c, a):
        return

    # 3) hungry, no food, can afford it, not busy → start a grocery run
    cheapest = min(CATALOG[k]["price"] for k in FOODS)
    if ((a["hunger"] or 0) < HUNGRY_SHOP and (a["coins"] or 0) >= cheapest
            and a.get("state") in _INTERRUPTIBLE):
        _trips[a["key"]] = now + SHOP_TRIP_SEC
        a["state"], a["location"], a["goal"] = "shopping", "shop", "heading to the store"
        return

    # 4) comfortable surplus → maybe furnish the house/yard
    if a.get("state") in _INTERRUPTIBLE:
        _maybe_furnish(c, a)
        # …or, rarely, commission a pixel-art piece of their OWN (paid for with
        # their coins; all GPU guards live inside personal_create)
        if random.random() < 0.001 and (a["fulfillment"] or 0) > 55:
            try:
                import world_build
                world_build.personal_create(c, a)
            except Exception:
                pass
        # …or treat themselves to a custom LOOK (their own face in the world)
        if random.random() < 0.0006 and (a["coins"] or 0) >= 120 and not a.get("sprite_path"):
            try:
                import world_build
                world_build.agent_makeover(c, a)
            except Exception:
                pass
