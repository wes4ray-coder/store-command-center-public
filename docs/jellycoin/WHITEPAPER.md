# JellyCoin (JLY) — White Paper

*Version 1.0 — July 2026*

## Abstract

JellyCoin is a community token with one unusual property for its size: **supply is
issued exclusively by real GPU proof-of-work**. There is no faucet, no admin mint
button, and deliberately no CPU mining. A single authority node (the Acme
Store) keeps the ledger and verifies every block, while any GPU — from a decade-old
Radeon to a current RTX — competes to solve blocks. JLY powers a small, honest
economy: a virtual company whose agents boost mining through in-world labor, an
art-NFT registry anchored to content hashes, a compute-sharing market between
federated peers, and an AI assistant with its own tipping wallet.

**JellyCoin is a community token, not an investment.** It has no price, no
exchange listing, and no promise of value. This paper describes exactly what it
is, so nobody has to guess.

## 1. Design goals

1. **Real scarcity, honest issuance.** New JLY must cost physical work
   (electricity through a GPU), even though the ledger itself is centrally kept.
2. **Second life for old hardware.** The proof-of-work must run on any OpenCL 1.1
   GPU — cards too old for modern AI workloads remain first-class miners.
3. **No CPU mining.** Botnets, cloud burst instances, and "just run it on the
   server" shortcuts are all CPU-shaped. Excluding CPUs by protocol rule keeps
   issuance tied to hardware people actually own and can see.
4. **Human-approved commerce.** Software may *propose* promotion or sale of JLY;
   only a human may approve it.

## 2. Architecture: an authority-node chain

JellyCoin makes a deliberate trade: **one authority node** (the Store) holds the
ledger and validates proof-of-work, instead of a distributed consensus network.

What this gives up: trustlessness. The node operator can, in principle, edit the
ledger — exactly like every game economy, loyalty-points system, and community
scrip that has ever existed.

What it keeps — and what separates JLY from a points table:

- **Issuance is externally constrained.** The operator's database cannot create
  coins faster than GPUs solve blocks without breaking its own audit trail: every
  coin in `supply` traces to a block whose header hashes below its recorded
  target with its recorded nonce. Anyone with the block table can re-verify every
  hash with ~10 lines of any SHA-256 library.
- **Blocks are portable proofs.** A block (header + nonce + target) is valid or
  invalid independent of who stores it.
- **The chain is exportable.** Nightly snapshots mean the full history can be
  audited or re-hosted.

## 3. Proof-of-work specification

An implementation needs exactly this section.

```
header76 :=  prev_hash      (32 bytes — SHA-256 of previous block)
          || merkle         (32 bytes — SHA-256 binding height, prev, issue-time, miner)
          || height         (4 bytes, big-endian)
          || time           (4 bytes, big-endian, unix seconds)
          || reserved       (4 bytes, zero)

message  :=  header76 || nonce (4 bytes, big-endian)          -- 80 bytes total
pow_hash :=  SHA-256( SHA-256( message ) )

valid    :=  int(pow_hash, big-endian) < target               -- 256-bit compare
```

- **Genesis target** (difficulty 1.0): `2^240` — an average of 65,536 hashes per
  block, so bootstrap mining works on any hardware.
- **Difficulty retarget:** every 20 blocks, target scales by
  `actual_span / expected_span` toward **60-second blocks**, clamped to 4× per
  adjustment (in exact integer arithmetic), never easier than genesis.
- **Stall recovery:** because retargeting only happens when a block lands, a chain
  whose miners all disappear at a hard target could never recover on its own. Work
  issued after 20 minutes of silence is therefore progressively eased — one step
  per missed block interval — until some rig can find a block again. It clears the
  moment a block lands, and it can never mint past the cap, so it affects liveness
  only. Operator-toggleable.
- **Reward:** 50 JLY per block, halving every 50,000 blocks.
- **Premine:** 1,000,000 JLY minted in the genesis block to the treasury — the
  float that funds NFT fees, compute payouts, grants, and store perks. All
  further supply is mined.
- **Maximum supply:** **6,000,000 JLY. Hard, and enforced in code.**
- **Units:** 1 JLY = 1,000,000 µJLY. All ledger math is integer µJLY.

### 3.1 The supply cap

Summed exactly, the halving series pays
`Σ (50 JLY >> k) × 50,000` for k = 0…25 — after which the integer reward shifts to
zero at height 1,300,000 — for **4,999,999.4 JLY** of mining subsidy. With the
1,000,000 JLY premine that is 5,999,999.4 JLY, and the cap is that figure rounded
to a clean **6,000,000 JLY**. The cap was chosen to ratify the curve already in
force rather than to replace it: no holder's expected emission changes.

Three properties matter, and all three are enforced when a block is accepted, not
merely asserted here:

1. **Every mint site is capped.** Both the coinbase and the skilling-boost payout
   draw from the same headroom. Nothing else in the system can create JLY.
2. **The last block is trimmed, not overshot.** When the remaining headroom is
   smaller than the scheduled reward, the block pays exactly the headroom. After
   that the reward is zero.
3. **Boosts are inside the cap.** They were previously additional, unbounded
   emission on top of the block reward. They are not any more — which means boost
   emission now *shortens* the subsidy tail, spending headroom that would
   otherwise have paid the final coinbases. This is the honest consequence of
   having one cap that means one number.

