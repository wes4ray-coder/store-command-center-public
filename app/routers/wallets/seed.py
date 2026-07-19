"""wallets — seed backup reveal, backup acknowledgement, and BIP39 restore/import."""
import json

from fastapi import APIRouter

from deps import *
from services import *

import wallet_lib as wl

from ._base import router, _ensure_seed, _addresses, _store_mnemonic, _meta_get, _meta_set


# ── seed backup / restore ─────────────────────────────────────────────────────
@router.get("/api/wallets/seed")
def wallets_seed():
    """One-time backup reveal. The app is auth-guarded; still, treat this response
    like cash — it IS the wallet."""
    seed = _ensure_seed()
    return {
        "mnemonic": seed,
        "addresses": _addresses(seed),
        "warning": ("These 24 words ARE your wallet — anyone with them can take every "
                    "coin, on every chain, forever. Write them on paper, store them "
                    "offline, never screenshot or paste them anywhere. The Store cannot "
                    "recover them for you if this database is lost."),
    }


@router.post("/api/wallets/seed/ack")
def wallets_seed_ack():
    """User confirmed they saved the recovery phrase."""
    _meta_set("seed_ack", "1")
    return {"ok": True, "seed_backed_up": True}


class SeedImportIn(BaseModel):
    mnemonic: str


@router.post("/api/wallets/seed/import")
def wallets_seed_import(body: SeedImportIn):
    """Replace the wallet with the user's own BIP39 seed (restore). Resets the
    backup acknowledgement — it's a different wallet now."""
    from bip_utils import Bip39MnemonicValidator
    from cache import invalidate_prefix
    mnem = " ".join((body.mnemonic or "").strip().lower().split())
    if not mnem:
        raise HTTPException(400, "Mnemonic is required.")
    if not Bip39MnemonicValidator().IsValid(mnem):
        raise HTTPException(400, "Not a valid BIP39 mnemonic — check the words, order "
                                 "and count (12/15/18/21/24 words).")
    _store_mnemonic(mnem)
    _meta_set("seed_ack", "0")
    invalidate_prefix("wallets:")   # old addresses + balances are for the old wallet
    logger.info("wallet seed imported (replaced)")   # never the words themselves
    return {"ok": True, "addresses": _addresses(mnem), "seed_backed_up": False}
