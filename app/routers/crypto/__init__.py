"""Crypto & Markets — local Bitcoin (regtest) node, FreqTrade paper bot, coins & stocks.

What lives here:
  - Coin market data (CoinGecko free API, TTL-cached) for the Stats sub-tab.
  - Bitcoin Core running in Docker (`crypto-bitcoind`) on REGTEST — a private local
    chain with no blockchain download. Blocks are mined instantly via
    `generatetoaddress`, which makes it perfect for learning the REAL node/wallet
    software and for agent automation, but the coins have no market value.
  - FreqTrade (`crypto-freqtrade`) in DRY-RUN mode — a real trading bot, paper money.
    The LLM drafts IStrategy files into user_data/strategies_drafts; a human approves
    a draft to move it into user_data/strategies. Drafts NEVER go live by themselves.
  - Stocks: Robinhood portfolio (robin_stocks, read-only here), a yfinance watchlist,
    and an LLM daily brief (SMA20/50 + RSI14 signals). Not financial advice.
  - A key backup zip (bitcoin wallet descriptors + crypto/trading settings +
    strategy files). The zip CONTAINS PRIVATE KEYS — treat it like cash.

This module is a package: the router + shared constants/helpers + the reserved-keys
settings endpoints live in ``_base``; the routes are split by domain across ``node``
(bitcoind + coin stats + gated key backup), ``mining`` (xmrig), ``trading``
(FreqTrade lifecycle), ``stocks`` (Robinhood + yfinance) and ``kraken`` (Kraken).
Importing the submodules runs their ``@router.*`` decorators, registering every
route on the single shared ``router`` exposed here.
"""
from ._base import router, _BACKUP_PREFIXES    # shared router + one-time schema side effect
# ``_BACKUP_PREFIXES`` re-exported so external callers keep resolving
# ``routers.crypto._BACKUP_PREFIXES`` as they did against the old single-file module
# (tests/test_pearl.py depends on it).
from . import node, mining, trading, stocks, kraken  # noqa: F401  (registers @router routes)

__all__ = ["router", "_BACKUP_PREFIXES"]
