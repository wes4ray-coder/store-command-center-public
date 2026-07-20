"""FreqTrade (DRY-RUN paper bot) lifecycle: proxy status, LLM strategy drafts,
the autonomous strategy hunt, the backtesting gate, and human approve/reject.

Drafts NEVER go live by themselves — a human approve moves a draft file into the
live strategies dir, and it is gated on a PASSING backtest unless force=true.
"""
import io
import json as _json
import os
import re as _re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, _call_lmstudio, _dec, logger
from services import *      # (kept consistent with sibling routers)

from ._base import (router, _container_status, _docker_env,
                    FT_API_URL, FT_CONTAINER, FT_USER_DATA, FT_STRATS, FT_DRAFTS)


# ── 🤖 freqtrade proxy ────────────────────────────────────────────────────────
_ft_jwt: dict = {"token": None, "exp": 0.0}   # cached JWT, ~5 min


def _ft_token() -> str:
    now = time.time()
    if _ft_jwt["token"] and _ft_jwt["exp"] > now:
        return _ft_jwt["token"]
    user = get_setting("ft_api_user", "") or ""
    pw   = get_setting("ft_api_pass", "") or ""
    if not user or not pw:
        raise RuntimeError("ft_api_user / ft_api_pass not set")
    r = httpx.post(f"{FT_API_URL}/api/v1/token/login", auth=(user, pw), timeout=8)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError("freqtrade login returned no access_token")
    _ft_jwt["token"], _ft_jwt["exp"] = tok, now + 300
    return tok


def _ft_get(path: str):
    r = httpx.get(f"{FT_API_URL}{path}",
                  headers={"Authorization": f"Bearer {_ft_token()}"}, timeout=10)
    if r.status_code == 401:            # stale JWT — refresh once
        _ft_jwt["token"] = None
        r = httpx.get(f"{FT_API_URL}{path}",
                      headers={"Authorization": f"Bearer {_ft_token()}"}, timeout=10)
    r.raise_for_status()
    return r.json()


@router.get("/api/crypto/trading")
def crypto_trading():
    container = _container_status(FT_CONTAINER)
    try:
        cfg = _ft_get("/api/v1/show_config")
        profit = {}
        try:
            p = _ft_get("/api/v1/profit")
            profit = {k: p.get(k) for k in (
                "profit_closed_coin", "profit_closed_percent_mean", "profit_all_coin",
                "profit_all_percent_mean", "trade_count", "closed_trade_count",
                "winning_trades", "losing_trades", "best_pair", "first_trade_date")}
        except Exception:
            pass
        try:
            open_trades = _ft_get("/api/v1/status")
            open_count = len(open_trades) if isinstance(open_trades, list) else 0
        except Exception:
            open_count = None
        try:
            whitelist = (_ft_get("/api/v1/whitelist") or {}).get("whitelist", [])
        except Exception:
            whitelist = cfg.get("exchange", {}).get("pair_whitelist", []) if isinstance(cfg.get("exchange"), dict) else []
        try:
            balance = (_ft_get("/api/v1/balance") or {}).get("total")
        except Exception:
            balance = None
        return {"configured": True, "container": container,
                "running": (cfg.get("state") == "running"),
                "dry_run": bool(cfg.get("dry_run", True)),
                "strategy": cfg.get("strategy"),
                "stake_currency": cfg.get("stake_currency"),
                "max_open_trades": cfg.get("max_open_trades"),
                "open_trade_count": open_count,
                "balance_total": balance,
                "whitelist": whitelist,
                "profit": profit}
    except Exception as e:
        return {"configured": False, "container": container, "error": str(e)[:200]}


