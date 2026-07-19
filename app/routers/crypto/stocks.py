"""Stocks: Robinhood portfolio (read-only), a yfinance watchlist, and an LLM
daily brief (SMA20/50 + RSI14 signals). Not financial advice."""
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

from ._base import router


# ── 📈 stocks: robinhood portfolio ────────────────────────────────────────────
_rh_state = {"logged_in": False}


def _rh_login():
    """Lazy import + cached login. Import inside so a missing lib never breaks the app."""
    import robin_stocks.robinhood as rh
    if _rh_state["logged_in"]:
        return rh
    user = get_setting("rh_username", "") or ""
    pw   = get_setting("rh_password", "") or ""
    if not user or not pw:
        raise RuntimeError("Robinhood credentials not set")
    mfa_code = None
    secret = get_setting("rh_mfa_secret", "") or ""
    if secret:
        import pyotp
        mfa_code = pyotp.TOTP(secret).now()
    rh.login(user, pw, mfa_code=mfa_code, store_session=True)
    _rh_state["logged_in"] = True
    return rh


@router.get("/api/crypto/stocks")
def crypto_stocks():
    if not (get_setting("rh_username") and get_setting("rh_password")):
        return {"configured": False}
    try:
        rh = _rh_login()
        holdings = rh.build_holdings() or {}
        equity = None
        try:
            prof = rh.load_portfolio_profile() or {}
            equity = prof.get("equity")
        except Exception:
            pass
        return {"configured": True, "equity": equity, "holdings": holdings}
    except ImportError:
        return {"configured": False, "error": "robin_stocks not installed in the store venv"}
    except Exception as e:
        _rh_state["logged_in"] = False      # force fresh login next time
        return {"configured": False, "error": str(e)[:200]}


# ── 📈 stocks: watchlist quotes + news (yfinance, TTL 300s) ──────────────────
def _watch_symbols() -> list[str]:
    raw = get_setting("stocks_watchlist", "") or ""
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _yf_news(t, n=3) -> list[dict]:
    """Normalize yfinance news across its old (title/link) and new (content.*) shapes."""
    out = []
    try:
        for item in (t.news or [])[:n]:
            c = item.get("content") or item
            title = c.get("title") or ""
            link = (item.get("link")
                    or (c.get("canonicalUrl") or {}).get("url")
                    or (c.get("clickThroughUrl") or {}).get("url") or "")
            if title:
                out.append({"title": title, "link": link})
    except Exception:
        pass
    return out


@router.get("/api/crypto/stocks/watch")
def stocks_watch():
    syms = _watch_symbols()
    if not syms:
        return {"quotes": [], "note": "Add symbols to stocks_watchlist (comma-separated) first."}
    from cache import cached

    def _fetch():
        import yfinance as yf
        quotes = []
        for sym in syms[:25]:
            q = {"symbol": sym, "price": None, "news": []}
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info
                q["price"] = getattr(fi, "last_price", None) or (fi["last_price"] if "last_price" in fi else None)
                q["news"] = _yf_news(t, 3)
            except Exception as e:
                q["error"] = str(e)[:120]
            quotes.append(q)
        return {"quotes": quotes, "fetched_at": datetime.now().isoformat(timespec="seconds")}

    try:
        return cached("crypto:watch:" + ",".join(syms), 300, _fetch)
    except ImportError:
        return {"quotes": [], "error": "yfinance not installed in the store venv"}
    except Exception as e:
        return {"quotes": [], "error": str(e)[:200]}


# ── 📈 stocks: LLM daily brief (signals computed pure-pandas) ─────────────────
BRIEF_SYS = """You are a cautious markets analyst writing a SHORT morning brief for a \
hobbyist investor. You are given per-symbol technical signals (price, SMA20 vs SMA50, \
14-day RSI, a rough stance) and recent news headlines. Write 2-3 tight paragraphs: \
1) overall read of the watchlist, 2) the 2-3 most notable symbols and why (crossovers, \
overbought/oversold RSI, big news), 3) anything to watch next. Plain language, no hype, \
no price targets, no buy/sell instructions. End with exactly this line: \
"This is automated technical commentary, NOT financial advice.\""""


def _signal_for(sym: str) -> Optional[dict]:
    import yfinance as yf
    h = yf.Ticker(sym).history(period="3mo", interval="1d")
    close = h.get("Close")
    if close is None:
        return None
    close = close.dropna()
    if len(close) < 20:
        return None
    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = None
    try:
        g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
        rsi = 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    except Exception:
        pass
    if rsi is not None and rsi >= 70:
        stance = "overbought"
    elif rsi is not None and rsi <= 30:
        stance = "oversold"
    elif sma50 is not None and sma20 > sma50:
        stance = "bullish"
    elif sma50 is not None and sma20 < sma50:
        stance = "bearish"
    else:
        stance = "neutral"
    rnd = lambda v: round(v, 2) if isinstance(v, float) else v
    return {"symbol": sym, "price": rnd(price), "sma20": rnd(sma20),
            "sma50": rnd(sma50), "rsi": rnd(rsi), "stance": stance}


@router.get("/api/crypto/stocks/brief")
def stocks_brief():
    """Signals + ONE LLM brief for watchlist + holdings symbols. Heavy (yfinance
    history per symbol + an LLM call), so it runs as an orchestrator task — returns
    {task_id}; poll /api/task/{id} for {brief, signals}."""
    def _work():
        syms = list(_watch_symbols())
        try:                                     # add holdings symbols when configured
            if get_setting("rh_username") and get_setting("rh_password"):
                rh = _rh_login()
                for s in (rh.build_holdings() or {}):
                    if s.upper() not in syms:
                        syms.append(s.upper())
        except Exception:
            pass
        syms = syms[:15]
        if not syms:
            return {"brief": "No symbols — set a watchlist (or Robinhood creds) first.",
                    "signals": []}
        signals, headlines = [], []
        import yfinance as yf
        for sym in syms:
            try:
                sig = _signal_for(sym)
                if sig:
                    signals.append(sig)
                for n in _yf_news(yf.Ticker(sym), 2):
                    headlines.append(f"[{sym}] {n['title']}")
            except Exception:
                continue
        sig_lines = "\n".join(
            f"{s['symbol']}: price={s['price']} sma20={s['sma20']} sma50={s['sma50']} "
            f"rsi14={s['rsi']} stance={s['stance']}" for s in signals) or "(no signal data)"
        news_lines = "\n".join(headlines[:20]) or "(no recent headlines)"
        user_msg = f"Signals:\n{sig_lines}\n\nRecent headlines:\n{news_lines}"
        try:
            brief = _call_lmstudio(BRIEF_SYS, user_msg, max_tokens=900)
            brief = _re.sub(r"<think>.*?</think>", "", brief, flags=_re.DOTALL).strip()
        except Exception as e:
            brief = f"(LLM brief unavailable: {str(e)[:150]})"
        if "not financial advice" not in brief.lower():
            brief += "\n\nThis is automated technical commentary, NOT financial advice."
        return {"brief": brief, "signals": signals,
                "generated_at": datetime.now().isoformat(timespec="seconds")}

    tid = orch.submit_llm(_work, desc="Stocks daily brief", priority=0)
    return {"task_id": tid}
