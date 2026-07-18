import os, re, json, sqlite3, hashlib, base64
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from urllib.parse import urljoin, urlparse
import httpx

LIBRARY_ROOT = Path(__file__).parent.parent / "app" / "library"

def _safe_path(category: str, *parts: str) -> Path:
    """Build a safe path inside the library, preventing directory traversal."""
    base = LIBRARY_ROOT / category
    target = base
    for p in parts:
        target = target / p
    # Resolve and verify it's still under the library root
    resolved = target.resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError("Path traversal detected")
    return resolved

def list_sections():
    """Return top-level library sections with file counts."""
    sections = []
    if not LIBRARY_ROOT.exists():
        return sections
    for item in sorted(LIBRARY_ROOT.iterdir()):
        if item.name.startswith('.') or not item.is_dir():
            continue
        md_count = sum(1 for f in item.rglob("*.md"))
        sections.append({"name": item.name, "documents": md_count})
    return sections

def list_subsections(category: str):
    """List subdirectories within a category."""
    base = LIBRARY_ROOT / category
    if not base.exists():
        return []
    subs = []
    for item in sorted(base.iterdir()):
        if item.is_dir():
            md_count = sum(1 for f in item.rglob("*.md"))
            subs.append({"name": item.name, "documents": md_count})
    return subs

def _doc_title(f: Path) -> str:
    """Best display title: first markdown heading, else a humanized stem, else
    the parent folder name (fixes 'REFERENCE'/'INDEX'-named files all looking alike)."""
    try:
        with f.open(encoding="utf-8") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                if line.startswith("# "):
                    return line[2:].strip()
    except Exception:
        pass
    stem = f.stem
    if stem.upper() in ("REFERENCE", "INDEX", "README"):
        return f.parent.name.replace("-", " ").replace("_", " ").title()
    return stem.replace("-", " ").replace("_", " ")

def list_documents(category: str, sub: Optional[str] = None):
    """List markdown documents directly in a category/subcategory (non-recursive so
    a category with subfolders doesn't flatten every nested file into the list)."""
    base = (LIBRARY_ROOT / category / sub) if sub else (LIBRARY_ROOT / category)
    if not base.exists():
        return []
    docs = []
    for f in sorted(base.glob("*.md")):
        # path is relative to the CATEGORY root so a reader can locate it at any depth
        rel = f"{sub}/{f.name}" if sub else f.name
        docs.append({
            "path": rel,
            "name": f.stem,
            "title": _doc_title(f),
            "size": f.stat().st_size,
        })
    return docs

def read_document(category: str, *parts: str) -> dict:
    """Read a markdown document and return its content + metadata."""
    path = _safe_path(category, *parts)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Document not found: {category}/{ '/'.join(parts) }")
    content = path.read_text(encoding="utf-8")
    title = path.stem
    # Try to extract first heading as title
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break
    # Count lines
    lines = content.count("\n")
    # Extract code language tags for syntax highlighting hints
    langs = set()
    for m in re.finditer(r"```(\w+)", content):
        langs.add(m.group(1))
    return {
        "title": title,
        "path": f"{category}/{'/'.join(parts)}",
        "line_count": lines,
        "languages": sorted(langs),
        "content": content,
    }

def search_library(query: str, category: Optional[str] = None):
    """Search library files using simple text matching."""
    results = []
    search_root = LIBRARY_ROOT / category if category else LIBRARY_ROOT
    if not search_root.exists():
        return results
    q = query.lower()
    for f in search_root.rglob("*.md"):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            matches = []
            for i, line in enumerate(lines):
                if q in line.lower():
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    context = "\n".join(lines[start:end])
                    matches.append({"line": i + 1, "context": context})
                    if len(matches) >= 5:
                        break
            if matches:
                rel = f.relative_to(LIBRARY_ROOT)
                results.append({
                    "path": str(rel),
                    "name": f.stem,
                    "match_count": len(matches),
                    "matches": matches[:5],
                })
        except Exception:
            continue
    results.sort(key=lambda r: r["match_count"], reverse=True)
    return results[:50]