# ── 🧠 LLM strategy drafts (never straight to live strategies/) ──────────────
STRATEGY_SYS = """You are an expert freqtrade strategy developer. Write ONE complete, \
valid freqtrade strategy file for the user's stated goal, intended for DRY-RUN (paper) \
testing only. Requirements:
- All needed imports (from freqtrade.strategy import IStrategy; import talib.abstract as ta \
is NOT available — use pandas / pandas_ta-free pure-pandas indicator math or \
`from technical import qtpylib` style helpers only if standard; prefer pure pandas).
- Exactly one class subclassing IStrategy, named in CamelCase after the goal.
- INTERFACE_VERSION = 3, a conservative minimal_roi dict, a stoploss (e.g. -0.05 to -0.10), \
timeframe (e.g. '5m' or '1h'), and startup_candle_count.
- Implement populate_indicators, populate_entry_trend and populate_exit_trend with clear, \
simple, defensible logic for the goal. Set 'enter_long' / 'exit_long' columns.
- Conservative defaults; no leverage, no shorts unless the goal demands it.
- Use ONLY hardcoded numeric thresholds. Do NOT use hyperopt parameters \
(IntParameter, DecimalParameter, CategoricalParameter, BooleanParameter) or a \
buy_params/sell_params block — they break plain backtesting. Every threshold must be a \
literal number in the code.
Return ONLY the Python code. No markdown fences, no commentary before or after."""


class ProposeIn(BaseModel):
    goal: str


def _generate_strategy_draft(goal: str) -> dict:
    """LLM-write a freqtrade IStrategy for `goal`, save it as a draft, return its
    row id + name. Shared by manual propose and the autonomous hunt."""
    user = f"Strategy goal: {goal}"
    try:
        # advisory colour from the oracle tournament's accuracy-weighted consensus
        # ('' when the oracle_company_hookup toggle is off). Drafts stay dry-run +
        # approval-gated regardless — this only informs the writing.
        from routers.oracle.consensus import brief as _oracle_brief
        ob = _oracle_brief()
        if ob:
            user += f"\n\nMARKET CONTEXT (advisory, not a command): {ob}"
    except Exception:
        pass
    code = _call_lmstudio(STRATEGY_SYS, user, max_tokens=3000)
    code = _re.sub(r"<think>.*?</think>", "", code, flags=_re.DOTALL).strip()
    m = _re.search(r"```(?:python)?\s*(.*?)```", code, flags=_re.DOTALL)
    if m:
        code = m.group(1).strip()
    cm = _re.search(r"class\s+([A-Za-z_]\w*)\s*\(\s*IStrategy", code)
    name = cm.group(1) if cm else f"DraftStrategy{datetime.now().strftime('%m%d%H%M%S')}"
    FT_DRAFTS.mkdir(parents=True, exist_ok=True)
    path = FT_DRAFTS / f"{name}.py"
    i = 2
    while path.exists():                       # never clobber an earlier draft
        path = FT_DRAFTS / f"{name}_{i}.py"
        i += 1
    path.write_text(code, encoding="utf-8")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO crypto_strategy_drafts (name,goal,code,status,notes) VALUES (?,?,?,?,?)",
        (path.stem, goal, code, "proposed", f"file: {path}"))
    conn.commit()
    did = cur.lastrowid
    conn.close()
    return {"id": did, "name": path.stem, "file": str(path), "goal": goal}


@router.post("/api/crypto/trading/strategy/propose")
def propose_strategy(req: ProposeIn):
    goal = (req.goal or "").strip()
    if not goal:
        raise HTTPException(400, "goal required")
    tid = orch.submit_llm(lambda: _generate_strategy_draft(goal),
                          desc=f"FT strategy: {goal[:40]}", priority=0)
    return {"task_id": tid}


# ── 🏁 autonomous strategy hunt: generate → backtest → leaderboard ────────────
STRATEGY_ARCHETYPES = [
    "RSI mean-reversion: buy deep oversold dips (RSI<30) in an uptrend, exit on RSI recovery, tight stop-loss",
    "EMA crossover trend-following: enter when fast EMA crosses above slow EMA with a higher-timeframe trend filter",
    "Bollinger Band bounce: enter near the lower band while price is above the 200 SMA, exit at the middle band",
    "MACD momentum: enter on a bullish MACD cross above the zero line, trail the winners, cut losers fast",
    "Breakout: enter on a candle close above the prior 24-hour high with a volatility (ATR) confirmation filter",
    "Donchian channel breakout with an ATR-based trailing stop and conservative position sizing",
    "Dual-indicator: RSI oversold AND price reclaiming the 50 EMA, take profit at a fixed 3% ROI",
    "Volume-momentum: enter when price and volume both rise over the last few candles, exit on momentum fade",
]

