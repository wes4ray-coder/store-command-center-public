"""🎮 Games → shop: curate-then-push a game title to the WooCommerce store.

WHY THIS EXISTS (owner requirement, 2026-07-19): game projects on the node must
NEVER be public or auto-listed anywhere. There is no "list my games" endpoint and
nothing here runs on a schedule. The owner picks ONE project, hand-builds a listing
locally, and only then pushes it — and even that push lands as a WooCommerce
**draft** that still has to be published by hand in WP admin.

The flow, in order:
    1. POST /api/games/publish/draft        build a LOCAL listing draft from a project
    2. PATCH …/draft/{id}                   edit title/price/copy/images — never leaves the box
    3. (optional) images + description helpers, all local or queued
    4. POST /api/games/publish/{id}/push    create/update the Woo product as status=draft

State lives in the `game_listings` table (db_schema.create_game_listing_tables) plus
one folder per listing under DATA_DIR/game_listings/<id>/ for the picked images.

Transport is the SAME WooCommerce/WordPress plumbing the Portal tab uses:
routers.portal._wc() (WooClient, creds from settings) and routers.portal._mcp()
(WPMcpClient, media library). No new credentials, no new HTTP client. Products are
written through WooClient._req so this module can force `status="draft"` on create
AND update (the client's create_external_product has no update sibling); `_DRAFT`
is a module constant and the only status value ever sent.

Everything degrades: no Woo creds → an explanation, not a 500; node unreachable →
an empty screenshot list. Nothing here can publish.
"""
import base64
import json
import re
import shlex
import time
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from config import DATA_DIR
from db import get_conn
from orchestrator import orch

router = APIRouter()

# The ONLY WooCommerce status this module will ever send. Never parameterised.
_DRAFT = "draft"

LISTING_DIR = Path(DATA_DIR) / "game_listings"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 12

_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")
_PATH_RE = re.compile(r"^[A-Za-z0-9 _./~-]{1,300}$")

# Folders inside a game project that are engine noise, never art worth listing.
_SKIP_DIRS = ("/Library/", "/.git/", "/node_modules/", "/Temp/", "/obj/", "/Build/",
              "/.import/", "/Logs/", "/UserSettings/", "/Intermediate/", "/Saved/",
              "/DerivedDataCache/", "/.godot/")
# Filename hints that a PNG is an actual screenshot/cover rather than a UI atlas.
_ART_HINTS = ("screenshot", "screen_shot", "screen shot", "thumbnail", "thumb",
              "cover", "preview", "banner", "promo", "capsule", "keyart", "key_art",
              "splash", "icon", "logo")


def _ensure_tables():
    try:
        from db_schema import create_game_listing_tables
        conn = get_conn()
        create_game_listing_tables(conn)
        conn.close()
    except Exception:
        pass


_ensure_tables()


# ─── settings / gate ─────────────────────────────────────────────────────────

def _setting(key, default=""):
    try:
        c = get_conn()
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        c.close()
        if row and row["value"] not in (None, ""):
            return row["value"]
    except Exception:
        pass
    return default


def _gate_on() -> bool:
    """Push confirmation gate. Default ON, and — per house rule — toggleable, so the
    owner can turn the extra confirm step off without losing the draft-only floor
    (which is NOT a toggle: pushes are always Woo drafts)."""
    return str(_setting("games_publish_gate", "1")).strip().lower() not in ("0", "off", "false", "")


@router.post("/api/games/publish/gate")
def games_publish_gate(body: dict = Body(default={})):
    """Turn the extra "confirm before push" step on/off. Cannot disable the
    draft-only rule — that is structural."""
    on = 1 if body.get("on") in (True, 1, "1", "on", "true") else 0
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                 ("games_publish_gate", str(on)))
    conn.commit()
    conn.close()
    return {"ok": True, "gate": bool(on)}


# ─── shop plumbing (reused from the Portal tab) ──────────────────────────────