# ─── LIBRARY LINKS (drop-link add & review system) ──────────────────────────────

try:
    from config import DB_PATH
except Exception:
    DB_PATH = Path(__file__).parent.parent / "store.db"

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def add_link(url: str, title: str = "", description: str = "", category: str = "", tags: str = "") -> dict:
    """Submit a new link to the library for review."""
    conn = _get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO library_links (url, title, description, category, tags) VALUES (?, ?, ?, ?, ?)",
        (url, title, description, category, tags)
    )
    conn.commit()
    link_id = c.lastrowid
    conn.close()
    return {"id": link_id, "url": url, "title": title, "status": "pending"}

def list_links(status: str = "pending") -> list:
    """List links by status (pending | approved | rejected | all)."""
    conn = _get_db()
    c = conn.cursor()
    if status == "all":
        c.execute("SELECT * FROM library_links ORDER BY created_at DESC")
    else:
        c.execute("SELECT * FROM library_links WHERE status = ? ORDER BY created_at DESC", (status,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_link(link_id: int) -> Optional[dict]:
    """Get a single link by ID."""
    conn = _get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM library_links WHERE id = ?", (link_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def review_link(link_id: int, status: str, page_content: str = None, page_path: str = None) -> dict:
    """Approve or reject a link. If approved, optionally save content to library."""
    conn = _get_db()
    c = conn.cursor()
    from datetime import datetime
    reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if page_content is not None:
        c.execute(
            "UPDATE library_links SET status = ?, page_content = ?, page_path = ?, reviewed_at = ? WHERE id = ?",
            (status, page_content, page_path, reviewed_at, link_id)
        )
    else:
        c.execute(
            "UPDATE library_links SET status = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewed_at, link_id)
        )
    conn.commit()
    conn.close()
    return {"id": link_id, "status": status}

def delete_link(link_id: int) -> bool:
    """Delete a link submission."""
    conn = _get_db()
    c = conn.cursor()
    c.execute("DELETE FROM library_links WHERE id = ?", (link_id,))
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return deleted

def update_link(link_id: int, title: str = None, description: str = None, category: str = None, tags: str = None) -> dict:
    """Update metadata on a link submission."""
    conn = _get_db()
    c = conn.cursor()
    fields = []
    vals = []
    for col, val in [("title", title), ("description", description), ("category", category), ("tags", tags)]:
        if val is not None:
            fields.append(f"{col} = ?")
            vals.append(val)
    if fields:
        vals.append(link_id)
        c.execute(f"UPDATE library_links SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()
    conn.close()
    return {"id": link_id, "updated": True}

def render_markdown_simple(content: str) -> str:
    """Convert markdown to simple HTML for display. Not a full parser, but handles
    common patterns: headings, bold, italic, code blocks, inline code, lists, links, hr."""
    import html as html_module
    # Escape HTML first
    text = html_module.escape(content)
    # Code blocks (``` ... ```)
    text = re.sub(r'```(\w*)\n([\s\S]*?)```',
        lambda m: f'<pre style="background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:12px;overflow:auto;font-size:.8rem;margin:10px 0;"><code>{m.group(2)}</code></pre>',
        text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code style="background:var(--surface);padding:1px 4px;border-radius:3px;font-size:.85em;">\1</code>', text)
    # Headings
    text = re.sub(r'^######\s+(.+)$', r'<h6>\1</h6>', text, flags=re.MULTILINE)
    text = re.sub(r'^#####\s+(.+)$', r'<h5>\1</h5>', text, flags=re.MULTILINE)
    text = re.sub(r'^####\s+(.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s+(.+)$', r'<h3 style="font-size:1.05rem;margin:16px 0 6px;">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+)$', r'<h2 style="font-size:1.2rem;margin:18px 0 8px;">\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+)$', r'<h1 style="font-size:1.4rem;margin:20px 0 10px;">\1</h1>', text, flags=re.MULTILINE)
    # Bold and italic
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em\1</em>', text)
    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" style="color:var(--accent);">\1</a>', text)
    # Horizontal rules
    text = re.sub(r'^---+$', r'<hr style="border:none;border-top:1px solid var(--border);margin:16px 0;">', text, flags=re.MULTILINE)
    # Unordered lists
    lines = text.split('\n')
    in_list = False
    result = []
    for line in lines:
        if re.match(r'^\s*[-*]\s+', line):
            if not in_list:
                result.append('<ul style="margin:6px 0 10px;padding-left:20px;">')
                in_list = True
            result.append(f'<li>{re.sub(r"^\\s*[-*]\\s+", "", line)}</li>')
        else:
            if in_list:
                result.append('</ul>')
                in_list = False
            result.append(line)
    if in_list:
        result.append('</ul>')
    text = '\n'.join(result)
    # Paragraphs (wrap blocks that aren't already HTML tags)
    blocks = text.split('\n\n')
    wrapped = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith('<') and not block.startswith('<code'):
            wrapped.append(block)
        else:
            wrapped.append(f'<p style="margin:6px 0;line-height:1.6;">{block}</p>')
    return '\n'.join(wrapped)


# ─── WEB ARCHIVE (self-contained page snapshots + time machine) ──────────────
try:
    from config import ARCHIVE_DIR
except Exception:
    ARCHIVE_DIR = Path(__file__).parent.parent / "archive"

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0.0.0 Safari/537.36")
_FETCH_HEADERS = {"User-Agent": _UA,
                  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                  "Accept-Language": "en-US,en;q=0.9"}
_MAX_INLINE_BYTES = 3_000_000   # skip inlining assets larger than ~3 MB


def _check_fetch(resp):
    if resp.status_code == 403:
        raise RuntimeError("the site blocked automated saving (403 — it likely uses "
                           "Cloudflare/bot protection). Snapshots work best on blogs, docs and articles.")
    if resp.status_code == 429:
        raise RuntimeError("the site rate-limited the request (429). Try again later.")
    resp.raise_for_status()


def _url_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _inline_assets(html: str, base_url: str, client: httpx.Client) -> str:
    """Best-effort self-containment: inline external CSS and images as data URIs and
    add a <base> tag so the snapshot renders offline without hitting the live site."""
    def fetch(u):
        try:
            full = urljoin(base_url, u)
            if not full.startswith(("http://", "https://")):
                return None
            r = client.get(full, timeout=15)
            if r.status_code == 200 and len(r.content) <= _MAX_INLINE_BYTES:
                return r
        except Exception:
            return None
        return None

    # Inline <link rel="stylesheet" href="...">
    def repl_css(m):
        href = m.group(1)
        r = fetch(href)
        if r is None:
            return m.group(0)
        return f"<style>/* {href} */\n{r.text}\n</style>"
    html = re.sub(r'<link[^>]+rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\'][^>]*>',
                  repl_css, html, flags=re.I)
    html = re.sub(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\'][^>]*rel=["\']stylesheet["\'][^>]*>',
                  repl_css, html, flags=re.I)

    # Inline <img src="...">
    def repl_img(m):
        pre, src, post = m.group(1), m.group(2), m.group(3)
        if src.startswith("data:"):
            return m.group(0)
        r = fetch(src)
        if r is None:
            return m.group(0)
        ctype = r.headers.get("content-type", "image/png").split(";")[0]
        b64 = base64.b64encode(r.content).decode()
        return f'<img {pre}src="data:{ctype};base64,{b64}"{post}>'
    html = re.sub(r'<img\s+([^>]*?)src=["\']([^"\']+)["\']([^>]*?)>', repl_img, html, flags=re.I)

    # Neutralize scripts (snapshots are static) and add <base> for anything left.
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.I)
    if "<base" not in html.lower():
        html = re.sub(r'(<head[^>]*>)', rf'\1<base href="{base_url}">', html, count=1, flags=re.I)
    return html


import shutil as _shutil
import subprocess as _subprocess
import tempfile as _tempfile

try:
    from config import CHROME_BIN
except Exception:
    CHROME_BIN = "google-chrome"

_CF_MARKERS = ("just a moment", "cf-challenge", "challenge-platform",
               "checking your browser", "cf-browser-verification", "enable javascript and cookies")


def _chrome_path():
    for b in (CHROME_BIN, "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = _shutil.which(b)
        if p:
            return p
    return None


def _chrome_dump(url: str, wait_ms: int = 9000):
    """Render a page with headless Chrome and return the post-JS DOM (or None)."""
    binpath = _chrome_path()
    if not binpath:
        return None
    with _tempfile.TemporaryDirectory() as ud:
        cmd = [binpath, "--headless=new", "--disable-gpu", "--no-sandbox", "--mute-audio",
               f"--user-data-dir={ud}", f"--user-agent={_UA}",
               "--dump-dom", f"--virtual-time-budget={wait_ms}", url]
        try:
            r = _subprocess.run(cmd, capture_output=True, text=True, timeout=wait_ms / 1000 + 40)
            html = r.stdout
            return html if html and len(html) > 300 else None
        except Exception:
            return None


def _looks_blocked(html: str) -> bool:
    low = (html or "")[:5000].lower()
    return any(m in low for m in _CF_MARKERS)


def _wget_fetch(url: str):
    """Native wget fetch — fast, no browser. Won't pass JS/Cloudflare challenges, but
    great for plain articles/docs and when Chrome isn't available."""
    wget = _shutil.which("wget")
    if not wget:
        return None
    try:
        r = _subprocess.run(
            [wget, "-q", "-O", "-", "--timeout=25", "--tries=2", "--max-redirect=10",
             f"--user-agent={_UA}", "--header=Accept-Language: en-US,en;q=0.9", url],
            capture_output=True, text=True, timeout=45)
        out = r.stdout
        return out if out and len(out) > 300 else None
    except Exception:
        return None


def _browser_capture(url: str):
    """Grab the fully-rendered DOM from the Store's PERSISTENT logged-in Chrome (the one
    you sign into for resale). Because it carries your real session/cookies, it sails past
    Cloudflare where the throwaway --dump-dom can't. Returns (html, final_url) or (None,url)."""
    try:
        import browser as _b
        tab = _b.browser.open(url, headless=False)
        time.sleep(7)   # let JS render + any Cloudflare check clear
        html = tab.eval_js("document.documentElement.outerHTML")
        return (html if html and len(html) > 300 else None), (tab.url() or url)
    except Exception:
        return None, url


def capture_snapshot(url: str, deep: bool = False) -> dict:
    """Fetch a URL, make it self-contained, and store it as a new snapshot version.
    Tries a fast HTTP fetch first; falls back to headless Chrome for JS-heavy or
    lightly-protected pages. `deep=True` uses Chrome directly."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    with httpx.Client(headers=_FETCH_HEADERS, follow_redirects=True) as client:
        html, base_url, fetch_err = None, url, None
        if not deep:
            # 1. fast HTTP fetch
            try:
                resp = client.get(url, timeout=30)
                _check_fetch(resp)
                html, base_url = resp.text, str(resp.url)
                if _looks_blocked(html):
                    html = None
            except Exception as e:
                fetch_err = e
            # 2. native wget fallback (no browser)
            if html is None:
                w = _wget_fetch(url)
                if w and not _looks_blocked(w):
                    html, base_url, fetch_err = w, url, None
        # 3. the Store's persistent logged-in browser — real session beats Cloudflare
        if html is None:
            rendered, rurl = _browser_capture(url)
            if rendered and not _looks_blocked(rendered):
                html, base_url = rendered, rurl
            elif rendered and _looks_blocked(rendered):
                raise RuntimeError(
                    "This site's Cloudflare challenge didn't clear even in the Store browser. "
                    "Open Resell → Launch Browser, sign in / pass the check on this site once "
                    "(cookies persist), then re-save — or use “Upload saved page (.html)”.")
        if html is None:
            raise fetch_err or RuntimeError("could not fetch the page")

        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = (title_m.group(1).strip() if title_m else urlparse(url).netloc)[:200]
        html = _inline_assets(html, base_url, client)

    return _store_snapshot(url, title, html)


def _store_snapshot(url: str, title: str, html: str) -> dict:
    """Write an HTML string as a new archive version + index it. Shared by the
    auto-snapshot and the manual .html upload."""
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    (ARCHIVE_DIR / _url_key(url)).mkdir(parents=True, exist_ok=True)
    rel_path = f"{_url_key(url)}/{ts}.html"
    (ARCHIVE_DIR / rel_path).write_text(html, encoding="utf-8")
    conn = _get_db()
    c = conn.cursor()
    c.execute("INSERT INTO archive_snapshots (url, title, rel_path, size) VALUES (?,?,?,?)",
              (url, title, rel_path, len(html)))
    conn.commit()
    sid = c.lastrowid
    conn.close()
    return {"id": sid, "url": url, "title": title, "rel_path": rel_path, "size": len(html)}


def save_uploaded_page(html: str, url: str = "", title: str = "") -> dict:
    """Store a page the user saved in their own browser (Firefox/Chrome → 'Save Page As'
    → .html). This sidesteps Cloudflare/bot-protection entirely because a real, logged-in
    browser did the saving. Scripts are neutralized for safe iframe display; a <base> is
    added (when a source URL is given) so relative CSS/images resolve to the live site."""
    if not html or len(html) < 50:
        raise ValueError("The uploaded file looks empty — save the page as HTML and try again.")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = (m.group(1).strip() if m else (urlparse(url).netloc if url else "Uploaded page"))[:200]
    if not url:
        url = "upload://" + hashlib.sha256((title + str(len(html))).encode()).hexdigest()[:16]
    safe = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.I)
    if url.startswith("http") and "<base" not in safe.lower():
        safe = re.sub(r'(<head[^>]*>)', rf'\1<base href="{url}">', safe, count=1, flags=re.I)
    return _store_snapshot(url, title, safe)


def list_archived_sites() -> list:
    """One row per archived URL with its version count and latest capture."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT url,
               COUNT(*)            AS versions,
               MAX(captured_at)    AS latest,
               (SELECT title FROM archive_snapshots s2 WHERE s2.url = s1.url
                 ORDER BY captured_at DESC LIMIT 1) AS title,
               (SELECT id FROM archive_snapshots s3 WHERE s3.url = s1.url
                 ORDER BY captured_at DESC LIMIT 1) AS latest_id
        FROM archive_snapshots s1
        GROUP BY url ORDER BY latest DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_snapshots(url: str) -> list:
    """All versions of one URL, newest first (the time machine)."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, url, title, size, captured_at FROM archive_snapshots WHERE url=? ORDER BY captured_at DESC",
        (url,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshot_html(snapshot_id: int) -> Optional[str]:
    conn = _get_db()
    row = conn.execute("SELECT rel_path FROM archive_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    conn.close()
    if not row:
        return None
    p = ARCHIVE_DIR / row["rel_path"]
    return p.read_text(encoding="utf-8") if p.exists() else None


def delete_snapshot(snapshot_id: int) -> bool:
    conn = _get_db()
    row = conn.execute("SELECT rel_path FROM archive_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if not row:
        conn.close()
        return False
    try:
        (ARCHIVE_DIR / row["rel_path"]).unlink(missing_ok=True)
    except Exception:
        pass
    conn.execute("DELETE FROM archive_snapshots WHERE id=?", (snapshot_id,))
    conn.commit()
    conn.close()
    return True


def fetch_readable_text(url: str) -> tuple:
    """Fetch a URL and return (title, plain-ish text) for feeding to the local model."""
    with httpx.Client(headers=_FETCH_HEADERS, follow_redirects=True) as client:
        resp = client.get(url, timeout=30)
        _check_fetch(resp)
        html = resp.text
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = (title_m.group(1).strip() if title_m else urlparse(url).netloc)[:200]
    body = re.sub(r'<(script|style|nav|footer|header|aside)[\s\S]*?</\1>', ' ', html, flags=re.I)
    body = re.sub(r'<[^>]+>', ' ', body)
    body = re.sub(r'&[a-z]+;', ' ', body)
    body = re.sub(r'\s+', ' ', body).strip()
    return title, body[:12000]


def save_library_doc(category: str, name: str, markdown: str) -> dict:
    """Write a markdown doc into the library (used by 'rip to library')."""
    safe_cat = re.sub(r'[^a-z0-9_-]', '', category.lower()) or "saved"
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:60] or "untitled"
    folder = LIBRARY_ROOT / safe_cat
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.md"
    n = 2
    while path.exists():
        path = folder / f"{slug}-{n}.md"
        n += 1
    path.write_text(markdown, encoding="utf-8")
    return {"category": safe_cat, "path": path.name, "title": name}


# ─── LIBRARY MANAGEMENT: import, audit, metadata ─────────────────────────────
import shutil

try:
    from config import LIBRARY_IMPORT_DIRS
except Exception:
    LIBRARY_IMPORT_DIRS = [str(LIBRARY_ROOT.parent.parent)]

_IMPORT_SKIP = ("/app/library/", "/venv/", "/.git/", "/backups/", "/__pycache__/",
                "/node_modules/", "/static/", "/designs/", "/videos/", "/archive/", "/app/")


def import_folder_docs(dest_category: str = "imported") -> dict:
    """Copy loose markdown from the configured source folders into the library."""
    imported, skipped = [], 0
    for root in LIBRARY_IMPORT_DIRS:
        root = Path(root)
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            s = str(f) + "/"
            if any(x in s for x in _IMPORT_SKIP):
                continue
            try:
                rel = f.relative_to(root)
            except ValueError:
                rel = Path(f.name)
            dest = LIBRARY_ROOT / dest_category / rel
            try:
                if dest.exists() and dest.read_text(errors="ignore") == f.read_text(errors="ignore"):
                    skipped += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                imported.append(str(Path(dest_category) / rel))
            except Exception:
                continue
    return {"imported": imported, "count": len(imported), "skipped": skipped}


def audit_library() -> dict:
    """Fast health report over the library (no model)."""
    import hashlib
    cats, all_docs = {}, []
    if LIBRARY_ROOT.exists():
        for item in sorted(LIBRARY_ROOT.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            docs = list(item.rglob("*.md"))
            cats[item.name] = len(docs)
            all_docs.extend(docs)
    tiny, seen, dupes = [], {}, []
    newest = oldest = None
    for f in all_docs:
        st = f.stat()
        relp = str(f.relative_to(LIBRARY_ROOT))
        if st.st_size < 200:
            tiny.append(relp)
        try:
            h = hashlib.md5(f.read_bytes()).hexdigest()
            if h in seen:
                dupes.append([relp, seen[h]])
            else:
                seen[h] = relp
        except Exception:
            pass
        if newest is None or st.st_mtime > newest[1]:
            newest = (relp, st.st_mtime)
        if oldest is None or st.st_mtime < oldest[1]:
            oldest = (relp, st.st_mtime)
    return {
        "categories": cats,
        "total": len(all_docs),
        "empty_categories": [c for c, n in cats.items() if n == 0],
        "tiny_docs": tiny[:30],
        "duplicates": dupes[:30],
        "newest": newest[0] if newest else None,
        "oldest": oldest[0] if oldest else None,
    }


def doc_metadata(category: str, *parts: str) -> dict:
    """Structural metadata for a document: size, words, headings outline, links."""
    path = _safe_path(category, *parts)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Document not found")
    content = path.read_text(encoding="utf-8", errors="ignore")
    headings = []
    for line in content.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            headings.append({"level": len(m.group(1)), "text": m.group(2).strip()})
    links = [{"text": t, "url": u} for t, u in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", content)]
    return {
        "path": f"{category}/{'/'.join(parts)}",
        "size": path.stat().st_size,
        "words": len(content.split()),
        "lines": content.count("\n") + 1,
        "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "headings": headings[:60],
        "links": links[:60],
    }


def read_doc_raw(category: str, *parts: str) -> tuple:
    """Return (path_obj, content) for a doc — used by enrich/summarize."""
    path = _safe_path(category, *parts)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Document not found")
    return path, path.read_text(encoding="utf-8", errors="ignore")
