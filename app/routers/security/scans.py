"""Findings + Pi-hole config-scan lifecycle (_run_scan, findings/scan endpoints)."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from deps import *
from ._base import router, _fkey, _score

REPORT_DIR  = BASE / "network-security" / "reports"
SCAN_SCRIPT = BASE / "network-security" / "scripts" / "pihole-security-scan.sh"
REPORT_PATH = REPORT_DIR / "SECURITY-REPORT.md"


def _parse_report(content: str) -> dict:
    """Extract verdict + findings from the markdown report."""
    status = "unknown"
    upper = content.upper()
    if "NEEDS ATTENTION" in upper:
        status = "needs_attention"
    elif "HEALTHY" in upper:
        status = "healthy"

    findings = []
    seen = set()
    lines = content.split("\n")

    def add(issue, action="", priority=""):
        issue = (issue or "").strip().strip("*").strip()
        if not issue or issue.lower() in ("issue", "issues found") or issue.startswith("-"):
            return
        k = _fkey(issue)
        if k in seen:
            return
        seen.add(k)
        findings.append({"issue": issue, "action": (action or "").strip(), "priority": (priority or "").strip()})

    # 1) Remediation Plan table:  | Priority | Issue | Action |
    in_table = False
    for ln in lines:
        if "Remediation Plan" in ln:
            in_table = True
            continue
        if in_table:
            if ln.startswith("## ") or ln.startswith("---") or ln.startswith("*Report"):
                in_table = False
                continue
            if "|" in ln:
                cols = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cols) >= 3 and cols[0].lower() not in ("priority", "") and not set(cols[0]) <= {"-", ":"}:
                    add(cols[1], cols[2], cols[0])

    # 2) "Issues found:" bullet list (Section 6)
    in_issues = False
    for ln in lines:
        if "Issues found" in ln:
            in_issues = True
            continue
        if in_issues:
            s = ln.strip()
            if s.startswith("## ") or s.startswith("---"):
                in_issues = False
                continue
            if s.startswith(("-", "*")) and len(s) > 2:
                add(s.lstrip("-* ").strip())

    return {"status": status, "findings": findings}


def _upsert_findings(parsed_findings):
    """Insert new findings as 'pending'; keep existing statuses on re-scan."""
    conn = get_conn()
    for f in parsed_findings:
        k = _fkey(f["issue"])
        row = conn.execute("SELECT id FROM security_findings WHERE fkey=?", (k,)).fetchone()
        if row:
            conn.execute("UPDATE security_findings SET issue=?, action=?, priority=?, updated_at=datetime('now') WHERE fkey=?",
                         (f["issue"], f["action"], f["priority"], k))
        else:
            conn.execute("INSERT INTO security_findings (fkey, issue, action, priority, status) VALUES (?,?,?,?, 'pending')",
                         (k, f["issue"], f["action"], f["priority"]))
    conn.commit()
    conn.close()


def _run_scan() -> dict:
    if not SCAN_SCRIPT.exists():
        raise HTTPException(404, f"Scan script not found at {SCAN_SCRIPT}")
    env = dict(os.environ)
    if PIHOLE_API_PASS:
        env["PIHOLE_API_PASS"] = PIHOLE_API_PASS
    env["PIHOLE_API_PORT"] = PIHOLE_API_PORT
    env["PIHOLE_CONTAINER"] = PIHOLE_CONTAINER
    result = subprocess.run(["bash", str(SCAN_SCRIPT)], capture_output=True, text=True, env=env, timeout=180)
    if not REPORT_PATH.exists():
        raise HTTPException(500, f"Scan finished (rc={result.returncode}) but no report was produced. {result.stderr[-300:]}")
    content = REPORT_PATH.read_text()
    parsed = _parse_report(content)
    _upsert_findings(parsed["findings"])
    conn = get_conn()
    conn.execute(
        "INSERT INTO security_scans (status, last_scan_at, report_path, summary_json) VALUES (?,?,?,?)",
        (parsed["status"], datetime.now().isoformat(), str(REPORT_PATH),
         json.dumps({"status": parsed["status"], "findings_parsed": len(parsed["findings"])})),
    )
    conn.commit()
    conn.close()
    return {"status": parsed["status"], "findings_parsed": len(parsed["findings"]), "score": _score()}


@router.get("/api/security/status")
def get_security_status():
    conn = get_conn()
    scan = conn.execute("SELECT * FROM security_scans ORDER BY created_at DESC LIMIT 1").fetchone()
    counts = {}
    for r in conn.execute("SELECT status, COUNT(*) c FROM security_findings GROUP BY status").fetchall():
        counts[r["status"]] = r["c"]
    conn.close()
    return {
        "status": scan["status"] if scan else "unknown",
        "last_scan": scan["last_scan_at"] if scan else None,
        "score": _score(),
        "counts": counts,
        "message": None if scan else "No scans performed yet.",
    }


@router.post("/api/security/scan")
def trigger_security_scan():
    try:
        return _run_scan()
    except HTTPException as e:
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Scan timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/security/findings")
def list_findings(status: str = ""):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM security_findings WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM security_findings ORDER BY "
                            "CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 "
                            "WHEN 'remediated' THEN 2 ELSE 3 END, updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/security/findings/{fid}/review")
def review_finding(fid: int, data: dict):
    new_status = (data or {}).get("status", "")
    if new_status not in ("pending", "approved", "ignored", "remediated"):
        raise HTTPException(400, "status must be pending|approved|ignored|remediated")
    conn = get_conn()
    cur = conn.execute("UPDATE security_findings SET status=?, updated_at=datetime('now') WHERE id=?", (new_status, fid))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if not changed:
        raise HTTPException(404, "Finding not found")
    return {"ok": True, "status": new_status, "score": _score()}


@router.get("/api/security/report")
def get_security_report():
    if REPORT_PATH.exists():
        conn = get_conn()
        scan = conn.execute("SELECT last_scan_at FROM security_scans ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.close()
        return {"report": REPORT_PATH.read_text(), "last_scan": scan["last_scan_at"] if scan else None}
    raise HTTPException(404, "No report found — run a scan first")
