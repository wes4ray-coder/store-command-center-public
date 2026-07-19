"""AI-shield, guardian, connections and audit/threats engine endpoints."""
from fastapi import HTTPException
import netwatch
import secaudit
import netguard
import aishield
from ._base import router


@router.get("/api/security/ai/surface")
def ai_surface():
    """Audit the AI attack surface — exposed model/tool endpoints + agent gates."""
    return {"checks": aishield.ai_surface()}


@router.get("/api/security/ai/bots")
def ai_bots():
    """Bot governance — good AI crawlers (allow), bad scrapers (block), raw clients."""
    return aishield.bots()


@router.post("/api/security/ai/scan")
def ai_scan(data: dict):
    """Scan arbitrary text/file content for prompt-injection / jailbreak / exfil."""
    return aishield.scan_injection((data or {}).get("text", ""))


@router.get("/api/security/ai/anomalies")
def ai_anomalies():
    """Agent-action anomaly watch — rogue-agent detection from the prayer queue."""
    return aishield.agent_anomalies()


@router.get("/api/security/guardian")
def security_guardian():
    """Fingerprint + auto-name devices, categorize their traffic, flag bad actors
    (trackers/ads/retry-loops) and recommend surgical blocks."""
    return netguard.analyze()


@router.post("/api/security/guardian/block")
def security_guardian_block(data: dict):
    """Block bad domains (Pi-hole deny). Never blocks functional/local — surgical + reversible."""
    return netguard.remediate(data.get("domains") or [], auto=False, device=data.get("device", ""))


@router.post("/api/security/guardian/unblock")
def security_guardian_unblock(data: dict):
    d = (data or {}).get("domain", "")
    if not d:
        raise HTTPException(400, "domain required")
    return netguard.unblock(d)


@router.post("/api/security/guardian/name")
def security_guardian_name(data: dict):
    mac = (data or {}).get("mac", "")
    name = (data or {}).get("name", "")
    if not mac or not name:
        raise HTTPException(400, "mac and name required")
    return netguard.set_name(mac, name)


@router.get("/api/security/guardian/actions")
def security_guardian_actions(limit: int = 50):
    return netguard.actions(limit)


@router.get("/api/security/connections")
def security_connections(enrich: bool = True):
    """Live who/what/where: external connections in & out, SSH attempts, exposed
    services + attack surface. This is the 'is it even doing anything' view.

    Cached ~10s: it shells out to `ss`, the sshd journal and geo lookups, so rapid
    tab re-opens don't re-run the whole scan."""
    from cache import cached
    return cached(f"sec:connections:{enrich}", 10, lambda: netwatch.connections(enrich=enrich))


@router.get("/api/security/audit")
def security_audit():
    """Hardening audit — patches, SSH, accounts, exposure, Docker, firewall —
    with a weighted score + letter grade (Lynis/CIS-style, native)."""
    return secaudit.audit()


@router.get("/api/security/web-traffic")
def security_web_traffic():
    """Who's hitting the public services (nginx-proxy-manager access logs):
    visitors, vhosts, status codes, and scanner/probe attempts."""
    return secaudit.web_traffic()


@router.get("/api/security/threats")
def security_threats():
    """Ranked attackers (SSH brute-force, web scanners) with a ready-to-run block
    command + fail2ban status."""
    return secaudit.threats()


@router.get("/api/security/events")
def security_events(limit: int = 40):
    """Scheduled-audit alert history + the security score trend."""
    return secaudit.events(limit)


@router.post("/api/security/audit/run")
def security_audit_run():
    """Take an audit snapshot now + diff vs the last (raises regression alerts)."""
    return secaudit.run_scheduled_audit()
