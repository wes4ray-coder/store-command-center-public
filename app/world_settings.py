"""
The Company — settings & real-world rules.

A thin, typed layer over the store's existing `settings` table (all keys prefixed
`world_`). Holds the LLM schedule (so the model runs on a cadence, not 24/7) and the
guardrails that keep agents realistic — no free items, price floors, sane discounts,
no auto-posting AI junk. Read via `get_all` / typed helpers; write via `save`.
"""
from deps import get_conn

DEFAULTS = {
    # cognition schedule — the crew "wakes up" to think/opine on this cadence
    "world_llm_enabled":      "1",
    "world_llm_interval_min": "60",     # load a model at most ~once/hour
    "world_active_start":     "7",      # cognition only runs between these hours…
    "world_active_end":       "23",     # …(24h clock; wrap not supported — keep start<end)
    # governance
    "world_meetings_enabled": "1",
    "world_incidents_enabled": "1",
    "world_meeting_interval_min": "60",
    # real-world economic rules (guardrails)
    "world_min_item_cost":    "30",     # a prop/item can never be cheaper than this
    "world_allow_free":       "0",      # agents may NOT make things free
    "world_min_price_cents":  "500",    # store product price floor ($5.00)
    "world_max_discount_pct": "40",     # no unrealistic fire-sales
    "world_require_review":   "1",      # nothing auto-posts without review (no AI-junk dumps)
    # the world-builder's "eyes" — a vision model reviews each generated sprite and
    # keeps the best of N (and retries if poor). See world_vision.VISION_MODELS.
    "world_vision_enabled":   "1",
    "world_vision_candidates": "2",     # sprites to generate, then vision-pick the best
    "world_vision_retries":   "1",      # extra feedback-guided retry rounds if all poor
    "world_vision_min_score": "7",      # 1-10; below this triggers a retry
    "world_vision_model":     "google/gemma-4-12b-qat",   # fallback VLM if none resident (Gemma 4 is multimodal)
    # JellyCoin: skilling (woodcutting/mining/fishing/…) queues boost tickets that pay
    # out ONLY inside real GPU-mined blocks (jellycoin.py). Off by default — god's call.
    "world_crypto_mining_enabled": "0",
    # production BILLS (world_bills): whether an active bill may kick a REAL
    # world_auto creation (all its gates still apply), and how often at most.
    "world_bills_drive":      "0",
    "world_bills_drive_interval_min": "30",
    # music: agents may write their OWN lyrics and record a full vocal song via
    # ACE-Step (when installed on the GPU node) instead of a short instrumental.
    "world_music_lyrics":     "1",
    # leaders: Mayor/Boss file REAL dev-swarm upgrade jobs from the company fund
    # (charged only when you APPROVE the job in the Dev Swarm tab).
    "world_leader_upgrades":  "1",
    "world_leader_upgrade_hours": "12",
    # world
    "world_theme":            "futuristic",
    # play-god MAP EDITS: auto-persist hand edits (move/resize/add/delete buildings,
    # decor, work nodes, landmarks) shortly after each change so they survive a
    # tab-flip/reload/restart. ON by default; off → only the 💾 Save button persists.
    "world_layout_autosave":  "1",
    # per-entity sprite sheets (world_sprites): on-demand "this entity doing this
    # action" sheet generation — need-triggered (a frontend cache-miss), pack-
    # library-first, transparency+QA gated, budget-capped. The AUTO cadence
    # (slow background backfill) is a separate toggle, OFF by default.
    "world_sprites_enabled":  "1",
    "world_sprites_max_hour": "6",      # generated sheets per rolling hour, max
    "world_sprites_auto":     "0",
    "world_sprites_auto_min": "240",
    # progressive tileset painting: agents slowly replace ONE procedural terrain
    # tile at a time (QA + style-gated; world_tileset.auto_tick). Off by default.
    "world_tileset_auto":     "0",
    "world_tileset_auto_min": "180",
    # Layer 2: one big generated whole-world terrain IMAGE drawn as the ground
    # (terrain LOGIC stays on the grid). OFF by default — procedural terrain
    # shows until this is on AND an image has been generated (world_terrain.py).
    "world_terrain_image_enabled": "0",
    # Layer 2b: ONE shared generated interior-floor texture blitted under every
    # building interior (tinted per kind so buildings still read distinct). OFF by
    # default — the procedural per-kind tint floor shows until this is on AND a
    # floor image has been generated (world_floors.py).
    "world_floor_image_enabled": "0",
    # pixel-art sprite generation — the model+LoRA the world-builder renders with.
    # empty model = the store's default image model. LoRA format "file:strength"
    # (must exist in the ComfyUI loras dir on the GPU box).
    "world_prop_model":       "",
    "world_prop_lora":        "pixel-art-xl.safetensors:0.9",
    # background-removal (matte) model that cuts world props/sprites out to a
    # transparent PNG in the ComfyUI workflow (generate.sh arg 10). Empty =
    # auto-detect whatever bg-removal model is installed on the box (e.g.
    # birefnet.safetensors); "off" = disable and rely on the flood-fill knockout.
    "world_prop_matte":       "",
    # ROOF CUTAWAY: camera-zoom scale at which roofs START fading to reveal interiors
    # (fade completes ~0.4x above it). Lower = interiors reveal sooner / further out.
    # Default 1.15 (was a hard-coded 2.4 that forced you to zoom almost fully in).
    "world_roof_fade_zoom":   "1.15",
    # night darkness of the world view: 1 = default readable night, lower = darker,
    # 0 = brightest (surfaced as window._wmNightBright in the renderer).
    "world_night_brightness": "1",
    # MOON: the drifting moon + its ground shadow (world-sky.js). On by default (a sky
    # object, night-gated). world_moon_daytime shows it in daylight too (a preview so you
    # don't have to wait for sim-night). A generated texture (world_moon.py) swaps into
    # the procedural cratered disc when present.
    "world_moon_enabled":     "1",
    "world_moon_daytime":     "0",
    # SPACE PROGRAM (JASA): a decoupled overlay that launches finance/crypto/research
    # agents to the Moon and flies them home (world_space.py). Purely cosmetic — the
    # town roster is untouched. ON by default; interval is the launch cadence.
    "world_space_enabled":    "1",
    "world_space_interval_min": "8",
}

