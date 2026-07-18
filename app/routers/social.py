"""Social — draft & schedule posts for Instagram / TikTok / YouTube / Facebook.

Phase 1 (now): a compose + queue workflow. You write (or LLM-generate) a caption,
attach one of your generated images/videos, pick platforms, and schedule it. Then
"copy caption → open the app → mark posted". No platform API keys required.

Phase 2 (later): real auto-posting per platform (YouTube Data API, Meta Graph for
IG/FB, TikTok Content Posting API). The schema + per-platform connection settings
here are already shaped for that — `posted_on` tracks what's live, and the config
endpoints hold handles/tokens.
"""
import json as _json
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, _call_lmstudio, config
from services import *      # (kept consistent with sibling routers)

router = APIRouter()

# Static platform catalog. `auto` is the Phase-2 auto-post status (planned|beta|live).
PLATFORMS = {
    "instagram": {"name": "Instagram", "icon": "\U0001F4F8", "caption_limit": 2200,
                  "media": ["image", "video"], "aspect": "square / 4:5 / 9:16 reel",
                  "upload_url": "https://www.instagram.com/", "auto": "planned",
                  "api": "Meta Graph API (needs FB Business app + review)"},
    "tiktok":    {"name": "TikTok", "icon": "\U0001F3B5", "caption_limit": 2200,
                  "media": ["video"], "aspect": "9:16 vertical video",
                  "upload_url": "https://www.tiktok.com/upload", "auto": "planned",
                  "api": "TikTok Content Posting API (needs app approval)"},
    "youtube":   {"name": "YouTube", "icon": "\U0001F3AC", "caption_limit": 5000,
                  "media": ["video"], "aspect": "16:9 or 9:16 Shorts",
                  "upload_url": "https://studio.youtube.com/", "auto": "planned",
                  "api": "YouTube Data API v3 (Google OAuth)"},
    "facebook":  {"name": "Facebook", "icon": "\U0001F310", "caption_limit": 63206,
                  "media": ["image", "video"], "aspect": "any",
                  "upload_url": "https://www.facebook.com/", "auto": "planned",
                  "api": "Meta Graph API (same app as Instagram)"},
}


def _row(r) -> dict:
    d = dict(r)
    d["platforms"] = _json.loads(d.get("platforms") or "[]")
    d["posted_on"] = _json.loads(d.get("posted_on") or "[]")
    return d


# ── platform catalog + per-platform connection settings ─────────────────────
@router.get("/api/social/platforms")
def social_platforms():
    out = []
    for key, meta in PLATFORMS.items():
        out.append({
            "key": key, **meta,
            "handle": get_setting(f"social_{key}_handle", "") or "",
            "connected": (get_setting(f"social_{key}_connected", "") == "1"),
        })
    return {"platforms": out}


class SocialConfigIn(BaseModel):
    platform: str
    handle: Optional[str] = None
    connected: Optional[bool] = None


@router.post("/api/social/config")
def social_config(cfg: SocialConfigIn):
    if cfg.platform not in PLATFORMS:
        raise HTTPException(400, f"Unknown platform '{cfg.platform}'.")
    conn = get_conn()
    if cfg.handle is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (f"social_{cfg.platform}_handle", cfg.handle.strip()))
    if cfg.connected is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (f"social_{cfg.platform}_connected", "1" if cfg.connected else "0"))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── posts CRUD ──────────────────────────────────────────────────────────────
class SocialPostIn(BaseModel):
    title: Optional[str] = ""
    caption: Optional[str] = ""
    hashtags: Optional[str] = ""
    platforms: list[str] = []
    media_type: Optional[str] = "none"
    media_path: Optional[str] = ""
    media_url: Optional[str] = ""
    status: Optional[str] = "draft"       # draft | scheduled | posted
    scheduled_at: Optional[str] = None
    notes: Optional[str] = ""
    source: Optional[str] = "manual"


@router.get("/api/social/posts")
def list_posts(status: Optional[str] = None):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM social_posts WHERE status=? ORDER BY "
                            "COALESCE(scheduled_at, updated_at) DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM social_posts ORDER BY "
                            "CASE status WHEN 'scheduled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, "
                            "COALESCE(scheduled_at, updated_at) DESC").fetchall()
    conn.close()
    posts = [_row(r) for r in rows]
    counts = {"draft": 0, "scheduled": 0, "posted": 0}
    for p in posts:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {"posts": posts, "counts": counts}


