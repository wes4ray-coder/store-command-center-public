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


# ─── Re-exports: cohesive helpers split into sibling modules ─────────────────
# Keep `library.NAME` (and `from library import NAME`) working unchanged for the
# db / links / archive concerns now living in siblings. No import cycle: those
# siblings import only from library_db (and config), never back from here.
from library_db import DB_PATH, _get_db
from library_links import (
    add_link, list_links, get_link, review_link, delete_link, update_link,
)
from library_archive import (
    ARCHIVE_DIR, CHROME_BIN,
    capture_snapshot, save_uploaded_page, list_archived_sites, list_snapshots,
    get_snapshot_html, delete_snapshot, fetch_readable_text,
)