_hunt = {"running": False, "target": 0, "done": 0, "generated": 0,
         "passers": 0, "started_at": None, "log": [], "results": []}
_hunt_lock = threading.Lock()


def _wait_task(tid: int, timeout: float = 240) -> Optional[dict]:
    end = time.time() + timeout
    while time.time() < end:
        p = orch.poll(tid)
        if p["status"] == "done":
            return p.get("result")
        if p["status"] in ("failed", "error", "cancelled", "not_found"):
            return None
        time.sleep(2)
    return None


def _hunt_log(msg: str):
    _hunt["log"].append(msg)
    _hunt["log"][:] = _hunt["log"][-40:]
    logger.info("strategy hunt: %s", msg)


def _run_hunt(target: int):
    _hunt.update(running=True, target=target, done=0, generated=0, passers=0,
                 started_at=datetime.now().isoformat(timespec="seconds"),
                 log=[], results=[])
    try:
        for i in range(target):
            goal = STRATEGY_ARCHETYPES[i % len(STRATEGY_ARCHETYPES)]
            _hunt_log(f"[{i+1}/{target}] generating: {goal[:48]}…")
            tid = orch.submit_llm(lambda g=goal: _generate_strategy_draft(g),
                                  desc=f"hunt gen {i+1}/{target}", priority=2)  # background batch
            res = _wait_task(tid, 240)
            if not res or "id" not in res:
                _hunt_log(f"[{i+1}/{target}] generation failed — skipping")
                _hunt["done"] += 1
                continue
            _hunt["generated"] += 1
            did, name = res["id"], res["name"]
            _hunt_log(f"[{i+1}/{target}] backtesting {name}…")
            try:
                m = _run_backtest(name, False)
                conn = get_conn()
                conn.execute(
                    "INSERT OR REPLACE INTO crypto_backtests "
                    "(strategy_id,metrics,profit_pct,profit_factor,sharpe,passed,created_at) "
                    "VALUES (?,?,?,?,?,?,datetime('now'))",
                    (did, _json.dumps(m), m["profit_pct"], m["profit_factor"],
                     m["sharpe"], 1 if m["passed"] else 0))
                conn.commit()
                conn.close()
                if m["passed"]:
                    _hunt["passers"] += 1
                _hunt["results"].append({"id": did, "name": name, "metrics": m})
                _hunt_log(f"[{i+1}/{target}] {name}: {m['profit_pct']:+}% · "
                          f"{'✓ PASS' if m['passed'] else '✗ fail'}")
            except Exception as e:
                _hunt_log(f"[{i+1}/{target}] backtest failed: {str(e)[:80]}")
            _hunt["done"] += 1
        _hunt_log(f"hunt complete — {_hunt['passers']} passer(s) of {_hunt['generated']} generated")
    except Exception as e:
        _hunt_log(f"hunt aborted: {str(e)[:120]}")
    finally:
        _hunt["running"] = False


class HuntIn(BaseModel):
    count: int = 5


@router.post("/api/crypto/trading/hunt")
def start_hunt(req: HuntIn):
    """Autonomously generate `count` diverse strategies, backtest each on real
    history, and rank them. Runs in the background — poll /hunt/status."""
    with _hunt_lock:
        if _hunt["running"]:
            raise HTTPException(409, "A hunt is already running.")
        n = max(1, min(int(req.count or 5), 12))
        t = threading.Thread(target=_run_hunt, args=(n,), daemon=True, name="strategy-hunt")
        t.start()
    return {"ok": True, "target": n}


@router.get("/api/crypto/trading/hunt/status")
def hunt_status():
    return {k: _hunt[k] for k in
            ("running", "target", "done", "generated", "passers", "started_at", "log")}


