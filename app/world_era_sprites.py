"""
THE COMPANY — per-CIVILIZATION-ERA generated building sprites.

``world_era.py`` gives every DEPARTMENT building a place on the 7-rung era ladder
(``wood → brick → metal → western → modern → futuristic → moon``) and the client
already restyles buildings procedurally per era. THIS module adds an OPTIONAL
layer on top: a real generated, transparent, top-down pixel-art building image
PER (building-type, era), which the frontend swaps in wherever one exists and
otherwise keeps the procedural restyle. Nothing here changes era LOGIC — it is a
pure cosmetic asset pipeline.

It does NOT open a second GPU path. Every render rides the EXISTING per-entity
sprite pipeline in ``world_sprites.py``:

  * one render at a time on the shared GPU (``world_sprites._gen_lock`` +
    ``orch.image_acquire``),
  * the SAME rolling-hour budget (``world_sprites_max_hour`` /
    ``world_sprites._hour_budget_ok`` / ``_hour_budget_spend``),
  * the SAME transparency (``alpha_ok``) + vision (``_qa``) gates,
  * installed through ``world_sprites.install_base`` so the sprite lands in the
    normal entity registry / manifest / ``/api/world/sprites`` index and is served
    at ``static/world_assets/entities/<id>/…`` — made ONCE, cached forever.

CONTRACT (what the frontend draws):
  entity id = ``era_<type>_<eraName>`` where
    * ``type``    = the building's ``loc`` (its department key) if it has one,
                    else its civic ``kind`` (house/shop/hq/church/library/…)
    * ``eraName`` ∈ ``world_era.ERAS`` (wood…moon)
  The sprite is installed as that entity's ``idle`` sheet, so the client draws it
  with ``WSP.drawStatic('era_'+type+'_'+eraName, 'idle', …)`` (drawStatic pins
  frame 0 — buildings don't bob). ``WSP.hasOwnLook('era_'+type+'_'+eraName)`` /
  the ``/api/world/sprites`` index tell it whether a sprite exists yet.

Gating: ``world_era_sprites_enabled`` (default "0" — OFF; it spends GPU). Every
public entry point is defended and never raises.

Import-safe: no DB / GPU / PIL work at import time.
"""
import json
import logging
import re
import threading
import time

from deps import get_conn, orch
from world_defs import mget
import world_defs as wd
import world_settings as ws
import world_sprites as wsp
from world_era import ERAS

log = logging.getLogger("world_era_sprites")

# ── era → material / style clause (the visual identity of each rung) ───────────
ERA_STYLE = {
    "wood":       "rustic timber log-cabin construction, wooden plank walls and shingle roof",
    "brick":      "sturdy red-brick masonry walls with a slate roof",
    "metal":      "riveted industrial steel and iron plating, corrugated metal roof, exposed pipes",
    "western":    "old-west false-front timber saloon, wooden porch, hanging sign, dusty boards",
    "modern":     "sleek glass-and-concrete architecture, flat roof, large clean windows",
    "futuristic": "sleek neon sci-fi architecture, glowing panels, chrome and holographic trim",
    "moon":       "white lunar dome base, solar panels, airlock doors, pale moonbase panels",
}

# ── building TYPE → what the building IS ───────────────────────────────────────
# Department keys (world_defs.DEPARTMENTS) describe the studio/desk; civic kinds
# describe standalone buildings. Any unknown type degrades to "a <type> building".
TYPE_DESC = {
    # departments
    "storefront": "a retail storefront shop with a display window",
    "image":      "an art and illustration studio",
    "video":      "a film and video production studio",
    "audio":      "a music recording studio",
    "models3d":   "a 3D-printing and sculpture workshop",
    "publishing": "a printing and publishing house",
    "devlab":     "a software engineering lab full of server racks",
    "resell":     "a reseller warehouse and shipping depot",
    "trends":     "a trend-forecasting office",
    "portal":     "a web-portal and media office",
    "social":     "a social-media broadcast studio",
    "finance":    "a bank and finance office with columns",
    "netsec":     "a network-security operations center",
    "research":   "a science research laboratory",
    "mail":       "a post office and mail room",
    "homelab":    "a home-server data closet building",
    "pearl":      "a gem and crystal mining outpost",
    "assistant":  "a robotics and AI-assistant office",
    # civic kinds
    "house":      "a small cozy family home",
    "shop":       "a small general store",
    "hq":         "a tall corporate headquarters tower",
    "church":     "a church with a tall steeple",
    "library":    "a public library",
    "townhall":   "a grand town hall with a clock tower",
    "bar":        "a tavern and bar",
    "cafe":       "a cozy cafe",
    "exec":       "an executive office building",
}

