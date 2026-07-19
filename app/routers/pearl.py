"""Pearl (PRL) API — status, settings, wallet address, gated miner control.

The user asked about "Purl"; research identified it as Pearl (PRL), the
proof-of-useful-work L1 by Pearl Research Labs (see app/pearl.py for the full
verified findings + red flags). Everything here is read-only or config, except
the miner start/stop — which is hard-gated behind the pearl_mining_enabled
toggle and NEVER runs automatically. We never download or run third-party
binaries: the user installs the official software themselves (setup notes in
/api/crypto/pearl/research), this tab only talks to it.
"""
from fastapi import APIRouter, HTTPException, Body, Request

from deps import *          # get_setting, logger (kept consistent with siblings)
import pearl

router = APIRouter()


def _is_human(request: Request) -> bool:
    """A caller is the HUMAN only when they present an authenticated browser
    session. MCP tools / automation / cron reach the API through the localhost
    auth-bypass with no session — those are agent callers and need
    pearl_agent_access before they can touch the miner."""
    try:
        return bool(request.session.get("authenticated"))
    except Exception:
        return False


@router.get("/api/crypto/pearl/status")
def pearl_status():
    """Node + wallet + miner rollup. Graceful (never 5xx) when nothing is set up."""
    return pearl.status()


@router.get("/api/crypto/pearl/research")
def pearl_research():
    """The Phase-1 research findings: what Pearl actually is, evidence, red flags,
    and the exact install steps for the real software. Served verbatim to the UI."""
    return pearl.RESEARCH


@router.get("/api/crypto/pearl/settings")
def pearl_get_settings():
    return {"settings": pearl.settings_masked(),
            "secret_keys": sorted(pearl.SECRET_SETTINGS)}


@router.post("/api/crypto/pearl/settings")
def pearl_set_settings(body: dict = Body(...)):
    bad = [k for k in body if k not in pearl.SETTING_KEYS]
    if bad:
        raise HTTPException(400, f"Unknown key(s): {', '.join(bad)}")
    try:
        saved = pearl.save_settings(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "saved": saved, "mining_enabled": pearl.mining_enabled()}


@router.post("/api/crypto/pearl/address/new")
def pearl_new_address():
    """Fresh receive address from the user's own oyster wallet daemon."""
    try:
        return pearl.new_address()
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/api/crypto/pearl/miner/{action}")
def pearl_miner(action: str, request: Request):
    """start|stop the miner systemd --user unit on the GPU node. start is
    REFUSED while the pearl_mining_enabled toggle is off (403). Non-human callers
    (MCP/automation) are ALSO refused unless pearl_agent_access is on (403)."""
    try:
        return pearl.miner_action(action, by_agent=not _is_human(request))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
