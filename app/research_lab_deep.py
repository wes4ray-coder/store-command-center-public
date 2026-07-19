"""Research Lab — the "after the report" features + smarter lab behaviour.

Everything here builds on the core pipeline in research_lab.py:
    peer_review(pid, body)   — a SECOND Genius reviews the draft; the author revises
                               (hooked into the pipeline behind the research_peer_review
                               toggle; the review verdict is stored on the project)
    ask_question(pid, q)     — "Ask the Genius": follow-up Q&A on a finished report,
                               answered in the background from the report + notes
    start_deeper(pid, focus) — "Dig deeper": a follow-up pass on a finished report —
                               plan follow-up searches, read new sources, REWRITE the
                               report as the next version (v2, v3, …)
    suggest_ideas(theme)     — the 💡 ideas board: fresh project ideas informed by
                               past projects (never repeats one)

All LLM calls go through research_lab._llm, so they ride the orchestrator queue at
priority=2 and honour the research model slot. research_lab is imported lazily
inside each function (same pattern as research_lab_media) — no import cycle.
"""
import json as _json
import re
import threading
from datetime import datetime

from db import get_conn


# ── prompts (registered in app/prompts.py via ref=("research_lab_deep", ...)) ──
REVIEW_SYS = (
    "You are a rigorous peer reviewer in a research lab. A fellow Research Genius wrote "
    "the draft report below for a practical project. Judge it for a DIY owner-operator: "
    "are the steps actually doable in order, are materials/costs concrete, are the safety "
    "warnings honest, is anything important missing or dubious? Reply with STRICT JSON "
    "and nothing else:\n"
    '{"verdict":"approve"|"revise",'
    '"strengths":["2-4 things the report does well"],'
    '"issues":["0-6 specific, actionable problems — empty if verdict is approve"],'
    '"summary":"one-sentence overall judgement"}'
)

REVISE_SYS = (
    "You are the Research Genius who wrote the draft report below. A peer reviewer raised "
    "specific issues. Rewrite the FULL report fixing every issue you can with the "
    "information at hand — keep the same markdown section structure, keep every image "
    "line (![...](...)) exactly where it helps, do not invent new facts, prices or URLs, "
    "and never write code. Reply with the complete revised markdown report only."
)

ANSWER_SYS = (
    "You are the Research Genius who wrote the report provided. The owner has a follow-up "
    "question about the project. Answer it concretely and honestly using the report and "
    "the research notes (plus common knowledge), in tight markdown — a few short "
    "paragraphs or bullets, a small table only if it genuinely helps. Keep real numbers "
    "and units where the notes have them, and say plainly when something would need "
    "fresh research. Never write code."
)

DEEPER_SYS = (
    "You are a research director planning a DEEPER follow-up pass on an already-"
    "researched project. Given the existing report and the owner's focus request, reply "
    "with STRICT JSON and nothing else:\n"
    '{"search_queries":["3-5 focused web queries that fill the report\'s gaps or dig into the requested focus"],'
    '"focus_note":"one sentence on what this deeper pass must add to the report"}'
)

SUGGEST_SYS = (
    "You are the Research Lab's ideas board. Suggest practical research projects for a "
    "hands-on DIY owner-operator (builds, home/farm improvements, side businesses, "
    "designs, crafts). Use the context — past projects and an optional theme — to "
    "suggest FRESH ideas; never repeat or lightly rephrase a past project. Reply with "
    "STRICT JSON and nothing else:\n"
    '{"ideas":[{"title":"short project title",'
    '"description":"1-2 sentences on scope and why it is worth doing",'
    '"kind":"build"|"business"|"design"|"other"}]}\n'
    "Give 4 to 6 ideas."
)


def _spawn(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True,
                     name=f"research-deep-{fn.__name__}").start()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