# civic (non-department) building kinds the frontend renders
CIVIC_KINDS = ["house", "shop", "hq", "church", "library", "townhall", "bar", "cafe", "exec"]


def all_types():
    """Every building TYPE we can make era sprites for: department keys + civic
    kinds. (List, deduped, stable order — departments first.)"""
    seen, out = set(), []
    for t in list(wd.DEPARTMENTS) + CIVIC_KINDS:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── id / prompt ────────────────────────────────────────────────────────────────
def _norm(x):
    return re.sub(r"[^a-z0-9_]", "", str(x or "").lower())


def _valid(type_, era):
    return bool(_norm(type_)) and _norm(era) in ERAS


def entity_id(type_, era):
    """The registry entity id for a (type, era) building sprite: era_<type>_<era>."""
    return f"era_{_norm(type_)}_{_norm(era)}"


def _prompt(type_, era):
    """An era-appropriate top-down pixel-art BUILDING prompt: the building TYPE
    rendered in the era's material/style, transparent, no characters/text —
    matched to the world_sprites prop knockout+QA discipline."""
    what = TYPE_DESC.get(_norm(type_), f"a {str(type_ or 'building').replace('_', ' ')} building")
    style = ERA_STYLE.get(_norm(era), str(era))
    p = (f"top-down orthographic view of {what}, {style}, "
         f"pixel-art game building sprite, 16-bit asset, flat solid colors, "
         f"bold dark outline, no gradients, no anti-aliasing, single centered building, "
         f"transparent background, no ground, no grass, no characters, no people, no text")
    # generate.sh embeds the prompt into a bash/python heredoc — strip the chars
    # that mangle it (same defense as world_terrain/world_floors _prompt).
    return re.sub(r"['\"\\`]", "", p)


# ── the reusable one-shot render (shared GPU lock + shared hourly budget) ──────
def _make(type_, era):
    """Render + install ONE era building sprite. Holds the shared world_sprites
    GPU lock (one render at a time on the shared card) and spends from the SHARED
    ``world_sprites_max_hour`` budget. Returns a status dict; never raises.

    Both ``request`` (lazy, one) and ``pre_seed`` (bulk, serial) funnel through
    here so there is exactly one gated, budget-capped GPU path."""
    if not _valid(type_, era):
        return {"ok": False, "reason": "bad type/era"}
    eid = entity_id(type_, era)
    if not wsp._gen_lock.acquire(blocking=False):
        return {"ok": False, "reason": "busy"}
    try:
        m = wsp.manifest(eid)
        if "idle" in (m.get("sheets") or {}):
            m.get("pending", {}).pop("idle", None)
            wsp._save_manifest(eid, m)
            return {"ok": True, "cached": True}
        if not wsp._hour_budget_ok():
            m.get("pending", {}).pop("idle", None)
            wsp._save_manifest(eid, m)
            return {"ok": False, "reason": "capped"}

        prompt = _prompt(type_, era)
        label = f"{_norm(type_).replace('_', ' ')} building, {era} era"
        d = wsp._dir(eid)
        d.mkdir(parents=True, exist_ok=True)
        raw = d / "_raw_era.png"
        sprite = None
        try:
            import world_build
            orch.image_acquire()
            try:
                for attempt in range(2):            # opaque/failed output → fresh-seed retry
                    if not wsp._render_sprite(prompt, raw, seed=None):
                        continue
                    cand = d / "_cand_era.png"
                    world_build._pixelate(raw, cand, cells=wsp.CELL, colors=28)
                    from PIL import Image
                    im = Image.open(cand).convert("RGBA")
                    try:
                        cand.unlink()
                    except Exception:
                        pass
                    if not wsp.alpha_ok(im):        # the picture-box gate (transparent surround)
                        log.warning("era sprite %s attempt %d: opaque/shredded — rejected",
                                    eid, attempt)
                        continue
                    sprite = im
                    break
            finally:
                orch.image_release()
        except Exception:
            log.exception("era sprite render %s failed", eid)
        finally:
            try:
                raw.unlink()
            except Exception:
                pass

        score = None
        if sprite is not None:
            tmp = d / "_qa_era.png"
            sprite.save(tmp)
            ok, score, issues = wsp._qa(tmp, label)
            try:
                tmp.unlink()
            except Exception:
                pass
            if not ok:
                log.warning("era sprite %s failed QA (%s: %s) — not installing", eid, score, issues)
                sprite = None

        if sprite is None:
            m = wsp.manifest(eid)
            m.get("pending", {}).pop("idle", None)
            wsp._save_manifest(eid, m)
            return {"ok": False, "reason": "no transparent/QA-passing render"}

        # install through the normal entity mechanism → shows in /api/world/sprites,
        # served at world_assets/entities/<eid>/idle.png, drawn via WSP.drawStatic.
        wsp.install_base(eid, sprite, prompt, score=score, actions=("idle",))
        wsp._hour_budget_spend()
        return {"ok": True, "source": "generated", "entity": eid}
    finally:
        wsp._gen_lock.release()


