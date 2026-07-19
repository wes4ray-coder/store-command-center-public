"""wallets — the all-coins overview: address + live (explorer-backed, cached) balance."""
import json

from fastapi import APIRouter

from deps import *
from services import *

import wallet_lib as wl

from ._base import router, _ensure_seed, _addresses, _meta_get


# Where "view on explorer" links point (public, address-level; XMR has none — privacy).
EXPLORER_URL = {
    "BTC":  "https://blockstream.info/address/{a}",
    "LTC":  "https://litecoinspace.org/address/{a}",
    "DOGE": "https://blockchair.com/dogecoin/address/{a}",
    "ETH":  "https://etherscan.io/address/{a}",
    "KAS":  "https://explorer.kaspa.org/addresses/{a}",
}


# ── wallets overview ──────────────────────────────────────────────────────────
@router.get("/api/wallets")
def wallets_overview():
    """All coins: address + live balance (explorer-backed, cached ~60s). A dead
    explorer yields an error string on that coin — never a 500."""
    from cache import cached
    seed = _ensure_seed()
    addrs = _addresses(seed)

    def _bal(sym, addr):
        return cached(f"wallets:bal:{sym}:{addr}", 60, lambda: wl.balance(sym, addr))

    # Fetch the 5 queryable balances in parallel — serial worst-case on dead
    # explorers would stall the tab for over a minute.
    import concurrent.futures as _cf
    balances = {}
    q = [s for s in wl.COINS if s != "XMR" and addrs.get(s)]
    with _cf.ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_bal, s, addrs[s]): s for s in q}
        for f in _cf.as_completed(futs):
            sym = futs[f]
            try:
                balances[sym] = f.result()
            except Exception as e:            # belt & braces — wl.balance never raises
                balances[sym] = {"confirmed": None, "error": str(e)[:120]}

    coins = []
    for sym in wl.COINS:
        addr = addrs.get(sym, "")
        if sym == "XMR":
            b = {"confirmed": None,
                 "error": "balance needs the Monero wallet daemon (privacy chain — "
                          "no public address lookup)"}
        else:
            b = balances.get(sym, {"confirmed": None, "error": "no address"})
        coins.append({
            "sym": sym,
            "name": wl.COIN_NAME[sym],
            "address": addr,
            "balance": b.get("confirmed"),
            "decimals": wl.COIN_DECIMALS[sym],
            "explorer": EXPLORER_URL[sym].format(a=addr) if sym in EXPLORER_URL and addr else "",
            "error": b.get("error"),
        })
    return {"coins": coins, "seed_backed_up": _meta_get("seed_ack") == "1"}
