"""JellyCoin (JLY) API — the store's own GPU-mined token + NFTs + agent missions.

Endpoints (chain logic lives in jellycoin.py):
  - /api/jelly/status, /blocks, /wallets, /transfer, /tip — ledger + explorer.
  - /api/jelly/mining/work + /submit — the getwork protocol for GPU rigs. These
    two (plus the miner download) are reachable from OTHER LAN boxes without a
    session (main.py bypass) but self-guard with the X-Jelly-Token header
    against settings.jelly_miner_token — same pattern as /api/money/signals.
    There is NO CPU mining: the server only VERIFIES hashes, and the shipped
    miner refuses to start without an OpenCL GPU.
  - /api/jelly/nft/* — mint real art files as NFTs (content-hash on chain).
  - /api/jelly/missions/* — LLM-drafted "push JLY" pitches from the Company.
    Drafts NEVER act on their own: every mission sits in 'proposed' until the
    god (you) approves or rejects it. Approval posts it to the town feed so
    agents can talk it up in-world; nothing external is auto-posted.
"""
import secrets
import hmac
from pathlib import Path

from fastapi import APIRouter, HTTPException, Body, Request
from fastapi.responses import FileResponse

from deps import *          # get_conn, get_setting, _call_lmstudio, logger
import jellycoin
from prompts import get_prompt
from world_defs import run_llm_job

router = APIRouter()

MINER_TOKEN_KEY = "jelly_miner_token"
_MINER_FILE = Path(__file__).resolve().parent.parent.parent / "miner" / "jellyminer.py"


def _miner_token() -> str:
    tok = get_setting(MINER_TOKEN_KEY)      # get_setting transparently decrypts
    if not tok:
        import crypto as _secrets_at_rest   # app/crypto.py — settings encryption
        tok = secrets.token_hex(16)
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (MINER_TOKEN_KEY, _secrets_at_rest.enc(tok)))
        conn.commit()
        conn.close()
    return tok


def _check_miner(request: Request):
    """LAN rigs authenticate with X-Jelly-Token; same-box calls ride the localhost bypass."""
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "testclient"):
        return
    if not hmac.compare_digest(request.headers.get("X-Jelly-Token", ""), _miner_token()):
        raise HTTPException(403, "bad or missing X-Jelly-Token")


# ── chain / ledger ───────────────────────────────────────────────────────────
@router.get("/api/jelly/status")
def jelly_status():
    return jellycoin.status()


@router.get("/api/jelly/blocks")
def jelly_blocks(limit: int = 25):
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT height,hash,time,miner,reward,boost,nonce FROM jelly_blocks "
                            "ORDER BY height DESC LIMIT ?", (max(1, min(200, limit)),)).fetchall()
        return {"blocks": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/api/jelly/wallets")
def jelly_wallets():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT name,address,balance,kind,created_at FROM jelly_wallets "
                            "ORDER BY balance DESC, name").fetchall()
        txs = conn.execute("SELECT * FROM jelly_txs ORDER BY id DESC LIMIT 40").fetchall()
        return {"unit": jellycoin.UNIT,
                "wallets": [dict(r) for r in rows],
                "recent_txs": [dict(r) for r in txs]}
    finally:
        conn.close()