# ── lazy on-demand: get-or-enqueue ONE ─────────────────────────────────────────
def request(type_, era):
    """Resolve one (type, era) building sprite → ready / pending / queued, or a
    gated reason. Made once, cached forever. Respects the world_sprites budget +
    one-render-at-a-time discipline (never a second uncapped GPU path)."""
    try:
        if not _valid(type_, era):
            return {"status": "unavailable", "reason": "bad type/era"}
        eid = entity_id(type_, era)
        m = wsp.manifest(eid)
        meta = (m.get("sheets") or {}).get("idle")
        if meta:
            return {"status": "ready", "entity": eid, "url": wsp._url(eid, meta["file"]),
                    "frames": meta.get("frames", wsp.FRAMES),
                    "fw": meta.get("fw", wsp.CELL), "fh": meta.get("fh", wsp.CELL),
                    "source": meta.get("source", "generated")}
        if "idle" in (m.get("pending") or {}):
            return {"status": "pending", "entity": eid}
        if not ws.b("world_era_sprites_enabled"):
            return {"status": "disabled", "entity": eid}
        if not wsp._hour_budget_ok():
            return {"status": "capped", "entity": eid}
        if wsp._gen_lock.locked():
            return {"status": "busy", "entity": eid}
        m.setdefault("pending", {})["idle"] = time.time()
        wsp._save_manifest(eid, m)
        threading.Thread(target=_make, args=(type_, era), daemon=True).start()
        return {"status": "queued", "entity": eid}
    except Exception:
        log.exception("era sprite request failed for %s/%s", type_, era)
        return {"status": "unavailable", "reason": "error"}


# ── bulk pre-seed (owner button — generate ahead of a dry run, budget-paced) ───
_preseed_lock = threading.Lock()
_preseed_state = {"running": False, "made": 0, "total": 0, "note": "", "t": 0.0}
_PRESEED_LOCK_WAIT = 90        # secs to wait out a concurrent world_sprites render


