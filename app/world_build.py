"""
The Company — world builder (pixel-art asset generation).

Renders props as pixel-art sprites through ComfyUI and drips themed tools into the
office over time. All GPU work goes through the orchestrator's image lane
(orch.image_acquire/release) — the same handshake services.run_generation uses — so
a render waits for the LLM to unload and never dumps a second model on the GPU. A
process-wide lock keeps it to one render at a time.
"""
import time, random, subprocess, threading, logging, shutil

from deps import get_conn, orch, GENERATE_SCRIPT, DEFAULT_IMAGE_MODEL
from world_defs import WORLD_ASSETS, DEPT_TOOL, ITEM_COST, pixel_prompt
import world_settings as ws
import world_vision

logger = logging.getLogger("store")

_gen_lock = threading.Lock()       # one prop renders at a time (shared GPU)


def _event(conn, key, kind, text):
    conn.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)", (key, kind, text))


def _knockout_bg(im, tol=26):
    """Make the flat background transparent: flood-fill inward from every border
    pixel, erasing pixels close to their border seed colour. Sprites then sit on
    the map instead of arriving as a baked square tile."""
    from collections import deque
    px = im.load()
    w, h = im.size
    out = im.convert("RGBA")
    opx = out.load()
    seen = [[False] * h for _ in range(w)]
    q = deque()
    for x in range(w):
        q.append((x, 0, px[x, 0])); q.append((x, h - 1, px[x, h - 1]))
    for y in range(h):
        q.append((0, y, px[0, y])); q.append((w - 1, y, px[w - 1, y]))
    while q:
        x, y, seed = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[x][y]:
            continue
        r, g, b = px[x, y][:3]
        sr, sg, sb = seed[:3]
        if abs(r - sr) + abs(g - sg) + abs(b - sb) > tol * 3:
            continue
        seen[x][y] = True
        opx[x, y] = (r, g, b, 0)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q.append((x + dx, y + dy, seed))
    return out


