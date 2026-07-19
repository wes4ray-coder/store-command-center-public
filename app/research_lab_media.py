"""Research Lab — image collection + report rendering/filing.

Extracted verbatim from research_lab.py to keep that module under the size
budget. These are the media (searxng image search, optional GPU hero image) and
report-output (markdown → HTML, final-markdown assembly, library filing) helpers
of the research pipeline.

The pipeline orchestration and the core helpers (_cancelled/_searx/_ev) live in
research_lab.py; the two image helpers lazy-import it inside their bodies so
there is no import cycle (research_lab.py re-exports these names).
"""
import re
import shutil
from datetime import datetime
from html import escape as _hesc

import httpx

from config import DATA_DIR, STORE_BASE
from db import get_conn

RESEARCH_MEDIA = DATA_DIR / "research_media"


# ── images ────────────────────────────────────────────────────────────────────
def _download_image(pid: int, url: str, idx: int):
    """Fetch one image into the project's media folder. Returns filename or None."""
    try:
        with httpx.Client(follow_redirects=True, timeout=25,
                          headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}) as cl:
            r = cl.get(url)
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > 6_000_000:
                return None
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
                   "image/gif": "gif"}.get(ctype)
            if not ext:
                return None
            d = RESEARCH_MEDIA / str(pid)
            d.mkdir(parents=True, exist_ok=True)
            fn = f"img{idx}.{ext}"
            (d / fn).write_bytes(r.content)
            return fn
    except Exception:
        return None


def _fetch_images(pid: int, image_queries: list) -> list:
    """searxng image search → downloaded local files [{file, caption, source}]."""
    import research_lab
    images = []
    for iq in image_queries[:4]:
        if research_lab._cancelled(pid):
            return images
        for hit in research_lab._searx(iq, 6, categories="images"):
            src = hit.get("img_src") or ""
            if src.startswith("//"):
                src = "https:" + src
            if not src.startswith("http"):
                continue
            fn = _download_image(pid, src, len(images) + 1)
            if fn:
                images.append({"file": fn, "caption": iq, "source": hit.get("url") or src})
                research_lab._ev(pid, "images", f"fetched image for “{iq}”")
                break
    return images


def _generate_hero(pid: int, prompt: str, images: list):
    """Optional GPU hero image via the Studio pipeline (generations + run_generation).
    The auto-created designs-review row is removed — research media is not merch."""
    import research_lab
    try:
        import services
        conn = get_conn()
        gid = conn.execute(
            "INSERT INTO generations (prompt,product_type,width,height,steps,model,source) "
            "VALUES (?,?,?,?,?,?,?)",
            (prompt[:600], "Poster", 1024, 768, 20, None, "research")).lastrowid
        conn.commit()
        conn.close()
        research_lab._ev(pid, "images", "generating a hero illustration in the Studio…")
        services.run_generation(gid)         # blocking; handles GPU acquire/release
        conn = get_conn()
        row = conn.execute("SELECT status,image_path FROM generations WHERE id=?", (gid,)).fetchone()
        conn.execute("DELETE FROM designs WHERE generation_id=? AND source='research'", (gid,))
        conn.commit()
        conn.close()
        if row and row["status"] == "done" and row["image_path"]:
            d = RESEARCH_MEDIA / str(pid)
            d.mkdir(parents=True, exist_ok=True)
            fn = "hero.png"
            shutil.copyfile(row["image_path"], d / fn)
            images.insert(0, {"file": fn, "caption": "Concept illustration", "source": "studio"})
            research_lab._ev(pid, "images", "hero illustration generated")
    except Exception as e:
        research_lab._ev(pid, "images", f"hero generation skipped: {str(e)[:120]}")


# ── report rendering ──────────────────────────────────────────────────────────
def render_report_html(md: str) -> str:
    """Markdown report → display HTML. Reuses the library renderer, adding image
    support (the library one doesn't do ![...]); local media paths get STORE_BASE."""
    import library
    imgs = []

    def _stash(m):
        imgs.append((m.group(1), m.group(2)))
        return f"\x01IMG{len(imgs) - 1}\x01"

    tmp = re.sub(r'!\[([^\]]*)\]\(([^)\s]+)\)', _stash, md or "")
    html = library.render_markdown_simple(tmp)
    for i, (alt, src) in enumerate(imgs):
        if src.startswith("/api/"):
            src = STORE_BASE + src
        tag = (f'<img src="{_hesc(src, quote=True)}" alt="{_hesc(alt, quote=True)}" loading="lazy" '
               f'style="max-width:100%;max-height:420px;border-radius:8px;margin:10px 0;display:block;">')
        html = html.replace(f"\x01IMG{i}\x01", tag)
    return html


def _final_markdown(p: dict, body: str, sources: list, images: list) -> str:
    lines = [f"# {p['title']}", "",
             f"*Research report by {p['genius_name']} — the Research Lab, "
             f"{datetime.now().strftime('%Y-%m-%d')}.*", "",
             body.strip(), ""]
    if sources:
        lines += ["## Sources", ""]
        lines += [f"- [{s['title'] or s['url']}]({s['url']})" for s in sources if s.get("url")]
        lines += [""]
    credits = [i for i in images if i.get("source") and i["source"] not in ("studio",)]
    if credits:
        lines += ["## Image credits", ""]
        lines += [f"- {i['caption']} — {i['source']}" for i in credits]
        lines += [""]
    return "\n".join(lines)


def _file_to_library(p: dict, md: str) -> str:
    """Auto-file the finished report into the Library (category 'research')."""
    import library
    doc = library.save_library_doc("research", p["title"], md)
    return f"{doc['category']}/{doc['path']}"