def _preseed_worker(combos):
    made = 0
    try:
        _preseed_state.update(running=True, made=0, total=len(combos),
                              note="pre-seeding era sprites", t=time.time())
        for (t, era) in combos:
            eid = entity_id(t, era)
            if "idle" in (wsp.manifest(eid).get("sheets") or {}):
                continue                                   # already made — skip, no spend
            if not ws.b("world_era_sprites_enabled"):
                _preseed_state["note"] = "stopped — feature disabled"
                break
            if not wsp._hour_budget_ok():
                _preseed_state["note"] = (f"hourly budget reached after {made} made — "
                                          f"run pre-seed again later to continue")
                break
            # let a concurrent world_sprites render finish rather than fight the GPU
            waited = 0
            while wsp._gen_lock.locked() and waited < _PRESEED_LOCK_WAIT:
                time.sleep(5)
                waited += 5
            r = _make(t, era)
            if r.get("ok") and not r.get("cached"):
                made += 1
            elif r.get("reason") == "capped":
                _preseed_state["note"] = (f"hourly budget reached after {made} made — "
                                          f"run pre-seed again later to continue")
                break
            _preseed_state.update(made=made, t=time.time())
        else:
            _preseed_state["note"] = f"pre-seed complete — {made} sprite(s) generated"
    except Exception:
        log.exception("era sprite pre-seed worker crashed")
        _preseed_state["note"] = "pre-seed crashed (see logs)"
    finally:
        _preseed_state.update(running=False, t=time.time())
        try:
            _preseed_lock.release()
        except Exception:
            pass


def pre_seed(types=None):
    """Kick a BACKGROUND worker that generates every missing (type, era) sprite
    one-at-a-time, respecting the shared hourly budget (it stops and asks to be
    re-run when the budget is spent — it never blasts the GPU). ``types`` may be a
    subset of ``all_types()``; None = all. Returns immediately."""
    if not ws.b("world_era_sprites_enabled"):
        return {"ok": False, "reason": "disabled",
                "note": "turn on world_era_sprites_enabled first (it spends GPU)"}
    if isinstance(types, str):
        types = [types]
    if types:
        types = [t for t in types if _norm(t)]
    types = types or all_types()
    combos = [(t, era) for t in types for era in ERAS]
    if not _preseed_lock.acquire(blocking=False):
        return {"ok": False, "reason": "running", "note": "a pre-seed is already running",
                "state": dict(_preseed_state)}
    threading.Thread(target=_preseed_worker, args=(combos,), daemon=True).start()
    return {"ok": True, "started": True, "total": len(combos),
            "note": f"pre-seeding up to {len(combos)} era sprites (budget-paced)"}


# ── status (shape mirrors world_terrain.status()) ──────────────────────────────
def _budget():
    """(max_hour, used_this_hour, remaining) against the SHARED world_sprites cap."""
    max_hour = max(1, ws.i("world_sprites_max_hour"))
    used = 0
    conn = get_conn()
    try:
        raw = mget(conn.cursor(), "sprites_gen_times", "[]") or "[]"
        try:
            used = len([t for t in json.loads(raw) if time.time() - t < 3600])
        except Exception:
            used = 0
    except Exception:
        pass
    finally:
        conn.close()
    return max_hour, used, max(0, max_hour - used)


def status():
    """Which (type, era) sprites exist + counts + queued + budget-remaining.

        { enabled, ladder, types, total, have_count, queued, missing,
          have: [{type, era, entity, url}], budget: {max_hour, used, remaining},
          preseed: {running, made, total, note} }

    Never raises — returns a safe shape (0 sprites is fine)."""
    try:
        types = all_types()
        have, queued = [], 0
        for t in types:
            for era in ERAS:
                eid = entity_id(t, era)
                m = wsp.manifest(eid)
                meta = (m.get("sheets") or {}).get("idle")
                if meta:
                    have.append({"type": t, "era": era, "entity": eid,
                                 "url": wsp._url(eid, meta["file"])})
                elif "idle" in (m.get("pending") or {}):
                    queued += 1
        total = len(types) * len(ERAS)
        max_hour, used, remaining = _budget()
        return {
            "enabled": ws.b("world_era_sprites_enabled"),
            "ladder": list(ERAS),
            "types": types,
            "total": total,
            "have_count": len(have),
            "queued": queued,
            "missing": total - len(have) - queued,
            "have": have,
            "budget": {"max_hour": max_hour, "used": used, "remaining": remaining},
            "preseed": dict(_preseed_state),
        }
    except Exception:
        log.exception("era sprite status failed")
        return {"enabled": ws.b("world_era_sprites_enabled"), "ladder": list(ERAS),
                "types": [], "total": 0, "have_count": 0, "queued": 0, "missing": 0,
                "have": [], "budget": {"max_hour": 0, "used": 0, "remaining": 0},
                "preseed": dict(_preseed_state)}