def _pixelate(src, dst, cells=64, colors=24):
    """Turn a soft SDXL render into a crisp pixel-art sprite: centre-crop square,
    nearest-neighbour downscale to `cells`px, quantise the palette, then knock the
    flat background out to transparency. The canvas upscales it with
    image-rendering:pixelated."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    im = im.resize((cells, cells), Image.NEAREST)
    im = im.quantize(colors=colors, method=Image.MEDIANCUT).convert("RGB")
    cut = _knockout_bg(im)
    # safety net: if the sprite's own colours matched the background, the flood
    # fill eats the object — in that case ship it opaque rather than shredded.
    opaque = sum(1 for p in cut.getdata() if p[3] > 0)
    if opaque < cells * cells * 0.22:
        cut = im.convert("RGBA")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cut.save(dst)


def _make_sheet(final, frames=4):
    """Build a horizontal idle-animation sheet next to the final sprite
    (<name>_sheet.png): a gentle 1px bob + brightness breathe. Cheap, consistent
    frames — far more reliable than asking the diffusion model for a sheet."""
    from PIL import Image, ImageEnhance
    im = Image.open(final).convert("RGBA")
    w, h = im.size
    sheet = Image.new("RGBA", (w * frames, h), (0, 0, 0, 0))
    bob = [0, -1, 0, 1]
    lum = [1.0, 1.05, 1.0, 0.95]
    for f in range(frames):
        frame = ImageEnhance.Brightness(im).enhance(lum[f % 4])
        sheet.paste(frame, (w * f, bob[f % 4]), frame)
    p = final.with_name(final.stem + "_sheet.png")
    sheet.save(p)
    return p


def _render_candidates(prop_id, prompt, n):
    """Render n sprite candidates in ONE ComfyUI session (one LLM→image swap), then
    pixelate each. Returns list of pixelated candidate paths."""
    out = []
    model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
    lora = ws.s("world_prop_lora")            # "" disables; needs the file on the GPU box
    orch.image_acquire()
    try:
        for k in range(n):
            raw = WORLD_ASSETS / f"prop_{prop_id}_raw{k}.png"
            seed = str(random.randint(1, 2**31 - 1))
            try:
                res = subprocess.run(
                    [str(GENERATE_SCRIPT), prompt, str(raw), "768", "768", "8", seed, model, lora],
                    capture_output=True, text=True, timeout=300)
                if res.returncode == 0 and raw.exists():
                    cand = WORLD_ASSETS / f"prop_{prop_id}_c{len(out)}.png"
                    _pixelate(raw, cand)
                    out.append(cand)
                else:
                    logger.error("world prop %d cand %d failed: %s", prop_id, k, (res.stderr or "")[:160])
            except Exception as ex:
                logger.error("world prop %d cand %d error: %s", prop_id, k, ex)
            finally:
                try: raw.unlink()
                except Exception: pass
    finally:
        orch.image_release()
    return out


def generate_world_prop(prop_id: int):
    """Render a prop as pixel art — with EYES. Generates N candidates, has the vision
    model score them (world_vision), keeps the best, and retries with feedback if the
    best is still poor. Degrades gracefully to a single blind render when no vision
    model is around. GPU access always via the orchestrator (one thing at a time)."""
    if not _gen_lock.acquire(blocking=False):
        return
    try:
        conn = get_conn()
        row = conn.execute("SELECT * FROM world_props WHERE id=?", (prop_id,)).fetchone()
        if not row:
            conn.close(); return
        r = dict(row)
        conn.execute("UPDATE world_props SET status='generating' WHERE id=?", (prop_id,))
        conn.commit()
        WORLD_ASSETS.mkdir(parents=True, exist_ok=True)

        label = r["label"]
        base_prompt = r["prompt"] or pixel_prompt(label)
        see = ws.b("world_vision_enabled") and world_vision.available()
        n = max(1, ws.i("world_vision_candidates")) if see else 1
        rounds = 1 + (ws.i("world_vision_retries") if see else 0)
        min_score = ws.i("world_vision_min_score")
        best = None                              # {"path","score","issues"}
        prompt = base_prompt

        try:
            for rnd in range(rounds):
                cands = _render_candidates(prop_id, prompt, n)
                if not cands:
                    continue
                if see:
                    for c in cands:
                        ev = world_vision.evaluate_asset(c, label)
                        sc = ev.get("score")
                        if sc is None:           # blind (no model available now) → accept first
                            if best is None: best = {"path": c, "score": None, "issues": ""}
                            continue
                        if best is None or best["score"] is None or sc > best["score"]:
                            best = {"path": c, "score": sc, "issues": ev.get("issues", "")}
                    if best and best["score"] is not None:
                        _event(conn, r.get("owner_key"), "vision",
                               f"👁️ Reviewed the {label}: best {best['score']}/10"
                               + (f" — {best['issues']}" if best["issues"] and best["score"] < min_score else ""))
                        conn.commit()
                        if best["score"] >= min_score:
                            break
                        prompt = f"{base_prompt}. Fix: {best['issues']}. MUST be clean flat pixel art, single centered object."
                    else:
                        break                    # blind — one round is enough
                else:
                    best = {"path": cands[0], "score": None, "issues": ""}
                    break

            final = WORLD_ASSETS / f"prop_{prop_id}.png"
            if best and best["path"].exists():
                shutil.copy(best["path"], final)
                try:
                    _make_sheet(final)               # idle-animation frames for the renderer
                except Exception:
                    logger.exception("prop %d sheet failed (static sprite still fine)", prop_id)
                url = f"/store/static/world_assets/{final.name}"
                conn.execute("UPDATE world_props SET status='done', image_path=?, score=?, verdict=? WHERE id=?",
                             (url, best["score"], best["issues"], prop_id))
                if r.get("owner_key"):
                    tag = f" (vision {best['score']}/10)" if best["score"] is not None else ""
                    _event(conn, r["owner_key"], "system", f"A {label} was conjured into the world!{tag} ✨")
            else:
                conn.execute("UPDATE world_props SET status='failed' WHERE id=?", (prop_id,))
        finally:
            # tidy candidate files (keep only the chosen final)
            for f in WORLD_ASSETS.glob(f"prop_{prop_id}_c*.png"):
                try: f.unlink()
                except Exception: pass
            conn.commit(); conn.close()
    finally:
        _gen_lock.release()


def rework_prop(prop_id, reason=""):
    """Regenerate a world creation the god rejected, with the feedback baked into the
    prompt — the world-creation reject → tweak loop. Re-runs generate_world_prop (GPU via
    the orchestrator, vision-scored like any prop)."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT prompt, label FROM world_props WHERE id=?", (prop_id,)).fetchone()
        if not row:
            conn.close(); return
        base = (row["prompt"] or row["label"] or "").split("  [note:")[0].strip()
        note = f"  [note: {reason.strip()}]" if (reason or "").strip() else "  [note: try a different take]"
        conn.execute("UPDATE world_props SET prompt=?, status='queued' WHERE id=?", (base + note, prop_id))
        conn.commit()
    finally:
        conn.close()
    generate_world_prop(prop_id)


