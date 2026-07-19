"""
Web archive — self-contained page snapshots + time machine (split out of library.py).

Fetches a URL (fast HTTP → wget → the Store's persistent logged-in browser),
inlines its assets into a self-contained snapshot, and stores versioned captures.
Shares the SQLite connection helper with library-links via library_db.

Moved here VERBATIM from library.py — the fetch/capture (SSRF-relevant) logic is
unchanged, including its browser fallback behavior.
"""
import re, hashlib, base64
from pathlib import Path
from typing import Optional
from datetime import datetime
from urllib.parse import urljoin, urlparse
import httpx

from library_db import _get_db


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
