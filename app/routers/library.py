"""library routes."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse
from deps import *
from services import *
import library   # archive/rip helpers not re-exported via deps

router = APIRouter()


@router.get("/api/library/sections")
def library_sections():
    """List all top-level library sections."""
    return {"sections": list_sections()}

@router.get("/api/library/search")
def library_search(q: str = "", category: Optional[str] = None):
    """Search across the entire library or within a category."""
    if not q:
        raise HTTPException(400, "Query parameter 'q' is required")
    return {"query": q, "results": search_library(q, category)}

@router.post("/api/library/links")
def library_add_link(body: dict):
    """Submit a new link to the library for review."""
    url = body.get("url", "").strip()
    if not url or not url.startswith("http"):
        raise HTTPException(400, "Valid URL required")
    link = add_link(
        url=url,
        title=body.get("title", "").strip(),
        description=body.get("description", "").strip(),
        category=body.get("category", "").strip(),
        tags=body.get("tags", "").strip(),
    )
    return {"ok": True, "link": link}

@router.get("/api/library/links")
def library_list_links(status: str = "pending"):
    """List link submissions by status."""
    return {"links": list_links(status)}

@router.get("/api/library/links/{link_id}")
def library_get_link(link_id: int):
    """Get a single link with full details."""
    link = get_link(link_id)
    if not link:
        raise HTTPException(404, "Link not found")
    return link

@router.patch("/api/library/links/{link_id}")
def library_update_link(link_id: int, body: dict):
    """Update link metadata (title, description, category, tags)."""
    return update_link(link_id, **{k: v for k, v in body.items() if k in ("title", "description", "category", "tags")})

@router.post("/api/library/links/{link_id}/review")
def library_review_link(link_id: int, body: dict):
    """Approve or reject a link. If approved, optionally save fetched content."""
    status = body.get("status", "approved")
    if status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be 'approved' or 'rejected'")
    page_content = body.get("page_content")
    page_path = body.get("page_path")
    result = review_link(link_id, status, page_content, page_path)
    return {"ok": True, "link": result}

@router.delete("/api/library/links/{link_id}")
def library_delete_link(link_id: int):
    """Delete a link submission."""
    if not delete_link(link_id):
        raise HTTPException(404, "Link not found")
    return {"ok": True}

@router.get("/api/library/render")
def library_render_markdown(content: str = ""):
    """Render markdown to HTML (for preview)."""
    if not content:
        raise HTTPException(400, "Content parameter required")
    return {"html": render_markdown_simple(content)}

@router.get("/api/library/read")
def library_read(category: str, path: str):
    """Read a document by category + category-relative path (unambiguous, any depth).
    Fixes docs at top level or in sub-folders resolving to the listing route instead."""
    try:
        doc = read_document(category, *[p for p in path.split("/") if p])
        doc["html"] = render_markdown_simple(doc["content"])
        return doc
    except FileNotFoundError:
        raise HTTPException(404, "Document not found")
    except ValueError:
        raise HTTPException(400, "Invalid path")


# ─── WEB ARCHIVE (snapshots + time machine) ──────────────────────────────────
# NOTE: these specific routes MUST be declared before the /{category} catch-alls
# below, or FastAPI would match "archive" as a category.
@router.post("/api/library/archive")
def archive_page(body: dict):
    """Capture a self-contained snapshot of a URL (a new version each time).
    body.deep=true forces a full headless-browser render."""
    url = (body or {}).get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Valid http(s) URL required")
    try:
        return library.capture_snapshot(url, deep=bool((body or {}).get("deep")))
    except Exception as e:
        raise HTTPException(502, f"Could not save page: {e}")

@router.post("/api/library/archive/upload")
async def archive_upload(file: UploadFile = File(...), url: str = Form(""), title: str = Form("")):
    """Archive a page the user saved in their own browser ('Save Page As' → .html).
    Works on sites that block automated snapshots (Cloudflare etc.)."""
    name = (file.filename or "").lower()
    if not (name.endswith(".html") or name.endswith(".htm") or name.endswith(".mhtml")):
        raise HTTPException(400, "Upload a saved .html page (File → Save Page As in your browser).")
    raw = await file.read()
    if len(raw) > 25_000_000:
        raise HTTPException(400, "That page is over 25 MB — save it as 'HTML only' rather than 'complete'.")
    try:
        html = raw.decode("utf-8", errors="replace")
    except Exception:
        html = raw.decode("latin-1", errors="replace")
    try:
        return library.save_uploaded_page(html, url=url.strip(), title=title.strip())
    except Exception as e:
        raise HTTPException(400, f"Could not save the uploaded page: {e}")

@router.get("/api/library/archive")
def archive_list():
    """One entry per archived URL (with version counts) — the archive index."""
    return {"sites": library.list_archived_sites()}

@router.get("/api/library/archive/versions")
def archive_versions(url: str):
    """All captured versions of a URL, newest first (the time machine)."""
    return {"url": url, "versions": library.list_snapshots(url)}

@router.get("/api/library/archive/{snapshot_id}/view", include_in_schema=False)
def archive_view(snapshot_id: int):
    """Serve the saved snapshot HTML for display inside an in-store iframe."""
    html = library.get_snapshot_html(snapshot_id)
    if html is None:
        raise HTTPException(404, "Snapshot not found")
    return HTMLResponse(html)

@router.delete("/api/library/archive/{snapshot_id}")
def archive_delete(snapshot_id: int):
    if not library.delete_snapshot(snapshot_id):
        raise HTTPException(404, "Snapshot not found")
    return {"ok": True}


# ─── AI LIBRARY: rip a page to markdown via the local model ──────────────────
_RIP_SYSTEM = (
    "You are a documentation archivist. Convert the given web page text into a clean, "
    "well-structured Markdown reference document for offline study and recall. Start with a "
    "single '# Title' line, keep the useful content (headings, steps, code, key facts), drop "
    "nav/ads/boilerplate. Output ONLY Markdown."
)

@router.post("/api/library/rip")
def library_rip(body: dict):
    """Fetch a URL, then queue an LLM job (via the orchestrator, which loads the local
    model) to turn it into a Markdown library doc. Returns {task_id} to poll."""
    url = (body or {}).get("url", "").strip()
    category = (body or {}).get("category", "saved").strip() or "saved"
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Valid http(s) URL required")
    try:
        title, text = library.fetch_readable_text(url)
    except Exception as e:
        raise HTTPException(502, f"Could not fetch page: {e}")

    def _work():
        md = _call_lmstudio(get_prompt('library_rip'), f"Source URL: {url}\n\nPage text:\n{text}", max_tokens=2000).strip()
        if not md.startswith("#"):
            md = f"# {title}\n\n{md}"
        md = f"{md}\n\n---\n*Archived from {url}*"
        return {"doc": library.save_library_doc(category, title, md)}

    tid = orch.submit_llm(_work, desc=f"Rip: {title[:40]}", task="library_rip")
    return {"task_id": tid}


# ─── Agent-assisted: research a topic into a guide via the OpenClaw local model ─
@router.post("/api/library/guide")
def library_guide(body: dict):
    """Ask the OpenClaw agent (local model, web-search tools) to research a topic and
    return a Markdown guide, saved to the library."""
    topic = (body or {}).get("topic", "").strip()
    category = (body or {}).get("category", "guides").strip() or "guides"
    if not topic:
        raise HTTPException(400, "topic required")
    prompt = (
        f"Research this topic and write a thorough, well-structured how-to guide in Markdown: "
        f"\"{topic}\". Use web search if helpful. Start with a single '# Title' heading. "
        f"Output ONLY the Markdown guide, no preamble."
    )
    try:
        result = subprocess.run(
            [OPENCLAW_BIN, "agent", "--agent", OPENCLAW_AGENT,
             "--session-key", "store-library", "--message", prompt, "--json"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise HTTPException(502, f"Agent error: {(result.stderr or '')[:300]}")
        data = json.loads(result.stdout)
        payloads = data.get("payloads") or []
        md = " ".join(p.get("text", "") for p in payloads if p.get("text")) if payloads \
            else (data.get("reply") or data.get("text") or "")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Agent timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Agent error: {e}")
    md = (md or "").strip()
    if not md:
        raise HTTPException(502, "Agent returned no content")
    doc = library.save_library_doc(category, topic, md)
    return {"ok": True, "doc": doc}


# ─── Auto-populate: import folder docs + AI generation ──────────────────────
@router.post("/api/library/import")
def library_import(body: dict = None):
    """Import loose markdown from the configured source folders into the library."""
    category = ((body or {}).get("category") or "imported").strip() or "imported"
    return library.import_folder_docs(category)


# ─── Audit ───────────────────────────────────────────────────────────────────
@router.get("/api/library/audit")
def library_audit():
    """Fast health report (categories, counts, empty/tiny/duplicate docs)."""
    return library.audit_library()

_GAP_SYSTEM = (
    "You are a knowledge-base curator. Given a library's categories and document counts, "
    "suggest what's MISSING or worth adding/updating for a self-hosted print-on-demand + "
    "network-security operation. Output a short Markdown list of concrete suggested docs/topics. "
    "Be specific and practical. Markdown only."
)

@router.post("/api/library/audit/ai")
def library_audit_ai():
    """Local model reviews the library structure and suggests gaps. Returns {task_id}."""
    a = library.audit_library()
    summary = f"Total docs: {a['total']}\nCategories: " + ", ".join(f"{c}({n})" for c, n in a["categories"].items())
    def _work():
        md = _call_lmstudio(get_prompt('library_gap'), summary, max_tokens=1200).strip()
        doc = library.save_library_doc("audits", "Library Gap Analysis", md or "_No suggestions._")
        return {"doc": doc, "suggestions": md}
    tid = orch.submit_llm(_work, desc="Library gap analysis", task="library_gap")
    return {"task_id": tid}


# ─── Detail triggers: metadata, enrich, summarize ────────────────────────────
@router.get("/api/library/meta")
def library_meta(category: str, path: str):
    """Structural metadata for a document (words, headings outline, links)."""
    try:
        return library.doc_metadata(category, *[p for p in path.split("/") if p])
    except FileNotFoundError:
        raise HTTPException(404, "Document not found")

_ENRICH_SYSTEM = (
    "You are a technical writer. Expand and improve the given Markdown document: add missing "
    "detail, concrete examples, clarifying structure and steps, while preserving all existing "
    "facts and the original intent. Keep the same top '# Title'. Output ONLY the improved Markdown."
)
_SUMMARY_SYSTEM = (
    "You are a study aid. For the given document, produce a concise TL;DR (2-3 sentences) and a "
    "bulleted 'Key points' list (max 8). Output ONLY Markdown starting with '## TL;DR'."
)

def _doc_llm_job(category: str, path: str, system: str, mode: str):
    try:
        path_obj, content = library.read_doc_raw(category, *[p for p in path.split("/") if p])
    except FileNotFoundError:
        raise HTTPException(404, "Document not found")

    def _work():
        out = _call_lmstudio(system, content[:12000], max_tokens=2500).strip()
        if mode == "enrich":
            path_obj.write_text(out or content, encoding="utf-8")
            return {"updated": f"{category}/{path}", "mode": "enrich"}
        else:  # summarize — prepend the summary block to the doc
            new = f"{out}\n\n---\n\n{content}"
            path_obj.write_text(new, encoding="utf-8")
            return {"updated": f"{category}/{path}", "mode": "summarize"}
    return {"task_id": orch.submit_llm(_work, desc=f"{mode}: {path[:40]}", task=("library_enrich" if mode == "enrich" else "library_summary"))}

@router.post("/api/library/enrich")
def library_enrich(body: dict):
    cat, path = (body or {}).get("category", ""), (body or {}).get("path", "")
    if not cat or not path:
        raise HTTPException(400, "category and path required")
    return _doc_llm_job(cat, path, get_prompt('library_enrich'), "enrich")

@router.post("/api/library/summarize")
def library_summarize(body: dict):
    cat, path = (body or {}).get("category", ""), (body or {}).get("path", "")
    if not cat or not path:
        raise HTTPException(400, "category and path required")
    return _doc_llm_job(cat, path, get_prompt('library_summary'), "summarize")


# ─── Category browsing (catch-alls — keep LAST) ──────────────────────────────
@router.get("/api/library/{category}")
def library_category(category: str, sub: Optional[str] = None):
    """List subsections or documents in a category."""
    subs = list_subsections(category)
    docs = list_documents(category, sub)
    return {"category": category, "subsections": subs, "documents": docs}

@router.get("/api/library/{category}/{sub}")
def library_subcategory(category: str, sub: str):
    """List documents in a subcategory."""
    docs = list_documents(category, sub)
    return {"category": category, "subcategory": sub, "documents": docs}

@router.get("/api/library/{category}/{sub}/{path:path}")
def library_document(category: str, sub: str, path: str):
    """Read a document, returning pre-rendered HTML (avoids passing the whole file
    back through a GET query param, which blew past URL length limits → NetworkError)."""
    parts = [sub] + path.split("/")
    try:
        doc = read_document(category, *parts)
        doc["html"] = render_markdown_simple(doc["content"])
        return doc
    except FileNotFoundError:
        raise HTTPException(404, "Document not found")
    except ValueError:
        raise HTTPException(400, "Invalid path")