@router.post("/api/social/posts")
def create_post(p: SocialPostIn):
    if not (p.caption or "").strip() and not (p.media_path or p.media_url):
        raise HTTPException(400, "Add a caption or attach media.")
    bad = [x for x in p.platforms if x not in PLATFORMS]
    if bad:
        raise HTTPException(400, f"Unknown platform(s): {', '.join(bad)}")
    status = p.status if p.status in ("draft", "scheduled", "posted") else "draft"
    if status == "scheduled" and not p.scheduled_at:
        status = "draft"
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO social_posts (title,caption,hashtags,platforms,media_type,media_path,
           media_url,status,scheduled_at,notes,source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (p.title, p.caption, p.hashtags, _json.dumps(p.platforms), p.media_type or "none",
         p.media_path, p.media_url, status, p.scheduled_at, p.notes, p.source or "manual"))
    conn.commit()
    row = conn.execute("SELECT * FROM social_posts WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return _row(row)


@router.patch("/api/social/posts/{pid}")
def update_post(pid: int, p: SocialPostIn):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM social_posts WHERE id=?", (pid,)).fetchone():
        conn.close()
        raise HTTPException(404, "Post not found")
    status = p.status if p.status in ("draft", "scheduled", "posted") else "draft"
    if status == "scheduled" and not p.scheduled_at:
        status = "draft"
    conn.execute(
        """UPDATE social_posts SET title=?,caption=?,hashtags=?,platforms=?,media_type=?,
           media_path=?,media_url=?,status=?,scheduled_at=?,notes=?,updated_at=datetime('now')
           WHERE id=?""",
        (p.title, p.caption, p.hashtags, _json.dumps(p.platforms), p.media_type or "none",
         p.media_path, p.media_url, status, p.scheduled_at, p.notes, pid))
    conn.commit()
    row = conn.execute("SELECT * FROM social_posts WHERE id=?", (pid,)).fetchone()
    conn.close()
    return _row(row)


class MarkPostedIn(BaseModel):
    platforms: Optional[list[str]] = None   # which platforms just went live; None = all on the post


@router.post("/api/social/posts/{pid}/mark-posted")
def mark_posted(pid: int, body: MarkPostedIn):
    conn = get_conn()
    row = conn.execute("SELECT * FROM social_posts WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Post not found")
    on_post = _json.loads(row["platforms"] or "[]")
    already = set(_json.loads(row["posted_on"] or "[]"))
    add = body.platforms if body.platforms else on_post
    already.update([x for x in add if x in on_post])
    all_done = set(on_post).issubset(already) and on_post
    conn.execute(
        "UPDATE social_posts SET posted_on=?, status=?, posted_at=?, updated_at=datetime('now') WHERE id=?",
        (_json.dumps(sorted(already)), "posted" if all_done else row["status"],
         datetime.now().isoformat(timespec="minutes") if all_done else row["posted_at"], pid))
    conn.commit()
    out = conn.execute("SELECT * FROM social_posts WHERE id=?", (pid,)).fetchone()
    conn.close()
    return _row(out)


@router.delete("/api/social/posts/{pid}")
def delete_post(pid: int):
    conn = get_conn()
    conn.execute("DELETE FROM social_posts WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── available generated media to attach ─────────────────────────────────────
@router.get("/api/social/media")
def social_media(kind: Optional[str] = None, limit: int = 60):
    """Generated images + videos you can attach to a post."""
    conn = get_conn()
    out = []
    if kind in (None, "image"):
        for r in conn.execute(
            "SELECT id, image_path, prompt FROM designs WHERE image_path IS NOT NULL AND image_path!='' "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall():
            parts = str(r["image_path"]).split("/")
            fn = parts[-1]; sub = parts[-2] if len(parts) > 1 else "approved"
            out.append({"type": "image", "id": r["id"], "title": (r["prompt"] or fn)[:70],
                        "local_path": r["image_path"], "url": f"/designs/{sub}/{fn}"})
    if kind in (None, "video"):
        for r in conn.execute(
            "SELECT id, video_path, prompt FROM videos WHERE status='done' AND video_path IS NOT NULL AND video_path!='' "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall():
            fn = str(r["video_path"]).split("/")[-1]
            out.append({"type": "video", "id": r["id"], "title": (r["prompt"] or fn)[:70],
                        "local_path": r["video_path"], "url": f"/videos/{fn}"})
    conn.close()
    return {"count": len(out), "media": out}


# ── LLM caption + hashtag helper ────────────────────────────────────────────
class CaptionIn(BaseModel):
    topic: str
    platforms: list[str] = []
    tone: Optional[str] = "fun, playful, on-brand for Acme"


@router.post("/api/social/generate")
def generate_caption(req: CaptionIn):
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(400, "topic required")
    plats = ", ".join(PLATFORMS[x]["name"] for x in req.platforms if x in PLATFORMS) or "Instagram, TikTok"
    SYS = ("You are the social media manager for Acme, a playful indie shop selling geeky "
           "graphic tees, 3D-printable models, free software, and curated gadget deals. Write ONE "
           f"short, scroll-stopping caption for {plats} in a {req.tone} tone, then 8-12 relevant "
           "hashtags. Keep the caption under 300 characters, add 1-3 tasteful emoji. "
           'Return STRICT JSON: {"caption": "...", "hashtags": "#a #b #c"} and nothing else.')
    def _work():
        import re as _re
        raw = _call_lmstudio(get_prompt('social_caption').format(plats=plats, tone=req.tone),
                             topic, max_tokens=400, json_mode=True)
        raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        try:
            data = _json.loads(raw)
            cap = str(data.get("caption", "")).strip()
            tags = data.get("hashtags", "")
            tags = " ".join(tags) if isinstance(tags, list) else str(tags).strip()
        except Exception:
            # model didn't return clean JSON — salvage: first block = caption, #-words = tags
            cap = _re.sub(r"#\w+", "", raw).strip().strip('"')[:300]
            tags = " ".join(_re.findall(r"#\w+", raw))
        return {"caption": cap, "hashtags": tags, "topic": topic}
    tid = orch.submit_llm(_work, desc=f"Social caption: {topic[:40]}", task="social_caption")
    return {"task_id": tid}