def _woo_state() -> dict:
    """What the shop side can do right now, without raising."""
    out = {"products_configured": False, "media_configured": False, "error": ""}
    try:
        from deps import get_setting
        from config import (WP_URL, WP_CONSUMER_KEY, WP_CONSUMER_SECRET,
                            WP_MCP_URL, WP_MCP_TOKEN)
        url = get_setting("wp_url", "") or WP_URL
        ck = get_setting("wp_consumer_key", "") or WP_CONSUMER_KEY
        cs = get_setting("wp_consumer_secret", "") or WP_CONSUMER_SECRET
        out["products_configured"] = bool(url and ck and cs)
        out["media_configured"] = bool((get_setting("wp_mcp_url", "") or WP_MCP_URL)
                                       and (get_setting("wp_mcp_token", "") or WP_MCP_TOKEN))
        if not out["products_configured"]:
            out["error"] = ("WooCommerce isn't connected yet — add the shop URL and API key "
                            "in the Portal tab. Listings can still be drafted and edited here; "
                            "only the push to the shop needs it.")
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def _wc():
    from routers.portal import _wc as portal_wc
    return portal_wc()


def _mcp():
    from routers.portal import _mcp as portal_mcp
    return portal_mcp()


# ─── row helpers ─────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or "game"


def _row(lid: int):
    conn = get_conn()
    r = conn.execute("SELECT * FROM game_listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    return r


def _images_of(row) -> list:
    try:
        v = json.loads(row["images"] or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _dto(row) -> dict:
    d = dict(row)
    d["images"] = _images_of(row)
    d["price"] = round((d.get("price_cents") or 0) / 100.0, 2)
    d["pushed"] = bool(d.get("wp_id"))
    d["needs_update"] = bool(d.get("wp_id")) and (d.get("updated_at") or "") > (d.get("pushed_at") or "")
    for img in d["images"]:
        img["url"] = f"/api/games/publish/draft/{d['id']}/image/{img.get('file', '')}"
    return d


def _listing_dir(lid: int) -> Path:
    p = LISTING_DIR / str(int(lid))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _touch(lid: int):
    conn = get_conn()
    conn.execute("UPDATE game_listings SET updated_at=datetime('now') WHERE id=?", (lid,))
    conn.commit()
    conn.close()


def _save_images(lid: int, images: list):
    conn = get_conn()
    conn.execute("UPDATE game_listings SET images=?,updated_at=datetime('now') WHERE id=?",
                 (json.dumps(images[:MAX_IMAGES]), lid))
    conn.commit()
    conn.close()


# ─── retail-safety: the shop must never learn where the project lives ────────

def _scrub(text: str, row=None) -> str:
    """Strip anything that would leak the box/node/filesystem into public shop copy.

    The listing is the ONE artefact that leaves the network, so the project's path,
    the node hostname and any home directory are removed before it is sent — even if
    the owner (or the LLM helper) pasted them into the description by accident.
    """
    t = str(text or "")
    candidates = []
    if row is not None:
        try:
            candidates.append(row["project_path"] or "")
        except Exception:
            pass
    try:
        from routers.games import _project_root, _node_label
        candidates += [_project_root(), _node_label()]
    except Exception:
        pass
    for c in candidates:
        c = (c or "").strip()
        # Only strip tokens that actually look like a path or a host, so a short
        # config value (e.g. a node nicknamed "node") can't eat words out of the copy.
        if len(c) >= 6 and ("/" in c or "." in c):
            t = t.replace(c, "")
            t = t.replace(c.replace("~", "/home"), "")
    # generic absolute paths, ~/ paths, and bare IPv4 addresses
    t = re.sub(r"(?:/(?:home|root|mnt|media|srv|opt)/[\w./~ -]+)", "", t)
    t = re.sub(r"~/[\w./-]+", "", t)
    t = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


# ─── status ──────────────────────────────────────────────────────────────────

@router.get("/api/games/publish/status")
def publish_status():
    """Shop-connection state + the gate, for the banner at the top of the editor."""
    st = _woo_state()
    return {**st, "gate": _gate_on(), "draft_only": True,
            "note": ("Pushing creates a DRAFT product in WooCommerce. Nothing about your "
                     "projects is public until you open the shop admin and publish it "
                     "yourself — the store never publishes, and never lists your projects "
                     "anywhere else.")}


# ─── draft CRUD ──────────────────────────────────────────────────────────────

@router.get("/api/games/publish/drafts")
def list_drafts(project: str = ""):
    """All local listing drafts (optionally just the ones for one project path)."""
    conn = get_conn()
    if project:
        rows = conn.execute("SELECT * FROM game_listings WHERE project_path=? "
                            "ORDER BY updated_at DESC", (project,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM game_listings ORDER BY updated_at DESC").fetchall()
    conn.close()
    st = _woo_state()
    return {"drafts": [_dto(r) for r in rows], "count": len(rows),
            "products_configured": st["products_configured"],
            "media_configured": st["media_configured"], "gate": _gate_on()}


@router.post("/api/games/publish/draft")
async def create_draft(request: Request):
    """Build a shop listing draft from a project. Local only — nothing is sent anywhere.

    Body: {project_path, project_name?, engine?, title?, price?/price_cents?,
           short_desc?, long_desc?, category?, tags?, external_url?, button_text?}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = (body.get("project_path") or "").strip()
    if not path or not _PATH_RE.match(path):
        return JSONResponse({"error": "A valid project path is required."}, status_code=400)
    name = (body.get("project_name") or Path(path).name or "Game").strip()
    title = (body.get("title") or name).strip()[:120]
    if not title:
        return JSONResponse({"error": "A listing title is required."}, status_code=400)
    engine = (body.get("engine") or "").strip().lower()[:16]

    price_cents = _price_cents(body)
    if price_cents is None:
        return JSONResponse({"error": "Price must be a number of dollars (0 or more)."},
                            status_code=400)

    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO game_listings
           (project_path, project_name, engine, title, slug, price_cents, short_desc,
            long_desc, category, tags, external_url, button_text, images, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')""",
        (path, name, engine, title, (body.get("slug") or _slugify(title))[:120], price_cents,
         str(body.get("short_desc") or "")[:600], str(body.get("long_desc") or "")[:20000],
         str(body.get("category") or "Games")[:80], str(body.get("tags") or "")[:300],
         str(body.get("external_url") or "")[:500],
         str(body.get("button_text") or "Get the game")[:60], "[]"))
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return {"ok": True, "draft": _dto(_row(lid)),
            "note": "Saved locally. Nothing has been sent to the shop."}


def _price_cents(body: dict):
    """Money is cents everywhere in this app; accept dollars or cents from the client."""
    if body.get("price_cents") not in (None, ""):
        try:
            v = int(body["price_cents"])
            return v if v >= 0 else None
        except (TypeError, ValueError):
            return None
    if body.get("price") in (None, ""):
        return 0
    try:
        v = round(float(str(body["price"]).replace("$", "").strip()) * 100)
        return int(v) if v >= 0 else None
    except (TypeError, ValueError):
        return None


@router.get("/api/games/publish/draft/{lid}")
def get_draft(lid: int):
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    return {"draft": _dto(row), **_woo_state(), "gate": _gate_on()}


@router.patch("/api/games/publish/draft/{lid}")
async def update_draft(lid: int, request: Request):
    """Edit a local draft. Still nothing leaves the box."""
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    fields, vals = [], []
    limits = {"title": 120, "slug": 120, "short_desc": 600, "long_desc": 20000,
              "category": 80, "tags": 300, "external_url": 500, "button_text": 60}
    for k, lim in limits.items():
        if k in body:
            fields.append(f"{k}=?")
            vals.append(str(body.get(k) or "")[:lim])
    if "price" in body or "price_cents" in body:
        pc = _price_cents(body)
        if pc is None:
            return JSONResponse({"error": "Price must be a number of dollars (0 or more)."},
                                status_code=400)
        fields.append("price_cents=?")
        vals.append(pc)
    if not fields:
        return {"ok": True, "draft": _dto(row)}
    vals.append(lid)
    conn = get_conn()
    conn.execute(f"UPDATE game_listings SET {','.join(fields)},updated_at=datetime('now') "
                 f"WHERE id=?", vals)
    conn.commit()
    conn.close()
    return {"ok": True, "draft": _dto(_row(lid))}


@router.delete("/api/games/publish/draft/{lid}")
def delete_draft(lid: int):
    """Delete the LOCAL draft only. A product already pushed to the shop is left
    exactly as it is — this never touches WooCommerce."""
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    conn = get_conn()
    conn.execute("DELETE FROM game_listings WHERE id=?", (lid,))
    conn.commit()
    conn.close()
    try:
        import shutil
        shutil.rmtree(LISTING_DIR / str(lid), ignore_errors=True)
    except Exception:
        pass
    return {"ok": True,
            "note": ("Local draft deleted. Any product already in the shop was left "
                     "untouched — remove it in WooCommerce if you want it gone.")}


# ─── images: (a) screenshots from the project on the node ────────────────────

@router.get("/api/games/publish/screenshots")
def screenshots(path: str = ""):
    """Look for existing screenshot/thumbnail art inside a project folder on the node.

    Unity projects very often have NO usable art on disk (everything lives in scenes
    and prefabs), so an empty list is a normal, expected result — not an error.
    """
    if not path or not _PATH_RE.match(path):
        return JSONResponse({"error": "A valid project path is required."}, status_code=400)
    try:
        from routers.games import _ssh, _node_label
    except Exception:
        return {"shots": [], "reachable": False, "error": "node helper unavailable"}
    names = " -o ".join(f"-iname '*{e}'" for e in _IMG_EXT)
    rc, out = _ssh(f'p={shlex.quote(path)}; p="${{p/#\\~/$HOME}}"; '
                   f'find "$p" -maxdepth 5 -type f \\( {names} \\) '
                   f"-size -8M -printf '%p|%s\\n' 2>/dev/null | head -300", timeout=45)
    if rc != 0:
        return {"shots": [], "reachable": False, "node": _node_label(),
                "error": (out or "node unreachable").strip()[:200]}
    shots = []
    for line in (out or "").splitlines():
        if "|" not in line:
            continue
        fpath, _, size = line.rpartition("|")
        fpath = fpath.strip()
        if not fpath or any(s in fpath for s in _SKIP_DIRS):
            continue
        try:
            nbytes = int(size)
        except (TypeError, ValueError):
            nbytes = 0
        low = fpath.lower()
        shots.append({"path": fpath, "name": Path(fpath).name,
                      "size_kb": round(nbytes / 1024, 1),
                      "likely_art": any(h in low for h in _ART_HINTS)})
    shots.sort(key=lambda s: (not s["likely_art"], s["name"].lower()))
    return {"shots": shots[:80], "reachable": True, "node": _node_label(), "error": None,
            "note": ("Nothing here? That's normal for Unity — projects usually have no "
                     "finished art on disk. Upload a screenshot or generate cover art instead.")}


@router.post("/api/games/publish/draft/{lid}/screenshots")
async def pull_screenshots(lid: int, request: Request):
    """Copy chosen screenshot files off the node into this listing's local folder."""
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    paths = [p for p in (body.get("paths") or []) if isinstance(p, str)][:MAX_IMAGES]
    if not paths:
        return JSONResponse({"error": "Pick at least one screenshot."}, status_code=400)
    try:
        from routers.games import _ssh
    except Exception:
        return JSONResponse({"error": "Node helper unavailable."}, status_code=502)

    images = _images_of(row)
    d = _listing_dir(lid)
    added, skipped = [], []
    for p in paths:
        if not _PATH_RE.match(p) or Path(p).suffix.lower() not in _IMG_EXT:
            skipped.append({"path": p[:80], "why": "not an image path"})
            continue
        rc, out = _ssh(f"base64 -w0 {shlex.quote(p)} 2>/dev/null", timeout=90)
        raw = (out or "").strip()
        if rc != 0 or not raw:
            skipped.append({"path": Path(p).name, "why": "could not read it on the node"})
            continue
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception:
            skipped.append({"path": Path(p).name, "why": "unreadable"})
            continue
        if not data or len(data) > MAX_IMAGE_BYTES:
            skipped.append({"path": Path(p).name, "why": "empty or too large"})
            continue
        fn = _unique_name(d, Path(p).name)
        (d / fn).write_bytes(data)
        images.append({"file": fn, "kind": "screenshot", "label": Path(p).name,
                       "added": int(time.time())})
        added.append(fn)
    _save_images(lid, images)
    return {"ok": bool(added), "added": added, "skipped": skipped,
            "draft": _dto(_row(lid))}


def _unique_name(d: Path, name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:60] or "image.png"
    if Path(safe).suffix.lower() not in _IMG_EXT:
        safe += ".png"
    stem, suf = Path(safe).stem, Path(safe).suffix
    out, n = safe, 1
    while (d / out).exists():
        n += 1
        out = f"{stem}_{n}{suf}"
    return out


# ─── images: (b) owner uploads ───────────────────────────────────────────────

@router.post("/api/games/publish/draft/{lid}/upload")
async def upload_image(lid: int, file: UploadFile = File(...)):
    """Attach an image the owner picked from their own machine."""
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    data = await file.read()
    if not data:
        return JSONResponse({"error": "That file was empty."}, status_code=400)
    if len(data) > MAX_IMAGE_BYTES:
        return JSONResponse({"error": "Images must be under 8 MB."}, status_code=400)
    if Path(file.filename or "").suffix.lower() not in _IMG_EXT:
        return JSONResponse({"error": "Use a PNG, JPG, WEBP or GIF."}, status_code=400)
    d = _listing_dir(lid)
    fn = _unique_name(d, file.filename or "upload.png")
    (d / fn).write_bytes(data)
    images = _images_of(row)
    images.append({"file": fn, "kind": "upload", "label": file.filename or fn,
                   "added": int(time.time())})
    _save_images(lid, images)
    return {"ok": True, "file": fn, "draft": _dto(_row(lid))}


@router.get("/api/games/publish/draft/{lid}/image/{name}")
def serve_image(lid: int, name: str):
    """Serve a listing image back to the editor (local preview only)."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "")
    f = LISTING_DIR / str(int(lid)) / safe
    if not safe or not f.is_file():
        raise HTTPException(404, "Image not found.")
    return FileResponse(str(f))


@router.delete("/api/games/publish/draft/{lid}/image/{name}")
def remove_image(lid: int, name: str):
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "")
    images = [i for i in _images_of(row) if i.get("file") != safe]
    _save_images(lid, images)
    try:
        (LISTING_DIR / str(lid) / safe).unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True, "draft": _dto(_row(lid))}


# ─── images: (c) generated cover art (Studio pipeline, unified queue) ────────

@router.post("/api/games/publish/draft/{lid}/cover")
async def generate_cover(lid: int, request: Request):
    """Queue cover art on the Studio image pipeline.

    Uses the same generations-row + services.run_generation path as Studio, which
    takes the GPU through orch.image_acquire/release — i.e. it rides the unified
    queue and can never race the LLM or another image job.
    """
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        prompt = (f"game cover art for \"{row['title']}\", key art, dramatic lighting, "
                  f"bold title composition, no text")
    prompt = _scrub(prompt, row)[:600]

    conn = get_conn()
    gid = conn.execute(
        "INSERT INTO generations (prompt,product_type,width,height,steps,model,source) "
        "VALUES (?,?,?,?,?,?,?)",
        (prompt, "Poster", 1024, 1024, 20, None, "games")).lastrowid
    conn.commit()
    conn.close()

    import threading
    import services
    threading.Thread(target=services.run_generation, args=(gid,), daemon=True).start()
    return {"ok": True, "generation_id": gid, "prompt": prompt,
            "note": "Queued on the shared GPU queue — it waits its turn like every other job."}


@router.get("/api/games/publish/draft/{lid}/cover/{gid}")
def cover_status(lid: int, gid: int):
    """Poll a queued cover render; on success copy it into the listing folder once."""
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    conn = get_conn()
    g = conn.execute("SELECT status,image_path FROM generations WHERE id=?", (gid,)).fetchone()
    conn.close()
    if not g:
        return {"status": "unknown", "attached": False}
    if g["status"] != "done" or not g["image_path"]:
        return {"status": g["status"], "attached": False}

    images = _images_of(row)
    if any(i.get("gen_id") == gid for i in images):
        return {"status": "done", "attached": True, "draft": _dto(row)}
    try:
        src = Path(g["image_path"])
        if not src.is_file():
            return {"status": "done", "attached": False, "error": "render file missing"}
        d = _listing_dir(lid)
        fn = _unique_name(d, f"cover_{gid}.png")
        (d / fn).write_bytes(src.read_bytes())
        images.append({"file": fn, "kind": "generated", "label": "Generated cover",
                       "gen_id": gid, "added": int(time.time())})
        _save_images(lid, images)
        # Cover art is not merch — keep it out of the designs review queue.
        conn = get_conn()
        conn.execute("DELETE FROM designs WHERE generation_id=? AND source='games'", (gid,))
        conn.commit()
        conn.close()
    except Exception as e:
        return {"status": "done", "attached": False, "error": str(e)[:200]}
    return {"status": "done", "attached": True, "draft": _dto(_row(lid))}


# ─── description helper (LLM, through the orchestrator queue) ────────────────

_DESC_SYSTEM = (
    "You write short, honest store copy for indie video games. You are given a game's "
    "working title and whatever scraps of metadata exist. Reply with JSON only: "
    '{"short":"one punchy sentence, max 200 characters",'
    '"long":"2-4 short paragraphs of plain HTML using <p> tags",'
    '"tags":"comma separated, max 6"}. '
    "Never invent platforms, review scores, release dates, prices or awards. Never mention "
    "file paths, servers, folders or how the game was made. If you know little, stay vague "
    "and brief rather than making things up."
)

_DESC_JOBS: dict = {}      # task_id -> {status, result, error}


@router.post("/api/games/publish/draft/{lid}/describe")
def describe_draft(lid: int):
    """Ask the LLM for draft marketing copy. ALWAYS through orch.submit_llm — this
    module never calls the model host directly. The result is returned to the editor
    for the owner to edit; it is never written to the draft or pushed automatically.
    """
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    facts = (f"TITLE: {row['title']}\nENGINE: {row['engine'] or 'unknown'}\n"
             f"EXISTING SHORT DESCRIPTION: {row['short_desc'] or '(none)'}\n"
             f"EXISTING LONG DESCRIPTION: {(row['long_desc'] or '(none)')[:1500]}\n"
             f"TAGS: {row['tags'] or '(none)'}")

    def _work():
        from deps import _call_lmstudio
        return _call_lmstudio(_DESC_SYSTEM, facts, max_tokens=900)

    holder = {"id": 0}

    def _wrapped():
        try:
            txt = _work()
            _DESC_JOBS[holder["id"]] = {"status": "done", "result": txt, "error": ""}
            return txt
        except Exception as e:
            _DESC_JOBS[holder["id"]] = {"status": "failed", "result": "", "error": str(e)[:300]}
            raise

    tid = orch.submit_llm(_wrapped, desc=f"game listing copy: {str(row['title'])[:40]}",
                          priority=1, source="games")
    holder["id"] = tid
    _DESC_JOBS[tid] = {"status": "queued", "result": "", "error": ""}
    if len(_DESC_JOBS) > 60:
        for old in sorted(_DESC_JOBS)[:-60]:
            _DESC_JOBS.pop(old, None)
    return {"ok": True, "task_id": tid,
            "note": "Queued. The suggestion appears here for you to edit — it is never "
                    "saved or pushed on its own."}


@router.get("/api/games/publish/describe/{task_id}")
def describe_status(task_id: int):
    rec = dict(_DESC_JOBS.get(task_id) or {})
    try:
        q = orch.poll(task_id)
    except Exception:
        q = {"status": "unknown"}
    status = rec.get("status") or q.get("status", "unknown")
    out = {"task_id": task_id, "status": status, "error": rec.get("error", "")}
    txt = rec.get("result") or ""
    if txt:
        out["raw"] = txt[:8000]
        parsed = None
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = None
        if isinstance(parsed, dict):
            out["short"] = _scrub(str(parsed.get("short") or ""))[:600]
            out["long"] = _scrub(str(parsed.get("long") or ""))[:20000]
            out["tags"] = str(parsed.get("tags") or "")[:300]
        else:
            out["long"] = _scrub(txt)[:20000]
    return out


# ─── push (Woo DRAFT only) ───────────────────────────────────────────────────

def _upload_images_to_wp(row) -> tuple:
    """Push the listing's local images into the WP media library, newest last.
    Returns (urls, errors). Missing media creds is a soft failure — the product is
    still created, just without art."""
    images = _images_of(row)
    if not images:
        return [], []
    urls, errs = [], []
    try:
        mcp = _mcp()
    except Exception as e:
        return [], [f"media library unavailable: {str(e)[:120]}"]
    d = LISTING_DIR / str(row["id"])
    for img in images:
        fn = img.get("file") or ""
        f = d / fn
        try:
            if not f.is_file():
                errs.append(f"{fn}: file missing")
                continue
            if img.get("wp_url"):
                urls.append(img["wp_url"])
                continue
            att = mcp.upload_media_base64(fn, f.read_bytes(),
                                          title=row["title"], alt_text=row["title"])
            src = att.get("source_url") or att.get("url") or att.get("guid") or ""
            if src:
                img["wp_url"] = src
                urls.append(src)
            else:
                errs.append(f"{fn}: upload returned no URL")
        except Exception as e:
            errs.append(f"{fn}: {str(e)[:120]}")
    _save_images(row["id"], images)
    return urls, errs


def _product_payload(row, image_urls, category_ids) -> dict:
    """Build the WooCommerce product body. `status` is hard-wired to draft."""
    tags = [t.strip() for t in (row["tags"] or "").split(",") if t.strip()][:15]
    ext = (row["external_url"] or "").strip()
    payload = {
        "name": _scrub(row["title"], row)[:120] or row["title"],
        "type": "external" if ext else "simple",
        "status": _DRAFT,                       # never "publish" — structural, not a setting
        "catalog_visibility": "hidden",         # invisible in the shop even if published early
        "description": _scrub(row["long_desc"] or "", row),
        "short_description": _scrub(row["short_desc"] or "", row),
        "regular_price": f"{(row['price_cents'] or 0) / 100:.2f}",
    }
    if ext:
        payload["external_url"] = ext
        payload["button_text"] = row["button_text"] or "Get the game"
    if row["slug"]:
        payload["slug"] = row["slug"]
    if image_urls:
        payload["images"] = [{"src": u} for u in image_urls if u]
    if category_ids:
        payload["categories"] = [{"id": i} for i in category_ids if i]
    if tags:
        payload["tags"] = [{"name": t} for t in tags]
    return payload


@router.post("/api/games/publish/{lid}/push")
async def push_listing(lid: int, request: Request):
    """Create (or update) the WooCommerce product for this listing AS A DRAFT.

    * status is always "draft" — this endpoint has no way to publish anything.
    * Re-pushing an already-pushed listing UPDATES the same product id instead of
      creating a duplicate.
    * The gate (default on, toggleable) requires an explicit confirm=true.
    """
    row = _row(lid)
    if not row:
        raise HTTPException(404, "Listing draft not found.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if _gate_on() and body.get("confirm") not in (True, 1, "1", "true", "yes"):
        return JSONResponse({"error": "Confirm the push first — this creates a draft product "
                                      "in your shop.", "needs_confirm": True}, status_code=400)
    if not (row["title"] or "").strip():
        return JSONResponse({"error": "Give the listing a title before pushing."}, status_code=400)

    st = _woo_state()
    if not st["products_configured"]:
        return JSONResponse({"error": st["error"] or "WooCommerce isn't connected."},
                            status_code=400)
    try:
        wc = _wc()
    except Exception as e:
        return JSONResponse({"error": str(getattr(e, "detail", e))[:300]}, status_code=400)

    image_urls, image_errors = _upload_images_to_wp(row)
    row = _row(lid)                                    # re-read: wp_url cached on images

    cat_ids = []
    if (row["category"] or "").strip():
        try:
            cid = wc.ensure_category(row["category"].strip())
            if cid:
                cat_ids.append(cid)
        except Exception:
            pass

    payload = _product_payload(row, image_urls, cat_ids)
    assert payload["status"] == _DRAFT              # belt-and-braces: never publish

    try:
        if row["wp_id"]:
            prod = wc._req("PUT", f"/products/{int(row['wp_id'])}", json=payload)
            action = "updated"
        else:
            prod = wc._req("POST", "/products", json=payload)
            action = "created"
    except Exception as e:
        # A product deleted in WP admin should not wedge the listing forever.
        if row["wp_id"] and "404" in str(e):
            try:
                prod = wc._req("POST", "/products", json=payload)
                action = "created"
            except Exception as e2:
                return JSONResponse({"error": str(e2)[:300]}, status_code=502)
        else:
            return JSONResponse({"error": str(e)[:300]}, status_code=502)

    wp_id = (prod or {}).get("id")
    permalink = (prod or {}).get("permalink") or ""
    admin_url = ""
    try:
        from deps import get_setting
        from config import WP_URL
        base = (get_setting("wp_url", "") or WP_URL or "").rstrip("/")
        if base and wp_id:
            admin_url = f"{base}/wp-admin/post.php?post={wp_id}&action=edit"
    except Exception:
        pass

    conn = get_conn()
    conn.execute("UPDATE game_listings SET wp_id=?,wp_link=?,wp_admin_url=?,wp_status=?,"
                 "status='pushed',pushed_at=datetime('now'),updated_at=datetime('now') "
                 "WHERE id=?",
                 (wp_id, permalink, admin_url, (prod or {}).get("status") or _DRAFT, lid))
    conn.commit()
    conn.close()
    try:
        from cache import invalidate_prefix
        invalidate_prefix("portal:wp-products:")
    except Exception:
        pass

    return {"ok": True, "action": action, "wp_id": wp_id, "wp_status": _DRAFT,
            "wp_link": permalink, "admin_url": admin_url,
            "image_errors": image_errors, "draft": _dto(_row(lid)),
            "note": ("Created as a DRAFT in WooCommerce. It is NOT visible to anyone — "
                     "open it in the shop admin, check it over, and publish it yourself "
                     "when you're ready.")}