# ── peer review (pipeline hook) ───────────────────────────────────────────────
def peer_review(pid: int, body: str) -> str:
    """A different Genius reviews the draft; on 'revise' the author rewrites it.
    Returns the (possibly revised) report body; stores the review on the project."""
    import research_lab as rl
    p = rl._get(pid)
    if not p:
        return body
    others = [g for g in rl.geniuses() if g["key"] != p["genius_key"]] or rl.geniuses()
    rev = sorted(others, key=lambda g: (g.get("projects_active", 0),
                                        g.get("projects_done", 0)))[0]
    rl._set(pid, phase="review", progress=84, phase_note=f"{rev['name']} is peer-reviewing")
    rl._ev(pid, "review", f"{rev['name']} is peer-reviewing the draft…")
    raw = rl._llm("research_review",
                  f"PROJECT: {p['title']}\nAUTHOR: {p['genius_name']}\n\n"
                  f"DRAFT REPORT:\n{body[:9000]}",
                  max_tokens=900, desc=f"research review · {p['title'][:36]}")
    r = rl._parse_json(raw or "") or {}
    issues = [str(i).strip()[:300] for i in (r.get("issues") or []) if str(i).strip()][:6]
    verdict = "revise" if ((r.get("verdict") or "").lower() == "revise" and issues) else "approve"
    review = {"reviewer": rev["name"], "verdict": verdict,
              "strengths": [str(s).strip()[:200] for s in (r.get("strengths") or []) if str(s).strip()][:4],
              "issues": issues, "summary": str(r.get("summary") or "").strip()[:300]}
    rl._set(pid, review=_json.dumps(review))
    rl._world_note(rev.get("key", ""), rev["name"],
                   f"Peer-reviewed “{p['title']}” by {p['genius_name']} — {verdict}.",
                   thought="peer-reviewed a colleague's research", mood=3)
    if verdict == "approve":
        rl._ev(pid, "review", f"{rev['name']} approved the draft"
               + (f" — {review['summary']}" if review["summary"] else ""))
        return body
    rl._ev(pid, "review", f"{rev['name']} requested changes: " + "; ".join(issues)[:220])
    rl._set(pid, phase="revise", progress=88, phase_note=f"{p['genius_name']} is revising")
    revised = rl._llm("research_revise",
                      f"PROJECT: {p['title']}\n\nREVIEWER ISSUES:\n"
                      + "\n".join(f"- {i}" for i in issues)
                      + f"\n\nDRAFT REPORT:\n{body[:9000]}",
                      max_tokens=3600, desc=f"research revise · {p['title'][:36]}")
    revised = _strip_think(revised)
    if revised and len(revised) > max(200, len(body) // 3):
        rl._ev(pid, "revise", f"{p['genius_name']} revised the report after peer review")
        return revised
    rl._ev(pid, "revise", "revision came back too short — keeping the original draft")
    return body


# ── Ask the Genius (Q&A on a finished report) ────────────────────────────────
def _qa_set(qid: int, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    conn = get_conn()
    conn.execute(f"UPDATE research_qa SET {cols} WHERE id=?", (*fields.values(), qid))
    conn.commit()
    conn.close()


def ask_question(pid: int, question: str) -> int:
    """File a follow-up question; a background thread answers it. Returns the qa id."""
    conn = get_conn()
    row = conn.execute("SELECT genius_name FROM research_projects WHERE id=?",
                       (pid,)).fetchone()
    qid = conn.execute(
        "INSERT INTO research_qa (project_id,question,genius_name) VALUES (?,?,?)",
        (pid, question.strip()[:1000], row["genius_name"] if row else "")).lastrowid
    conn.commit()
    conn.close()
    _spawn(_answer_qa, qid)
    return qid


def _answer_qa(qid: int):
    import research_lab as rl
    conn = get_conn()
    q = conn.execute("SELECT * FROM research_qa WHERE id=?", (qid,)).fetchone()
    conn.close()
    if not q:
        return
    p = rl._get(q["project_id"])
    if not p or not (p.get("report_md") or "").strip():
        _qa_set(qid, status="failed",
                answer="This project has no finished report to answer from.")
        return
    notes = ""
    try:
        notes = "\n\n".join(n.get("digest", "")
                            for n in _json.loads(p["notes"] or "[]"))[:4000]
    except Exception:
        pass
    try:
        ans = rl._llm("research_answer",
                      f"PROJECT: {p['title']}\n\nREPORT:\n{p['report_md'][:9000]}\n\n"
                      f"RESEARCH NOTES:\n{notes or '(none)'}\n\n"
                      f"QUESTION: {q['question']}",
                      max_tokens=1200, desc=f"research Q&A · {p['title'][:36]}")
        ans = _strip_think(ans)
        if not ans:
            raise RuntimeError("the model returned an empty answer")
        _qa_set(qid, status="answered", answer=ans[:8000], answered_at=_now())
        rl._world_note(p["genius_key"], p["genius_name"],
                       f"Answered a follow-up question on “{p['title']}”.",
                       thought="helped with a follow-up question", mood=3)
    except Exception as e:
        rl.logger.warning("research qa #%d failed: %s", qid, e)
        _qa_set(qid, status="failed", answer=f"answer failed: {str(e)[:200]}")


# ── Dig deeper (versioned follow-up pass) ─────────────────────────────────────
def start_deeper(pid: int, focus: str = "") -> bool:
    """Kick a deeper pass on a finished report (daemon thread). False if busy."""
    import research_lab as rl
    with rl._lock:
        if pid in rl._running:
            return False
        rl._running.add(pid)
    rl._set(pid, status="running", phase="deeper", progress=4, error="",
            phase_note="planning the deeper pass")
    _spawn(_run_deeper, pid, focus)
    return True


def _run_deeper(pid: int, focus: str = ""):
    import research_lab as rl
    try:
        p = rl._get(pid)
        if not p or not (p.get("report_md") or "").strip():
            raise RuntimeError("no finished report to deepen — run the research first")
        title, gname = p["title"], p["genius_name"]
        old_md = p["report_md"]

        def _load(col, dflt):
            try:
                return _json.loads(p[col] or "") or dflt
            except Exception:
                return dflt
        notes, sources, images = _load("notes", []), _load("sources", []), _load("images", [])

        rl._world_note(p["genius_key"], gname, f"Digging deeper into “{title}”.",
                       thought="revisiting a project to dig deeper", mood=4)
        rl._ev(pid, "deeper", f"{gname} is planning the deeper pass"
               + (f" — focus: {focus[:100]}" if focus else ""))
        raw = rl._llm("research_deeper",
                      f"PROJECT: {title}\nFOCUS REQUEST: {focus or '(none — fill the gaps)'}\n\n"
                      f"CURRENT REPORT:\n{old_md[:8000]}",
                      max_tokens=500, desc=f"research deeper · {title[:36]}")
        dplan = rl._parse_json(raw or "") or {}
        queries = [str(q) for q in (dplan.get("search_queries") or []) if str(q).strip()][:5] \
                  or [f"{title} {focus}".strip()]
        focus_note = str(dplan.get("focus_note") or focus
                         or "fill the gaps in the report").strip()[:300]

        # search — only sources we have not already used
        rl._set(pid, phase="search", progress=20, phase_note="searching for the deeper pass")
        seen = {s.get("url") for s in sources if s.get("url")}
        hits = []
        for q in queries:
            if rl._cancelled(pid):
                return
            found = rl._searx(q, 5)
            for h in found:
                if h["url"] and h["url"] not in seen:
                    seen.add(h["url"])
                    hits.append(h)
            rl._ev(pid, "search", f"“{q}” → {len(found)} results")
        hits = hits[:12]

        # read new pages, appending to the existing notes
        rl._set(pid, phase="read", progress=40, phase_note="reading the new sources")
        import library
        added = 0
        for h in hits:
            if added >= 4 or rl._cancelled(pid):
                break
            try:
                pg_title, text = library.fetch_readable_text(h["url"])
            except Exception:
                continue
            if len(text) < 400:
                continue
            digest = rl._llm("research_digest",
                             f"PROJECT: {title}\nPAGE: {pg_title} ({h['url']})\n\n"
                             f"CONTENT:\n{text[:6000]}",
                             max_tokens=700, desc=f"research read · {pg_title[:36]}")
            if digest and "IRRELEVANT" not in digest[:40]:
                notes.append({"url": h["url"], "title": pg_title,
                              "digest": digest.strip()[:2500]})
                added += 1
                rl._ev(pid, "read", f"digested “{pg_title[:70]}”")
        all_sources = (sources + hits)[:40]
        rl._set(pid, notes=_json.dumps(notes), sources=_json.dumps(all_sources),
                progress=60, phase_note=f"{added} new sources digested")
        if rl._cancelled(pid):
            return

        # rewrite the report as the next version
        rl._set(pid, phase="write", progress=68, phase_note=f"{gname} is rewriting the report")
        img_list = "\n".join(f"[IMAGE:{i+1}] {im['caption']}" for i, im in enumerate(images)) \
                   or "(no images available — do not insert [IMAGE] markers)"
        note_txt = "\n\n".join(f"SOURCE: {n['title']} ({n['url']})\n{n['digest']}"
                               for n in notes[-9:])
        user = (f"PROJECT: {title}\nKIND: {p.get('kind') or 'other'}\n\n"
                f"DESCRIPTION:\n{p['description']}\n\n"
                f"This is a DEEPER-PASS REWRITE of an existing report. Goal of this pass: "
                f"{focus_note}\nImprove and extend the previous report with the new "
                f"research — keep everything that was already right.\n\n"
                f"PREVIOUS REPORT:\n{old_md[:7000]}\n\n"
                f"AVAILABLE IMAGES:\n{img_list}\n\n"
                f"RESEARCH NOTES (old + new):\n{note_txt or '(none)'}")
        body = rl._llm("research_report", user, max_tokens=3600,
                       desc=f"research deeper · {title[:36]}")
        if not body or len(body.strip()) < 200:
            raise RuntimeError("the model returned an empty/too-short report")
        body = _strip_think(body)

        def _img_md(m):
            i = int(m.group(1)) - 1
            if 0 <= i < len(images):
                im = images[i]
                return f"![{im['caption']}](/api/research/media/{pid}/{im['file']})"
            return ""
        body = re.sub(r"\[IMAGE:(\d+)\]", _img_md, body)

        if rl._toggle("research_peer_review", "on"):
            try:
                body = peer_review(pid, body)
            except Exception as e:
                rl._ev(pid, "review", f"peer review skipped: {str(e)[:120]}")

        p = rl._get(pid)
        md = rl._final_markdown(p, body, all_sources, images)
        lib_path = p.get("library_path") or ""
        if rl._toggle("research_auto_library", "on"):
            try:
                lib_path = rl._file_to_library(p, md)
                rl._ev(pid, "file", f"filed into the Library at {lib_path}")
            except Exception as e:
                rl._ev(pid, "file", f"library filing failed: {str(e)[:120]}")
        ver = int(p.get("version") or 1) + 1
        rl._set(pid, status="done", phase="done", progress=100, report_md=md,
                library_path=lib_path, version=ver,
                phase_note=f"deeper pass done (v{ver})",
                completed_at=_now())
        rl._ev(pid, "done", f"deeper pass complete — v{ver}, {added} new sources read")
        try:
            import research_lab_market
            research_lab_market.after_report(pid)
        except Exception as e:
            rl._ev(pid, "market", f"market step skipped: {str(e)[:120]}")
        rl._world_note(p["genius_key"], gname,
                       f"Published v{ver} of “{title}” after a deeper research pass.",
                       thought="improved a research report", mood=6)
    except Exception as e:
        import research_lab as rl2
        rl2.logger.error("research deeper #%d failed: %s", pid, e)
        rl2._set(pid, status="failed", error=str(e)[:300], phase_note="deeper pass failed")
        rl2._ev(pid, "error", str(e)[:200])
    finally:
        import research_lab as rl3
        with rl3._lock:
            rl3._running.discard(pid)


# ── the 💡 ideas board ────────────────────────────────────────────────────────
def suggest_ideas(theme: str = "") -> list:
    """Fresh project ideas informed by past projects. Synchronous (queued LLM call)."""
    import research_lab as rl
    conn = get_conn()
    past = [r["title"] for r in conn.execute(
        "SELECT title FROM research_projects ORDER BY id DESC LIMIT 20").fetchall()]
    conn.close()
    raw = rl._llm("research_suggest",
                  f"THEME (optional): {theme.strip() or '(none — your judgement)'}\n\n"
                  "PAST PROJECTS (do not repeat these):\n"
                  + ("\n".join(f"- {t}" for t in past) or "(none yet)"),
                  max_tokens=900, desc="research ideas board")
    d = rl._parse_json(raw or "") or {}
    out = []
    for i in (d.get("ideas") or [])[:6]:
        if not isinstance(i, dict):
            continue
        t = str(i.get("title") or "").strip()
        if t:
            out.append({"title": t[:200],
                        "description": str(i.get("description") or "").strip()[:500],
                        "kind": str(i.get("kind") or "").strip()[:40]})
    return out