@router.get("/api/crypto/trading/leaderboard")
def leaderboard():
    """All backtested strategies ranked best-first (passers, then profit factor,
    then profit %). This is where the hunt's winners surface for approval."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT d.id,d.name,d.goal,d.status,b.metrics,b.profit_pct,b.profit_factor,b.sharpe,b.passed "
        "FROM crypto_strategy_drafts d JOIN crypto_backtests b ON b.strategy_id=d.id "
        "WHERE d.status!='rejected'").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = _json.loads(d["metrics"])
        except Exception:
            d["metrics"] = {}
        out.append(d)
    out.sort(key=lambda x: (x["passed"], x["profit_factor"] or 0, x["profit_pct"] or 0), reverse=True)
    return {"leaderboard": out}


@router.get("/api/crypto/trading/strategies")
def list_strategies():
    conn = get_conn()
    drafts = [dict(r) for r in conn.execute(
        "SELECT id,name,goal,status,notes,created_at FROM crypto_strategy_drafts "
        "ORDER BY id DESC").fetchall()]
    bts = {r["strategy_id"]: dict(r) for r in conn.execute(
        "SELECT strategy_id,metrics,profit_pct,profit_factor,passed FROM crypto_backtests").fetchall()}
    conn.close()
    for d in drafts:
        bt = bts.get(d["id"])
        if bt:
            try:
                d["backtest"] = _json.loads(bt["metrics"])
            except Exception:
                d["backtest"] = {"profit_pct": bt["profit_pct"], "profit_factor": bt["profit_factor"],
                                 "passed": bool(bt["passed"])}
    active = sorted(f.name for f in FT_STRATS.glob("*.py")) if FT_STRATS.is_dir() else []
    return {"drafts": drafts, "active": active,
            "strategies_dir": str(FT_STRATS), "drafts_dir": str(FT_DRAFTS)}


@router.get("/api/crypto/trading/strategy/{sid}")
def get_strategy_draft(sid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Draft not found")
    return dict(row)


# ── 🧪 backtesting gate (prove a strategy on real history before it goes live) ──
BT_PAIRS   = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD"]
BT_DATADIR = "/freqtrade/user_data/data/coinbase"
BT_CONFIG  = "/freqtrade/user_data/backtest-config.json"
BT_RESULTS = FT_USER_DATA / "backtest_results"


def _ft_exec(args, timeout):
    return subprocess.run(["docker", "exec", FT_CONTAINER, "freqtrade", *args],
                          capture_output=True, text=True, timeout=timeout, env=_docker_env())


def _bt_passed(m: dict) -> bool:
    """A strategy 'passes' only if it made money with a real edge over the window."""
    return (m.get("trades", 0) >= 5 and m.get("profit_pct", 0) > 0
            and m.get("profit_factor", 0) > 1.0)


def _run_backtest(name: str, is_approved: bool) -> dict:
    from datetime import timedelta
    import zipfile as _zip
    tr = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d") + "-"
    # 1. refresh Coinbase history (incremental — only missing candles, a few seconds)
    _ft_exec(["download-data", "--exchange", "coinbase", "--timeframe", "1h",
              "--timerange", tr, "--pairs", *BT_PAIRS], timeout=240)
    # 2. backtest the draft (or the live copy) without touching the running bot
    spath = ("/freqtrade/user_data/strategies" if is_approved
             else "/freqtrade/user_data/strategies_drafts")
    r = _ft_exec(["backtesting", "--strategy", name, "--strategy-path", spath,
                  "--datadir", BT_DATADIR, "--timeframe", "1h", "--timerange", tr,
                  "--config", BT_CONFIG], timeout=300)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(tail[-1][:200] if tail else "backtest failed")
    # 3. read the newest result zip straight off the host-mounted dir
    zips = sorted(BT_RESULTS.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise RuntimeError("no backtest result produced")
    z = _zip.ZipFile(zips[0])
    main = [n for n in z.namelist()
            if n.endswith(".json") and "config" not in n and "market_change" not in n][0]
    strat = _json.loads(z.read(main)).get("strategy", {})
    if name not in strat:
        raise RuntimeError("strategy missing from backtest result")
    m = strat[name]
    out = {
        "trades":        m.get("total_trades"),
        "profit_pct":    round((m.get("profit_total") or 0) * 100, 2),
        "win_pct":       round((m.get("winrate") or 0) * 100, 1),
        "sharpe":        round(m.get("sharpe") or 0, 2),
        "profit_factor": round(m.get("profit_factor") or 0, 3),
        "max_dd_pct":    round((m.get("max_drawdown_account") or 0) * 100, 2),
        "final_balance": round(m.get("final_balance") or 0, 2),
        "timerange":     tr,
    }
    out["passed"] = _bt_passed(out)
    return out


@router.post("/api/crypto/trading/strategy/{sid}/backtest")
def backtest_strategy(sid: int):
    """Prove a strategy against ~180 days of real Coinbase history — no money, no
    live bot impact. Stores the result; approval is gated on a passing backtest."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Draft not found")
    d = dict(row)
    name = d["name"]
    is_approved = d["status"] == "approved"
    # make sure the strategy file exists where we'll point freqtrade
    fp = (FT_STRATS if is_approved else FT_DRAFTS) / f"{name}.py"
    if not fp.is_file():
        FT_DRAFTS.mkdir(parents=True, exist_ok=True)
        (FT_DRAFTS / f"{name}.py").write_text(d.get("code") or "", encoding="utf-8")
        is_approved = False
    try:
        res = _run_backtest(name, is_approved)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Backtest timed out (data download or run too slow).")
    except Exception as e:
        raise HTTPException(400, f"Backtest failed: {str(e)[:220]}")
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO crypto_backtests "
                 "(strategy_id,metrics,profit_pct,profit_factor,sharpe,passed,created_at) "
                 "VALUES (?,?,?,?,?,?,datetime('now'))",
                 (sid, _json.dumps(res), res["profit_pct"], res["profit_factor"],
                  res["sharpe"], 1 if res["passed"] else 0))
    conn.commit()
    conn.close()
    return {"ok": True, "metrics": res, "passed": res["passed"]}


