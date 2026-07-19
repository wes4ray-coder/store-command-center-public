"""Research Lab routes — Research Geniuses + research projects.

The engine (schema, pipeline, geniuses, prompts) lives in app/research_lab.py;
this router is the thin HTTP surface the Research tab talks to.
"""
import json as _json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, logger
import research_lab
import research_lab_deep
import research_lab_market

router = APIRouter()

_TOGGLES = {
    "research_autostart":     "on",
    "research_images":        "on",
    "research_gen_images":    "off",
    "research_auto_library":  "on",
    "research_peer_review":   "on",
    "research_shop_push":     "on",
    "research_recur_enabled": "on",
    "research_price_alerts":  "on",
}


def _row(r) -> dict:
    d = dict(r)
    for k in ("plan", "notes", "sources", "images", "review"):
        dflt = {} if k in ("plan", "review") else []
        try:
            d[k] = _json.loads(d[k]) if d.get(k) else dflt
        except Exception:
            d[k] = dflt
    d["has_report"] = bool(d.pop("report_md", "") or d["status"] == "done")
    return d


@router.get("/api/research/overview")
def research_overview():
    conn = get_conn()
    counts = {s: conn.execute("SELECT COUNT(*) FROM research_projects WHERE status=?", (s,)).fetchone()[0]
              for s in ("proposed", "running", "done", "failed")}
    conn.close()
    config = {k: (get_setting(k, d) or d) for k, d in _TOGGLES.items()}
    config["research_price_alert_pct"] = get_setting("research_price_alert_pct", "10") or "10"
    return {
        "geniuses": research_lab.geniuses(),
        "counts": counts,
        "config": config,
    }


class ProjectIn(BaseModel):
    title: str
    description: str = ""
    kind: str = ""


@router.post("/api/research/projects")
def propose_project(body: ProjectIn):
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "A project title is required")
    g = research_lab._assign_genius(title, body.description or "", body.kind or "")
    conn = get_conn()
    pid = conn.execute(
        "INSERT INTO research_projects (title,description,kind,genius_key,genius_name) "
        "VALUES (?,?,?,?,?)",
        (title[:200], (body.description or "").strip()[:4000], (body.kind or "").strip()[:40],
         g["key"], g["name"])).lastrowid
    conn.commit()
    conn.close()
    started = False
    if (get_setting("research_autostart", "on") or "on").lower() != "off":
        started = research_lab.start_project(pid)
    return {"id": pid, "genius": g["name"], "started": started}