@router.post("/api/jelly/transfer")
def jelly_transfer(payload: dict = Body(...)):
    try:
        return jellycoin.transfer(
            str(payload.get("from", "")).strip(), str(payload.get("to", "")).strip(),
            int(float(payload.get("amount_jly", 0)) * jellycoin.UNIT),
            memo=str(payload.get("memo", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/jelly/tip")
def jelly_tip(payload: dict = Body(...)):
    """The AI friend's tip jar → send JLY from the 'assistant' wallet (MCP-callable)."""
    try:
        return jellycoin.transfer(
            jellycoin.ASSISTANT, str(payload.get("to", "")).strip(),
            int(float(payload.get("amount_jly", 0)) * jellycoin.UNIT),
            memo=str(payload.get("memo", "tip from your AI friend")), kind="tip")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/jelly/stats")
def jelly_stats(points: int = 160):
    """Chart series derived from the block table: difficulty, block interval,
    cumulative supply (each downsampled to ≤`points`), plus blocks per rig."""
    points = max(10, min(500, points))
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT height,time,target,reward,boost,miner FROM jelly_blocks "
                            "ORDER BY height").fetchall()
        per_rig = [dict(r) for r in conn.execute(
            "SELECT miner, COUNT(*) blocks FROM jelly_blocks WHERE height>0 "
            "GROUP BY miner ORDER BY blocks DESC LIMIT 8")]
    finally:
        conn.close()
    series = []
    supply = 0
    for i, r in enumerate(rows):
        supply += int(r["reward"]) + int(r["boost"])
        series.append({
            "h": int(r["height"]), "t": int(r["time"]),
            "difficulty": round(jellycoin.difficulty(int(r["target"], 16)), 2),
            "interval": (int(r["time"]) - int(rows[i - 1]["time"])) if i else None,
            "supply": round(supply / jellycoin.UNIT, 2),
        })
    if len(series) > points:                      # keep first/last, stride the middle
        step = len(series) / points
        series = [series[int(i * step)] for i in range(points - 1)] + [series[-1]]
    return {"series": series, "per_rig": per_rig,
            "target_block_sec": jellycoin.TARGET_BLOCK_SEC}


_DOCS = {"whitepaper": "WHITEPAPER.md", "security": "SECURITY.md"}
_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "jellycoin"


@router.get("/api/jelly/doc/{name}")
def jelly_doc(name: str):
    """Serve the JellyCoin white paper / security-protocol docs (markdown, read-only)."""
    fn = _DOCS.get(name)
    if not fn or not (_DOCS_DIR / fn).is_file():
        raise HTTPException(404, f"doc must be one of {sorted(_DOCS)}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse((_DOCS_DIR / fn).read_text(encoding="utf-8"),
                             media_type="text/markdown")


# ── mining (LAN-reachable, token-guarded; GPU rigs only — server never mines) ─
@router.get("/api/jelly/mining/work")
def jelly_work(request: Request, miner: str, gpu: str = "", hashrate: float = 0.0):
    _check_miner(request)
    try:
        return jellycoin.get_work(miner, gpu=gpu, hashrate=hashrate)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/jelly/mining/submit")
def jelly_submit(request: Request, payload: dict = Body(...)):
    _check_miner(request)
    res = jellycoin.submit_work(str(payload.get("work_id", "")),
                                int(payload.get("nonce", 0)),
                                str(payload.get("miner", "")))
    if res.get("ok") and res.get("wallet"):                 # winner-take-all block
        logger.info(f"[jelly] block {res['height']} mined by {res['wallet']} (+{res['reward']} JLY)")
    elif res.get("block"):                                  # pool block (reward split)
        logger.info(f"[jelly] pool block {res['height']} split (+{res.get('reward', 0)} JLY)")
    return res


@router.get("/api/jelly/mining/miner.py")
def jelly_miner_download(request: Request):
    _check_miner(request)
    if not _MINER_FILE.is_file():
        raise HTTPException(404, "miner script missing from install")
    return FileResponse(str(_MINER_FILE), media_type="text/x-python", filename="jellyminer.py")


@router.get("/api/jelly/miner-token")
def jelly_miner_token():
    """Session-only: show the token + a copy-paste command to start a rig on any LAN box."""
    tok = _miner_token()
    return {"token": tok,
            "run": (f"python3 jellyminer.py --url http://127.0.0.1:8787 "
                    f"--token {tok} --name $(hostname)")}


# ── buddy-share compute billing (peers federation) ───────────────────────────
@router.get("/api/jelly/peer-billing")
def jelly_peer_billing():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        peers = [dict(r) for r in conn.execute(
            "SELECT name,balance FROM jelly_wallets WHERE kind='peer' ORDER BY balance DESC")]
        comped = conn.execute("SELECT COUNT(*) c FROM jelly_txs WHERE kind='compute_comped'").fetchone()["c"]
    finally:
        conn.close()
    return {"enabled": jellycoin.peer_billing_enabled(),
            "price_jly": jellycoin.peer_job_price("llm") / jellycoin.UNIT,
            "embedding_price_jly": jellycoin.peer_job_price("embedding") / jellycoin.UNIT,
            "peer_wallets": peers, "comped_jobs": int(comped)}


@router.post("/api/jelly/peer-billing")
def jelly_peer_billing_set(payload: dict = Body(...)):
    conn = get_conn()
    try:
        if "enabled" in payload:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (jellycoin.PEER_BILLING_KEY, "1" if payload["enabled"] else "0"))
        if "price_jly" in payload:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (jellycoin.PEER_PRICE_KEY, str(max(0.0, float(payload["price_jly"])))))
        conn.commit()
    finally:
        conn.close()
    return jelly_peer_billing()


# ── buddy-share mining pool (proportional reward splitting; toggle default OFF) ─
@router.get("/api/jelly/pool")
def jelly_pool():
    return jellycoin.pool_state()