@router.post("/api/crypto/trading/strategy/{sid}/approve")
def approve_strategy(sid: int, body: dict = Body(default={})):
    """Human approval: move the draft file into the LIVE strategies dir. GATED —
    a strategy must have a PASSING backtest first (profitable, profit-factor > 1,
    ≥5 trades) unless you pass force=true. FreqTrade still only trades it once you
    set it in its own config, and it stays paper money until dry_run is flipped."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Draft not found")
    bt = conn.execute("SELECT passed, profit_pct FROM crypto_backtests WHERE strategy_id=?",
                      (sid,)).fetchone()
    if not (body or {}).get("force"):
        if not bt:
            conn.close()
            raise HTTPException(400, "No backtest yet — run a backtest first, or pass force=true.")
        if not bt["passed"]:
            conn.close()
            raise HTTPException(400, f"Backtest did NOT pass (profit {bt['profit_pct']}%) — "
                                     f"this strategy loses money on history. Pass force=true to override.")
    d = dict(row)
    FT_STRATS.mkdir(parents=True, exist_ok=True)
    src = FT_DRAFTS / f"{d['name']}.py"
    dst = FT_STRATS / f"{d['name']}.py"
    try:
        if src.is_file():
            shutil.move(str(src), str(dst))
        else:                                   # draft file lost — rebuild from DB code
            dst.write_text(d.get("code") or "", encoding="utf-8")
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Could not move draft into strategies/: {e}")
    conn.execute("UPDATE crypto_strategy_drafts SET status='approved', notes=? WHERE id=?",
                 (f"approved → {dst}", sid))
    conn.commit()
    conn.close()
    return {"ok": True, "id": sid, "file": str(dst)}


@router.post("/api/crypto/trading/strategy/{sid}/reject")
def reject_strategy(sid: int):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone():
        conn.close()
        raise HTTPException(404, "Draft not found")
    conn.execute("UPDATE crypto_strategy_drafts SET status='rejected' WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return {"ok": True, "id": sid}