INT_KEYS = {"world_llm_interval_min", "world_active_start", "world_active_end",
            "world_meeting_interval_min", "world_min_item_cost", "world_min_price_cents",
            "world_max_discount_pct", "world_vision_candidates", "world_vision_retries",
            "world_vision_min_score", "world_bills_drive_interval_min",
            "world_leader_upgrade_hours", "world_tileset_auto_min",
            "world_space_interval_min", "world_sprites_max_hour", "world_sprites_auto_min"}
BOOL_KEYS = {"world_llm_enabled", "world_meetings_enabled", "world_incidents_enabled",
             "world_allow_free", "world_require_review", "world_vision_enabled",
             "world_crypto_mining_enabled", "world_bills_drive", "world_music_lyrics",
             "world_leader_upgrades", "world_tileset_auto", "world_terrain_image_enabled",
             "world_floor_image_enabled", "world_layout_autosave",
             "world_moon_enabled", "world_moon_daytime", "world_space_enabled",
             "world_sprites_enabled", "world_sprites_auto"}


def get_all(conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        rows = {r["key"]: r["value"] for r in
                conn.execute("SELECT key,value FROM settings WHERE key LIKE 'world\\_%' ESCAPE '\\'").fetchall()}
    except Exception:
        rows = {}
    finally:
        if own:
            conn.close()
    out = dict(DEFAULTS)
    out.update(rows)
    return out


def i(key, conn=None):
    try: return int(float(get_all(conn).get(key, DEFAULTS.get(key, "0"))))
    except Exception: return int(float(DEFAULTS.get(key, "0")))

def b(key, conn=None):
    return str(get_all(conn).get(key, DEFAULTS.get(key, "0"))) in ("1", "true", "True", "on")


def s(key, conn=None):
    return str(get_all(conn).get(key, DEFAULTS.get(key, "")) or "")


def save(updates: dict, conn=None):
    """Persist a subset of world settings (only known keys)."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        for k, v in updates.items():
            if not k.startswith("world_") or k not in DEFAULTS:
                continue
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, str(v)))
        conn.commit()
    finally:
        if own:
            conn.close()


def cognition_allowed(conn=None):
    """True if the crew is allowed to run the model right now (enabled + active hours)."""
    import time
    if not b("world_llm_enabled", conn):
        return False
    hour = int(time.strftime("%H"))
    start, end = i("world_active_start", conn), i("world_active_end", conn)
    return start <= hour < end if start < end else True
