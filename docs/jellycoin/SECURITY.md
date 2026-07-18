# JellyCoin — Security Protocols & Backups

The operating rules that keep the coin honest. Companion to `WHITEPAPER.md` §5.

## Attack surface

| Surface | Exposure | Guard |
|---|---|---|
| `/api/jelly/mining/work`, `/submit`, `/miner.py` | Reachable without a login session (rigs live on other boxes) | `X-Jelly-Token` shared rig token, checked on every call; localhost is implicitly trusted (same-box callers already passed the store's auth model) |
| Every other `/api/jelly/*` endpoint | Operator only | Store session auth (same as the rest of the dashboard) |
| Peer wallet RPC `/api/peers/rpc/wallet` | Federated buddies | `X-Peer-Key` hash-match against an APPROVED peer — same guard as all peer RPC; read-only |
| The miner script itself | Runs on rig boxes | Talks HTTP out only; holds nothing but the rig token |

## Protocols

1. **The rig token** (`jelly_miner_token`)
   - Auto-generated (128-bit hex) on first read; shown only inside the
     authenticated UI (Crypto → JellyCoin → Mining).
   - **Encrypted at rest** in the settings table (store secrets-at-rest system,
     same as exchange keys and the wallet mnemonic).
   - Rotation: delete the `jelly_miner_token` settings row (or overwrite via the
     API) → a new token generates on next read; update each rig's service unit.
     Old token dies instantly — rigs fail with 403, nothing worse.
   - Leak impact: a token holder can *fetch work and submit valid blocks* — i.e.
     donate hashpower and earn play-money JLY into a `miner:` wallet. They cannot
     read wallets, move funds, mint NFTs, or touch any other API.
2. **Work integrity**
   - Work IDs are single-use, in-memory, expire after 10 minutes.
   - Every submission is re-verified server-side with full 256-bit precision
     (the GPU's 64-bit fast compare is never trusted).
   - Stale submissions (chain advanced) are rejected; the first valid nonce at a
     height wins atomically under a lock.
3. **Ledger integrity**
   - Balances only move through logged `jelly_txs` rows inside the same SQLite
     transaction as the balance update — no silent edits.
   - Every coin of supply traces to a block whose `(header, nonce, target)` can
     be re-verified by anyone holding the block table.
   - All amounts are integer µJLY — no float drift.
4. **Human-in-the-loop commerce**
   - Missions (promo/perk/sell drafts) are inert until the operator approves;
     approval only posts to the in-world town feed.
   - The skilling-boost hook is wrapped so any coin failure can never break the
     world sim, and the whole tie-in sits behind the
     `world_crypto_mining_enabled` toggle (default off).
5. **No real-money coupling**
   - JLY is never sold by software, holds no exchange value, and the treasury
     touches no real-currency systems. Worst-case compromise = corrupted play
     economy, restored from a snapshot.

## Backups

- **Chain, wallets, NFTs, missions, boosts** all live in the store's single
  SQLite database, which the store's backup system snapshots on its schedule as
  compressed, rotated archives (Settings → Backups). Restoring a snapshot
  restores the full coin state; the ~10-minute in-memory work window is the only
  thing lost (miners just refetch work).
- **The rig token** is included in the Crypto tab's key-backup zip (the `jelly_`
  settings prefix), alongside the other market/exchange secrets. That zip
  contains live secrets — treat it like cash.
- **Rig boxes need no backup**: the miner is stateless; reinstalling is
  `pip install` + the service unit.

## Incident playbook

| Event | Response |
|---|---|
| Rig token leaked | Rotate (protocol 1); review `jelly_miners` for unknown rig names |
| Suspicious supply jump | Re-verify recent blocks' PoW from the block table; compare against snapshot |
| Chain corruption / bad deploy | Stop store, restore latest DB snapshot, restart; rigs reconnect automatically |
| Runaway boost minting | Toggle `world_crypto_mining_enabled` off; boost payouts are capped at 20 JLY/block regardless |