Because 6,000,000 is a rounding-up, the subsidy alone stops 0.6 JLY short of the
cap; only boost emission can consume that last fraction. There is no burn
mechanism, so headroom never returns once spent.

### 3.2 The tail: after the cap, mining pays nothing

**This chain has no transaction fees.** Transfers are free. So when the cap is
reached there is no block subsidy *and* no fee market to replace it, and a miner
who solves a block past that point earns **zero JLY**. That is stated plainly
because it is the truthful outcome of the design, not an oversight: blocks are
still validated, ordered, and appended, so mining continues to secure and
sequence the chain — it simply stops paying.

No fee market is invented to paper over this. If one is ever wanted it is a
deliberate future decision, not something this document quietly assumes.

### 3.3 The getwork protocol

Miners speak plain HTTP to the node: `GET /work` returns
`{work_id, header76, target, height}`; the miner grinds nonces; `POST /submit`
returns accept/reject. Work expires in 10 minutes; the first valid submission at
a height wins; later ones are rejected as stale. The node *verifies* hashes — it
never generates them.

### 3.4 Why GPU-only holds

The reference miner enumerates OpenCL **GPU devices only** and refuses to start
otherwise. Could someone write a CPU miner against the open protocol? Yes — and
they would lose: sha256d throughput on a GPU is 2–4 orders of magnitude above a
CPU, so difficulty retargeting driven by GPU participants prices CPUs out
structurally, not just by policy.

## 4. The economy

| Wallet | Role |
|---|---|
| `treasury` | Premine float; pays compute credits and grants; collects NFT fees |
| `company` | The virtual company's fund; receives boost shares and compute charges |
| `assistant` | The AI assistant's tipping purse (500 JLY genesis grant) |
| `miner:<rig>` | Coinbase rewards per mining rig |
| `agent:<name>` | Virtual-company agents' earnings |
| `peer:<name>` | Federated buddies' compute earnings/spending |

### 4.1 Skilling boosts — play labor meets real work

Agents in the operator's virtual company gather resources (woodcutting, mining,
fishing…). Each unit of in-world yield queues a **boost ticket**. Tickets do
nothing on their own: they cash out **only inside a real mined block**, minting a
small bonus (0.05 JLY/ticket, ≤ 20 JLY/block, 24 h expiry) split between the
agent and the company. No GPU online → tickets expire worthless.

Boost emission is **inside the 6,000,000 JLY cap** (§3.1): a block pays its
coinbase first and boosts only from what headroom is left. If only part of the
queue fits, the tickets that fit are paid and the rest **stay pending**, first in
line for the next block. Tickets that will never be paid — aged out, or with the
cap exhausted — are **marked expired with a stated reason and kept on the ledger**
rather than deleted, so owed value never silently disappears; and once the cap is
exhausted no new tickets are issued at all, since that would accrue a debt the
chain has already promised not to pay. The game can
*decorate* proof-of-work; it can never *replace* it. The whole mechanism sits
behind an operator toggle.

### 4.2 Buddy compute — JLY as a metering currency

Federated peer nodes ("buddies") share LLM compute. JLY meters it: a buddy's
machine completing a job for the node **earns** their wallet a fee from the
treasury; a buddy consuming the node's AI **spends** the same fee into the
company wallet (embeddings cost ¹⁄₁₀). A buddy with no balance is **comped, never
blocked** — the tab is recorded, because compute sharing must not break over play
money. Peers audit their own wallet through an authenticated RPC.

### 4.3 Art NFTs

An NFT is minted from a real artwork file: the file's SHA-256 becomes the token's
immutable content hash, recorded with title, owner, and mint height. The same
content can never be minted twice. Minting costs 5 JLY to the treasury;
tokens are transferable between wallets.

### 4.4 Promotion under human approval

LLM agents may draft promotion or sale pitches for JLY. Every draft lands in a
**proposed** state that only the operator can approve, and approval merely
announces it inside the community. Nothing external is ever auto-posted, and JLY
is never sold for real money by software. This is a hard design rule, kept partly
for honesty and partly because selling tokens for real money is a regulated
activity that a hobby coin has no business wandering into.

## 5. Security model

- **Ledger integrity:** every balance change is a logged transaction; every coin
  traces to a verifiable block. Wallets are custodial accounts on the node.
- **Mining endpoints** are the only unauthenticated-session surface, and they
  self-guard with a shared rig token; all other operations require the node
  operator's authenticated session. The rig token is stored encrypted at rest.
- **Work replay:** work IDs are single-use, expire in 10 minutes, and submissions
  are re-verified server-side in full 256-bit precision.
- **Backups:** the ledger database is snapshotted on a schedule (compressed,
  rotated); the rig token ships in the operator's encrypted key-backup archive.
- **Blast radius:** JLY holds no real-money value by design, so the worst-case
  compromise is a corrupted play economy — recoverable from any snapshot.

## 6. What JellyCoin is not

- Not decentralized, and not pretending to be.
- Not an investment, a security, or a store of real-world value.
- Not for sale by software; humans approve every outward-facing action.
- Not mineable by CPU, botnet, or API shortcut — GPUs only, by protocol economics
  and by reference-implementation rule.

## 7. Reference implementation

The authority-node core (ledger + PoW validation, standalone, zero infrastructure
dependencies) is published as open source. The GPU miner ships with the Acme
Store distribution — mining JLY means joining a Acme node's network, which is
the point: the coin exists to make one small community's hardware, art, and
agents worth playing with.
