"""
The Company — balance & content registries (the single tuning surface).

Every number that controls how the world *feels* lives here, plus the data-driven
registries (achievements, incidents) that let new content be added without touching
engine code. To add a milestone or a random event, append a dict below — the engine
picks it up automatically. Keep behaviour (how) in the engine modules; keep balance
(how much) and content (what) here.
"""

# ── economy ───────────────────────────────────────────────────────────────────
WAGE_PER_JOB   = 12        # coins for one real completed job (× earn_mult)
XP_PER_JOB     = 15
RENT           = 16
BILLS          = 8
BILL_CYCLE_SEC = 480       # 8 real minutes = one "billing day"
COMPANY_TAX    = 0.10      # fraction of each wage skimmed into the company treasury

# ── simulation tick ───────────────────────────────────────────────────────────
TICK_INTERVAL_SEC = 8      # background ticker cadence
DT_CAP            = 120     # ignore gaps longer than this (server was asleep)
OPINION_EVERY_SEC = 120     # a fresh agent opinion at most this often
MEETING_EVERY_SEC = 900     # auto town meeting cadence
INCIDENT_EVERY_SEC = 360    # a random incident at most this often
EVENTS_RETENTION  = 600     # keep only the newest N rows in world_events

# ── needs decay / restore (points per minute) ────────────────────────────────
NEED_DECAY = {"hunger": 2.2, "fun": 1.8, "social": 1.6}
WORK_ENERGY_DRAIN = 3.2
WORK_FULFILL_GAIN = 2.0
WORK_FUN_DRAIN = 1.3          # company work is a grind — fun sags on shift (god lifts, work drains)

# ── the FLUX system: monotony punishes grinding, balance pays, god lifts ──────
MONOTONY_GRACE_SEC = 1500     # ~25 min of one activity before boredom sets in
MONOTONY_SLOPE = 0.0006       # productivity lost per second past the grace period
MONOTONY_FLOOR = 0.35         # output never drops below 35% (they still function)
THRIVE_GREEN = 68             # EVERY need at/above this → "thriving"
THRIVE_MULT = 1.25            # thriving bonus on pay + xp (all-green is the max-reward state)
BLESS_BUFF_SEC = 3600         # a blessing from god buffs the creator for an hour
BLESS_MULT = 1.25             # blessed bonus on pay + xp
BLESS_NEED_LIFT = 25          # blessing restores every need by this much (toward green)
IDLE_ENERGY_DRAIN = 0.8
IDLE_FULFILL_DRAIN = 2.4
PLACE_RESTORE = {   # location → {need: per-minute gain}
    "home":   {"energy": 7.5},   # snappier recovery — less of the day lost parked in bed
    "cafe":   {"hunger": 7.0, "social": 3.0},
    "bar":    {"social": 6.0, "fun": 3.0},
    "arcade": {"fun": 7.0},
    "tv":     {"fun": 4.0, "energy": 2.0},
    "park":   {"fun": 2.0, "social": 2.0},
    "church": {"fulfillment": 6.0, "social": 3.0, "fun": 1.5},   # spiritual calm restores purpose/morale
    "library":{"fulfillment": 2.0},                              # studying is quietly fulfilling
}

# System B — Library/Knowledge: each Knowledge level makes an agent better at their
# real job (higher pay + XP per completed job). "Studying to do stuff better."
KNOWLEDGE_WAGE_FACTOR = 0.03    # +3% wage & xp on real work per Knowledge level

# ── company milestones (data-driven; checked each tick) ────────────────────────
# `check` receives a summary dict (see world_systems._summary): total_jobs, treasury,
# total_debt, pop, props_done, upgrades, meetings, max_level, thriving.
ACHIEVEMENTS = [
    {"id": "first_job",    "label": "First Paycheck 💵",  "desc": "Someone completed their first real job.",
     "check": lambda s: s["total_jobs"] >= 1},
    {"id": "jobs_25",      "label": "Getting Busy ⚙️",    "desc": "25 jobs completed company-wide.",
     "check": lambda s: s["total_jobs"] >= 25},
    {"id": "jobs_100",     "label": "Production Line 🏭",  "desc": "100 jobs completed company-wide.",
     "check": lambda s: s["total_jobs"] >= 100},
    {"id": "treasury_500", "label": "Nest Egg 🥚",        "desc": "Company treasury reached 500 🪙.",
     "check": lambda s: s["treasury"] >= 500},
    {"id": "treasury_2000","label": "War Chest 💰",        "desc": "Company treasury reached 2000 🪙.",
     "check": lambda s: s["treasury"] >= 2000},
    {"id": "debt_free",    "label": "In the Black 📈",     "desc": "Nobody in the company is in debt.",
     "check": lambda s: s["pop"] > 0 and s["total_debt"] == 0},
    {"id": "furnished",    "label": "Home Sweet Office 🪑","desc": "10 props built in the world.",
     "check": lambda s: s["props_done"] >= 10},
    {"id": "tooled_up",    "label": "Tooled Up 🛠️",       "desc": "5 upgrades purchased across the crew.",
     "check": lambda s: s["upgrades"] >= 5},
    {"id": "democracy",    "label": "Democracy 🏛️",       "desc": "The town held its first meeting.",
     "check": lambda s: s["meetings"] >= 1},
    {"id": "veteran",      "label": "Seasoned Pro 🎖️",    "desc": "An agent reached level 10.",
     "check": lambda s: s["max_level"] >= 10},
    {"id": "thriving_town","label": "Boom Town 🎉",        "desc": "Half the crew is thriving at once.",
     "check": lambda s: s["pop"] > 0 and s["thriving"] * 2 >= s["pop"]},
]

# ── random incidents (data-driven; one fires occasionally) ─────────────────────
# effect ops (applied by world_systems): {"need": name, "delta": n, "scope": "all"|dept}
#                                          {"coins": n, "scope": "all"|dept}
INCIDENTS = [
    {"id": "coffee",  "text": "☕ Fresh coffee delivery lifts everyone's spirits!",
     "effects": [{"need": "fun", "delta": 12, "scope": "all"}, {"need": "energy", "delta": 8, "scope": "all"}]},
    {"id": "viral",   "text": "🚀 A listing went viral — the Storefront cashes in!",
     "effects": [{"coins": 40, "scope": "storefront"}]},
    {"id": "outage",  "text": "🔌 Brief server hiccup — the Dev Lab is stressed.",
     "effects": [{"need": "energy", "delta": -14, "scope": "devlab"}]},
    {"id": "potluck", "text": "🍲 Surprise office potluck — nobody's hungry now.",
     "effects": [{"need": "hunger", "delta": 25, "scope": "all"}]},
    {"id": "bonus",   "text": "🎁 Great sales week — a small bonus for everyone!",
     "effects": [{"coins": 15, "scope": "all"}]},
    {"id": "gremlin", "text": "🐛 A render gremlin frustrates the Image Studio.",
     "effects": [{"need": "fun", "delta": -12, "scope": "image"}]},
]
