# The Company — Roles, Checks & Balances

Who everyone is, what they're for, and how the loop keeps itself honest.

## The cast

| Role | Who | Purpose | Backed by |
|---|---|---|---|
| **God** | You | Final judgement. Blesses/denies prayers, reviews designs, creates your own work. Every verdict trains the town. | `world_ops` God Console, design review pipeline |
| **Boss Kane** 💼 | NPC (special agent) | Production standards + finances. Endorses prayers: is this on-brand for god's learned taste, can the budget bear it? Mood mirrors the workers. | `world_ops._endorse` (taste + budget cap) |
| **Mayor Vex** 🏛️ | NPC (special agent) | The people + the treasury. Endorses prayers: is the crew in shape for new ventures, can the balance take the hit? Mood mirrors the whole town. Runs meetings/directives. | `world_ops._endorse` (morale + treasury), `world_gov` |
| **Agents** (the crew) | 17 workers/OpenClaw-bound characters | Do the REAL work: their coins/XP come only from actual completed platform jobs. They create media, file prayers, shop, study, build, defend, and *feel* god's verdicts. | `world_sim`, `world_work`, `world_items`, `world_auto` |
| **Townsfolk / NPCs** | Client-side villagers | The civilians the Mayor answers for: venue staff, HQ sentries, wanderers. Pure atmosphere — no economy access. | `world-npcs.js` |

## The learning loop (the "machine learning")

Two genuine online learners, both fed by the world:

1. **`world_taste` — god's taste model.** Embedding k-NN over every judgement
   you make: hand-made prayer verdicts (±1), design approvals/rejections (±1),
   and your own creations (+0.7 exemplars). `score(text)` → predicted approval.
   Retrains continuously — every bless/deny is a new training example, and the
   creator gets a mood hit + journal entry, so agents *know* what god thought.
2. **`world_learn` — the activity bandit.** ε-greedy per-agent policy over idle
   activities, rewarded by XP; merit routing gives skilled agents more work.

## Checks & balances (why the loop can't run away)

- An agent/studio wants something real → files a **prayer**.
- **Boss + Mayor endorse independently** (taste/finances vs morale/treasury).
  Their reasons are stamped on the prayer and shown in the God Console.
- **Automation may only act with BOTH endorsements + taste ≥ `world_taste_min`**
  — and even then only free/within-budget kinds. Anything doubted waits for god.
- **ALWAYS_GATE** (Etsy/Printify listings, payouts, code) never auto-runs, ever.
- **God overrules freely** — and every override becomes training data, so the
  endorsers' judgement converges toward yours over time.
- **The economy breathes**: wages come only from real completed work; purchases
  return coins to the company fund; bills/rent drain; the Mayor blocks new
  ventures when morale or the treasury sags — so activity naturally fluctuates
  with real output and real money.

## Free will (why nobody moves in lockstep)

Every agent has a **chronotype** (stable id-hash): personal collapse point,
recharge threshold, and scheduled-sleep resistance — plus the bandit's learned
preferences, needs, mood thoughts and mental breaks. Same state machine,
different constants per person → individual-looking lives.

## Extension points

- `world_taste.score` is a general "would god like this?" oracle — usable by
  the Republic (rank strategies), world_sell (pick designs to list), trends.
- Endorsement thresholds: `world_taste_min` setting (default 0.35).
- A future RL layer can consume the same signals (taste labels, XP rewards,
  treasury deltas) — they're all persisted tables.