@router.get("/api/research/projects")
def list_projects(status: str = ""):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM research_projects WHERE status=? ORDER BY id DESC",
                            (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM research_projects ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return {"projects": [_row(r) for r in rows]}


@router.get("/api/research/projects/{pid}")
def project_detail(pid: int):
    conn = get_conn()
    r = conn.execute("SELECT * FROM research_projects WHERE id=?", (pid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "No such research project")
    events = [dict(e) for e in conn.execute(
        "SELECT phase,message,created_at FROM research_events WHERE project_id=? "
        "ORDER BY id DESC LIMIT 40", (pid,)).fetchall()]
    qa = []
    for q in conn.execute("SELECT * FROM research_qa WHERE project_id=? ORDER BY id",
                          (pid,)).fetchall():
        qd = dict(q)
        if qd["status"] == "answered" and qd["answer"]:
            qd["answer_html"] = research_lab.render_report_html(qd["answer"])
        qa.append(qd)
    conn.close()
    d = _row(r)
    d["events"] = events
    d["qa"] = qa
    d["running"] = research_lab.is_running(pid)
    return d


@router.get("/api/research/projects/{pid}/report")
def project_report(pid: int):
    conn = get_conn()
    r = conn.execute("SELECT title,report_md,library_path,status FROM research_projects WHERE id=?",
                     (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    if not r["report_md"]:
        raise HTTPException(400, "This project has no report yet")
    return {"title": r["title"], "md": r["report_md"],
            "html": research_lab.render_report_html(r["report_md"]),
            "library_path": r["library_path"]}


@router.post("/api/research/projects/{pid}/start")
def start_project(pid: int):
    conn = get_conn()
    r = conn.execute("SELECT status FROM research_projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    if r["status"] == "running" or research_lab.is_running(pid):
        raise HTTPException(409, "This project is already being researched")
    ok = research_lab.start_project(pid)
    return {"ok": ok}


@router.post("/api/research/projects/{pid}/cancel")
def cancel_project(pid: int):
    conn = get_conn()
    r = conn.execute("SELECT status FROM research_projects WHERE id=?", (pid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "No such research project")
    if r["status"] not in ("running", "proposed"):
        conn.close()
        raise HTTPException(400, "Only a proposed/running project can be cancelled")
    conn.execute("UPDATE research_projects SET status='cancelled', phase_note='cancelled', "
                 "updated_at=datetime('now') WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True}


class AskIn(BaseModel):
    question: str


@router.post("/api/research/projects/{pid}/ask")
def ask_genius(pid: int, body: AskIn):
    """Ask-the-Genius: file a follow-up question on a finished report."""
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "Ask an actual question")
    conn = get_conn()
    r = conn.execute("SELECT status,report_md FROM research_projects WHERE id=?",
                     (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    if not r["report_md"]:
        raise HTTPException(400, "The report has to be finished before you can ask about it")
    return {"id": research_lab_deep.ask_question(pid, q)}


class DeeperIn(BaseModel):
    focus: str = ""


@router.post("/api/research/projects/{pid}/deeper")
def dig_deeper(pid: int, body: DeeperIn):
    """Dig deeper: follow-up research pass that rewrites the report as v2, v3, …"""
    conn = get_conn()
    r = conn.execute("SELECT status,report_md FROM research_projects WHERE id=?",
                     (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    if not r["report_md"]:
        raise HTTPException(400, "Finish the research first — there is no report to deepen")
    if r["status"] == "running" or research_lab.is_running(pid):
        raise HTTPException(409, "This project is already being researched")
    return {"ok": research_lab_deep.start_deeper(pid, (body.focus or "").strip()[:500])}


class SuggestIn(BaseModel):
    theme: str = ""


@router.post("/api/research/suggest")
def suggest_ideas(body: SuggestIn = SuggestIn()):
    """💡 ideas board — fresh project ideas (synchronous; rides the LLM queue)."""
    return {"ideas": research_lab_deep.suggest_ideas((body.theme or "").strip()[:200])}


def _project_with_report(pid: int):
    conn = get_conn()
    r = conn.execute("SELECT status,report_md FROM research_projects WHERE id=?",
                     (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    if not r["report_md"]:
        raise HTTPException(400, "Finish the research first — there is no report yet")
    return r


@router.get("/api/research/projects/{pid}/market")
def project_market(pid: int):
    """Materials, Money-tab filing state, recurrence and the price-watch series."""
    conn = get_conn()
    r = conn.execute("SELECT id FROM research_projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    return research_lab_market.market_info(pid)


@router.post("/api/research/projects/{pid}/shop")
def push_materials_to_money(pid: int):
    """File the report's materials into the Money tab as shop searches (deduped)."""
    _project_with_report(pid)
    return {"filed": research_lab_market.file_to_money(pid)}


@router.post("/api/research/projects/{pid}/pricecheck")
def run_price_check(pid: int):
    """Re-check current prices on the report's materials now (background pass)."""
    r = _project_with_report(pid)
    if r["status"] == "running" or research_lab.is_running(pid):
        raise HTTPException(409, "This project is already busy")
    return {"ok": research_lab_market.start_price_check(pid)}


class RecurIn(BaseModel):
    days: int = 0


@router.post("/api/research/projects/{pid}/recur")
def set_recurrence(pid: int, body: RecurIn):
    """Set the recurring-recheck cadence in days (0 = off, max 365)."""
    days = int(body.days or 0)
    if days < 0 or days > 365:
        raise HTTPException(400, "days must be between 0 (off) and 365")
    conn = get_conn()
    r = conn.execute("SELECT id FROM research_projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not r:
        raise HTTPException(404, "No such research project")
    research_lab_market.set_recurrence(pid, days)
    return {"ok": True, "days": days}


@router.delete("/api/research/projects/{pid}")
def delete_project(pid: int):
    if research_lab.is_running(pid):
        raise HTTPException(400, "Cancel the project before deleting it")
    conn = get_conn()
    n = conn.execute("DELETE FROM research_projects WHERE id=?", (pid,)).rowcount
    conn.execute("DELETE FROM research_events WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM research_qa WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM research_price_history WHERE project_id=?", (pid,))
    conn.execute("DELETE FROM research_price_alerts WHERE project_id=?", (pid,))
    conn.commit()
    conn.close()
    if not n:
        raise HTTPException(404, "No such research project")
    try:
        import shutil
        d = research_lab.RESEARCH_MEDIA / str(pid)
        if d.exists():
            shutil.rmtree(d)
    except Exception:
        pass
    return {"ok": True}


_FN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@router.get("/api/research/media/{pid}/{filename}")
def research_media(pid: int, filename: str):
    if not _FN_RE.match(filename) or ".." in filename:
        raise HTTPException(400, "Bad filename")
    path = (research_lab.RESEARCH_MEDIA / str(pid) / filename)
    if not path.is_file():
        raise HTTPException(404, "No such media file")
    return FileResponse(str(path), headers={"Cache-Control": "public, max-age=86400"})
