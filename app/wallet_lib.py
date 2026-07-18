"""Real mainnet light wallets — deterministic address derivation from one BIP39
seed, balances via public block explorers. No local full node, no blockchain
download (per the owner's constraint). Monero is handled separately via
monero-wallet-rpc against a remote node (see routers/crypto.py).

SECURITY: the master mnemonic controls REAL funds. It lives ONLY in the settings
table encrypted at rest (key `wallet_mnemonic`, in SECRET_KEYS). This module never
logs it. Receiving is always safe; spending is gated in the router.
"""
from __future__ import annotations
import logging
import requests

from bip_utils import (
    Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes,
    Bip32Secp256k1, Monero,
)

log = logging.getLogger("store")

# coin symbol → (bip_utils coin, explorer kind)
_BIP44 = {
    "BTC":  Bip44Coins.BITCOIN,
    "LTC":  Bip44Coins.LITECOIN,
    "DOGE": Bip44Coins.DOGECOIN,
    "ETH":  Bip44Coins.ETHEREUM,
}

COINS = ["BTC", "LTC", "DOGE", "ETH", "XMR", "KAS"]
COIN_NAME = {"BTC": "Bitcoin", "LTC": "Litecoin", "DOGE": "Dogecoin",
             "ETH": "Ethereum", "XMR": "Monero", "KAS": "Kaspa"}
COIN_DECIMALS = {"BTC": 8, "LTC": 8, "DOGE": 8, "ETH": 18, "XMR": 12, "KAS": 8}


# ── Kaspa CashAddr encoding (bip_utils has no Kaspa) ─────────────────────────
_KAS_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_KAS_GEN = [0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4, 0xae2eabe2a8, 0x1e4f43e470]


def _kas_polymod(values):
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07ffffffff) << 5) ^ d
        for i in range(5):
            if (c0 >> i) & 1:
                c ^= _KAS_GEN[i]
    return c


def _kas_to5(data: bytes):
    acc = 0
    bits = 0
    out = []
    for b in data:
        acc = (acc << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append((acc >> bits) & 0x1f)
    if bits:
        out.append((acc << (5 - bits)) & 0x1f)
    return out


def kaspa_address(xonly_pubkey: bytes, prefix: str = "kaspa", version: int = 0) -> str:
    """CashAddr-encode a 32-byte x-only schnorr pubkey as a kaspa: address."""
    payload = bytes([version]) + xonly_pubkey
    five = _kas_to5(payload)
    pfx = [ord(c) & 0x1f for c in prefix] + [0]
    mod = _kas_polymod(pfx + five + [0] * 8) ^ 1
    checksum = [(mod >> (5 * (7 - i))) & 0x1f for i in range(8)]
    return prefix + ":" + "".join(_KAS_CHARSET[d] for d in five + checksum)


# ── derivation ───────────────────────────────────────────────────────────────
def derive_all(mnemonic: str) -> dict:
    """Return {symbol: address} for every non-Monero coin from one BIP39 seed.
    Monero's address comes from its wallet-rpc, not here."""
    seed = Bip39SeedGenerator(mnemonic).Generate()
    out = {}
    for sym, coin in _BIP44.items():
        acct = (Bip44.FromSeed(seed, coin)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0))
        out[sym] = acct.PublicKey().ToAddress()
    # Kaspa: raw secp256k1 at m/44'/111111'/0'/0/0, x-only pubkey
    kctx = Bip32Secp256k1.FromSeedAndPath(seed, "m/44'/111111'/0'/0/0")
    out["KAS"] = kaspa_address(kctx.PublicKey().RawCompressed().ToBytes()[1:])
    return out


def derive_xmr_primary(mnemonic: str) -> str:
    """Monero primary address derived from the same seed (for display/mining payout
    when wallet-rpc isn't up)."""
    seed = Bip39SeedGenerator(mnemonic).Generate()
    priv = (Bip44.FromSeed(seed, Bip44Coins.MONERO_ED25519_SLIP)
            .DeriveDefaultPath().PrivateKey().Raw().ToBytes())
    return Monero.FromBip44PrivateKey(priv).PrimaryAddress()


# ── balances via public explorers (best-effort, never raises) ────────────────
def _get(url, timeout=15, **kw):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "store-command-center"}, **kw)
    r.raise_for_status()
    return r


def balance(sym: str, address: str) -> dict:
    """Return {confirmed: float, error: str|None} for a coin+address. Uses public
    explorers; XMR is not queryable by address (privacy) — handled via wallet-rpc."""
    try:
        if sym == "BTC":
            d = _get(f"https://blockstream.info/api/address/{address}").json()
            sats = d["chain_stats"]["funded_txo_sum"] - d["chain_stats"]["spent_txo_sum"]
            return {"confirmed": sats / 1e8, "error": None}
        if sym == "LTC":
            d = _get(f"https://litecoinspace.org/api/address/{address}").json()
            sats = d["chain_stats"]["funded_txo_sum"] - d["chain_stats"]["spent_txo_sum"]
            return {"confirmed": sats / 1e8, "error": None}
        if sym == "DOGE":
            d = _get(f"https://api.blockcypher.com/v1/doge/main/addrs/{address}/balance").json()
            return {"confirmed": d.get("final_balance", 0) / 1e8, "error": None}
        if sym == "ETH":
            return eth_balance(address)
        if sym == "KAS":
            d = _get(f"https://api.kaspa.org/addresses/{address}/balance").json()
            return {"confirmed": int(d["balance"]) / 1e8, "error": None}
    except Exception as e:
        return {"confirmed": None, "error": str(e)[:120]}
    return {"confirmed": None, "error": "unsupported"}


