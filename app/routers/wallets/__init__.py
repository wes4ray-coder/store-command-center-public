"""Wallets — REAL mainnet light-wallets (receive + monitor). One BIP39 seed drives
deterministic addresses for BTC/LTC/DOGE/ETH/KAS (app/wallet_lib.py); Monero gets a
primary address from the same seed, with live balance only when monero-wallet-rpc is
up. No node, no blockchain download — balances come from public explorers.

SECURITY: the mnemonic controls REAL funds. It is stored in the settings table under
`wallet_mnemonic` (encrypted at rest when that key is in SECRET_KEYS — see
app/crypto.py) and is NEVER logged. Receiving is always safe. SENDING IS DOUBLE-GATED:
/api/wallets/send queues a `wallet_sends` row ('proposed'); /prepare dry-runs the fee;
/broadcast does NOT sign directly — it files a `wallet_send` prayer in the God Console
and the transaction is only signed + broadcast once a HUMAN blesses that prayer. A
localhost/MCP caller (which bypasses auth) therefore cannot move real crypto on its own.

This module is a package: the shared ``router`` + schema/seed/address helpers live in
``_base``; the routes are split across ``overview`` (all-coins balances), ``seed``
(backup/restore), ``sends`` (the gated spend engine + `wallet_send` prayer executor)
and ``xmr`` (Monero daemon/wallet). Importing the submodules runs their ``@router.*``
decorators (and the ``sends`` executor registration), registering every route on the
single shared ``router``.
"""
from ._base import router                       # shared router + one-time _ensure_schema()
from . import overview, seed, sends, xmr        # noqa: F401  (import registers routes + the wallet_send executor)

__all__ = ["router"]