@router.post("/api/jelly/pool")
def jelly_pool_set(payload: dict = Body(...)):
    """God-side controls (session-guarded — NOT in the mining exemption): flip the
    pool toggle and/or map named rigs to payout wallets (e.g. rig → peer:<name>)."""
    if "enabled" in payload:
        jellycoin.set_pool_enabled(bool(payload["enabled"]))
    owners = payload.get("owners") or {}
    if isinstance(owners, dict):
        for rig, owner in owners.items():
            try:
                jellycoin.set_rig_owner(str(rig), str(owner))
            except ValueError:
                pass
    return jellycoin.pool_state()


# ── NFTs ─────────────────────────────────────────────────────────────────────
@router.post("/api/jelly/nft/mint")
def jelly_nft_mint(payload: dict = Body(...)):
    path = str(payload.get("file_path", "")).strip()
    title = str(payload.get("title", "")).strip() or Path(path).stem
    owner = str(payload.get("owner", jellycoin.TREASURY)).strip() or jellycoin.TREASURY
    try:
        return jellycoin.mint_nft(owner, path, title, meta={
            "artist": str(payload.get("artist", "Acme Studio")),
            "note": str(payload.get("note", ""))[:300]})
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/jelly/nft/list")
def jelly_nft_list():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT * FROM jelly_nfts ORDER BY id DESC LIMIT 100").fetchall()
        return {"nfts": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/jelly/nft/transfer")
def jelly_nft_transfer(payload: dict = Body(...)):
    try:
        return jellycoin.transfer_nft(str(payload.get("token_id", "")),
                                      str(payload.get("from", "")), str(payload.get("to", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── missions: agents push/sell JLY — always behind god approval ──────────────
_MISSION_KINDS = {"promo": "a social/blog promo pitch for JellyCoin",
                  "perk": "a 'pay/earn with JLY' perk idea for the example.com store",
                  "sell": "an in-community offer to sell/swap a small JLY bundle"}


@router.post("/api/jelly/missions/draft")
def jelly_mission_draft(payload: dict = Body(default={})):
    kind = str(payload.get("kind", "promo"))
    if kind not in _MISSION_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(_MISSION_KINDS)}")
    st = jellycoin.status()
    user = (f"Mission kind: {kind} — {_MISSION_KINDS[kind]}.\n"
            f"Chain facts: height {st['height']}, supply {st['supply']:.0f} JLY, "
            f"{st['miners_online']} GPU rig(s) online, {st['nft_count']} NFTs minted.\n"
            "Write the pitch now.")
    title, pitch = f"JLY {kind} pitch", ""
    try:
        # through the unified queue — the orch loads the model (with idle-TTL) and
        # the draft shows up as a queue entry instead of a bare JIT call
        raw = run_llm_job(lambda: _call_lmstudio(get_prompt("jelly_mission"), user, max_tokens=700),
                          "jelly:mission-draft", wait=240)
        pitch = (raw or "").strip()
        if pitch:
            title = pitch.splitlines()[0].strip("# ").strip()[:80] or title
    except Exception as e:
        logger.warning(f"[jelly] mission LLM draft failed, using template: {e}")
    if not pitch:
        pitch = (f"JellyCoin ({st['symbol']}) is Acme's own GPU-mined token — "
                 f"{st['supply']:.0f} JLY minted across {st['height']} real proof-of-work blocks. "
                 f"Old graphics cards earn it, the Company's crew boosts it, and our art becomes "
                 f"NFTs on it. Idea ({kind}): spotlight one NFT and offer a small JLY reward "
                 "for community members who share it.")
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        cur = conn.execute("INSERT INTO jelly_missions (kind,title,pitch,agent) VALUES (?,?,?,?)",
                           (kind, title, pitch, str(payload.get("agent", "the Company"))[:60]))
        conn.commit()
        return {"ok": True, "id": cur.lastrowid, "title": title, "pitch": pitch, "status": "proposed"}
    finally:
        conn.close()


@router.get("/api/jelly/missions")
def jelly_missions():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT * FROM jelly_missions ORDER BY id DESC LIMIT 50").fetchall()
        return {"missions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/jelly/missions/{mission_id}/decide")
def jelly_mission_decide(mission_id: int, payload: dict = Body(...)):
    approve = bool(payload.get("approve"))
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        row = conn.execute("SELECT * FROM jelly_missions WHERE id=?", (mission_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown mission")
        if row["status"] != "proposed":
            raise HTTPException(400, f"already {row['status']}")
        status = "approved" if approve else "rejected"
        conn.execute("UPDATE jelly_missions SET status=?, decided_at=datetime('now') WHERE id=?",
                     (status, mission_id))
        conn.commit()
    finally:
        conn.close()
    if approve:
        try:
            from world_defs import log_town
            log_town(f"📣 The god approved a JellyCoin {row['kind']} mission: {row['title']}")
        except Exception:
            pass
    return {"ok": True, "id": mission_id, "status": status}