# ── agents commissioning their OWN pixel art — earned, capped, GPU-safe ──────
PERSONAL_COST = 60              # coins the agent pays (→ company fund): creation is EARNED
PERSONAL_COOLDOWN_SEC = 6 * 3600   # one commission per agent per 6h
PERSONAL_MAX_PROPS = 20         # global shelf space

PERSONAL_IDEAS = ["ornate trophy", "potted bonsai tree", "vintage radio", "lava lamp",
                  "stack of art books", "crystal figurine", "toy robot", "framed medal"]


def personal_create(c, a):
    """An agent spends its own coins to commission a personal pixel prop.
    Every GPU guard from the autobuilder applies: one render at a time, nothing
    else queued, global cap — real store work always outranks it in the orch
    queue, so the load cost is one serialized image job at most."""
    import time as _t
    from world_defs import mget, mset
    if (a["coins"] or 0) < PERSONAL_COST or _gen_lock.locked():
        return False
    if _t.time() - float(mget(c, f"pc_t_{a['key']}", 0) or 0) < PERSONAL_COOLDOWN_SEC:
        return False
    if c.execute("SELECT COUNT(*) FROM world_props WHERE status IN ('queued','generating')").fetchone()[0]:
        return False
    if c.execute("SELECT COUNT(*) FROM world_props WHERE status='done'").fetchone()[0] >= PERSONAL_MAX_PROPS:
        return False
    item = PERSONAL_IDEAS[(a["id"] * 13 + int(_t.time() // 21600)) % len(PERSONAL_IDEAS)]
    pid = c.execute("INSERT INTO world_props (kind,label,location,prompt,status,owner_key) "
                    "VALUES ('personal',?,?,?,'queued',?)",
                    (item, "home", pixel_prompt(item), a["key"])).lastrowid
    c.execute("UPDATE world_agents SET coins=coins-? WHERE id=?", (PERSONAL_COST, a["id"]))
    a["coins"] -= PERSONAL_COST
    mset(c, "company_fund", int(float(mget(c, "company_fund", 0) or 0)) + PERSONAL_COST)
    mset(c, f"pc_t_{a['key']}", _t.time())
    _event(c, a["key"], "want", f"🎨 {a['name']} commissioned a {item} with their own {PERSONAL_COST}🪙.")
    threading.Thread(target=generate_world_prop, args=(pid,), daemon=True).start()
    return True


_last_autobuild = [0.0]

def maybe_autobuild(conn):
    """The world-builder: every so often give a busy, solvent worker the themed tool
    their studio is missing, and render it. One at a time, GPU permitting."""
    if time.time() - _last_autobuild[0] < 90:
        return
    c = conn.cursor()
    busy = _gen_lock.locked() or c.execute(
        "SELECT COUNT(*) FROM world_props WHERE status IN ('queued','generating')").fetchone()[0]
    if busy:
        return
    if c.execute("SELECT COUNT(*) FROM world_props WHERE status='done'").fetchone()[0] >= 14:
        return
    have = {r["location"] for r in c.execute("SELECT DISTINCT location FROM world_props").fetchall()}
    for row in c.execute("SELECT * FROM world_agents WHERE state='working' ORDER BY xp DESC").fetchall():
        a = dict(row)
        loc = f"desk:{a['dept']}"
        if loc in have or (a["coins"] or 0) < ITEM_COST:
            continue
        tool = DEPT_TOOL.get(a["dept"], "potted plant")
        prompt = pixel_prompt(tool)
        pid = conn.execute(
            "INSERT INTO world_props (kind,label,location,prompt,status,owner_key) "
            "VALUES ('furniture',?,?,?,'queued',?)", (tool, loc, prompt, a["key"])).lastrowid
        conn.execute("UPDATE world_agents SET coins=coins-? WHERE id=?", (ITEM_COST, a["id"]))
        conn.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                     (a["key"], "want", f"{a['name']} spent {ITEM_COST} 🪙 on a {tool}."))
        conn.commit()
        _last_autobuild[0] = time.time()
        threading.Thread(target=generate_world_prop, args=(pid,), daemon=True).start()
        return