def eth_balance(address: str, rpc: str = "https://ethereum-rpc.publicnode.com") -> dict:
    try:
        r = requests.post(rpc, timeout=15, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
            "params": [address, "latest"]})
        r.raise_for_status()
        wei = int(r.json()["result"], 16)
        return {"confirmed": wei / 1e18, "error": None}
    except Exception as e:
        return {"confirmed": None, "error": str(e)[:120]}


def valid_kaspa(address: str) -> bool:
    """Ask the public Kaspa API to validate our generated address (checksum check)."""
    try:
        r = requests.get(f"https://api.kaspa.org/addresses/{address}/balance", timeout=15)
        return r.status_code == 200
    except Exception:
        return False


# ── SPENDING: private keys + sign/broadcast (SENSITIVE — never logged) ───────
# Every function here derives the key on demand from the seed and forgets it.
# BTC/LTC/DOGE go through bitcoinlib (UTXO build+sign+broadcast); ETH via web3.
_NET = {"BTC": "bitcoin", "LTC": "litecoin", "DOGE": "dogecoin"}
ETH_RPC = "https://ethereum-rpc.publicnode.com"


def _priv_wif(sym: str, mnemonic: str) -> str:
    seed = Bip39SeedGenerator(mnemonic).Generate()
    acct = (Bip44.FromSeed(seed, _BIP44[sym])
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0))
    return acct.PrivateKey().ToWif()


def _eth_priv(mnemonic: str) -> str:
    seed = Bip39SeedGenerator(mnemonic).Generate()
    acct = (Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT).AddressIndex(0))
    return acct.PrivateKey().Raw().ToHex()


def xmr_keys(mnemonic: str) -> dict:
    """Monero primary address + private spend/view keys (for wallet-rpc restore)."""
    seed = Bip39SeedGenerator(mnemonic).Generate()
    priv = (Bip44.FromSeed(seed, Bip44Coins.MONERO_ED25519_SLIP)
            .DeriveDefaultPath().PrivateKey().Raw().ToBytes())
    m = Monero.FromBip44PrivateKey(priv)
    return {"address": m.PrimaryAddress(),
            "spend": m.PrivateSpendKey().Raw().ToHex(),
            "view": m.PrivateViewKey().Raw().ToHex()}


def btc_family_send(sym: str, mnemonic: str, to: str, amount: float, broadcast: bool) -> dict:
    """Build (and optionally broadcast) a legacy P2PKH send on BTC/LTC/DOGE via
    bitcoinlib. broadcast=False = dry run: build + sign, return the fee, DON'T send.
    Raises on insufficient funds / bad address (surfaced to the caller)."""
    from bitcoinlib.wallets import Wallet, wallet_exists, wallet_delete_if_exists
    net = _NET[sym]
    name = f"jn_{sym.lower()}"
    wif = _priv_wif(sym, mnemonic)
    # rebuild the wallet fresh each call so a rotated seed can't hit a stale key
    wallet_delete_if_exists(name, force=True)
    w = Wallet.create(name, keys=wif, network=net, witness_type="legacy")
    try:
        w.utxos_update()   # pull UTXOs from bitcoinlib's service providers
        sats = int(round(amount * 10 ** COIN_DECIMALS[sym]))
        # broadcast=False → build + sign only; True → also push to the network
        t = w.send_to(to, sats, broadcast=broadcast)
        fee = (t.fee or 0) / 10 ** COIN_DECIMALS[sym]
        if t.error:
            raise RuntimeError(str(t.error)[:160])
        if not broadcast:
            return {"fee": fee, "inputs": len(t.inputs), "size": getattr(t, "size", None)}
        return {"txid": t.txid, "fee": fee}
    finally:
        wallet_delete_if_exists(name, force=True)


def eth_send(mnemonic: str, to: str, amount: float, broadcast: bool) -> dict:
    """Build (and optionally broadcast) a plain ETH transfer via web3 + public RPC."""
    from web3 import Web3
    from eth_account import Account
    w3 = Web3(Web3.HTTPProvider(ETH_RPC, request_kwargs={"timeout": 20}))
    acct = Account.from_key(_eth_priv(mnemonic))
    to_cs = Web3.to_checksum_address(to)
    value = w3.to_wei(amount, "ether")
    gas_price = w3.eth.gas_price
    gas = 21000
    fee = gas_price * gas
    if not broadcast:
        bal = w3.eth.get_balance(acct.address)
        if bal < value + fee:
            raise RuntimeError(f"insufficient funds: have {bal/1e18:.6f}, "
                               f"need {(value+fee)/1e18:.6f} ETH incl. fee")
        return {"fee": fee / 1e18, "total": (value + fee) / 1e18,
                "gas_price_gwei": gas_price / 1e9}
    tx = {"to": to_cs, "value": value, "gas": gas, "gasPrice": gas_price,
          "nonce": w3.eth.get_transaction_count(acct.address), "chainId": 1}
    signed = acct.sign_transaction(tx)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction)
    return {"txid": txh.hex(), "fee": fee / 1e18}
