# THE COMPANY — Game Systems Roadmap

The living-world vision, structured. Read `WORLD.md` first (module map). This doc
covers the *game-as-mirror-of-reality* layer: skills, seasons, the raid, and
"learning". Everything here extends the EXISTING state machine (`world_sim` +
`world_ticker`) — we are adding richer states, not a parallel engine.

## The core principle (the thing that ties it all together)

Two coupled layers, one truth:

1. **The Real Layer** — actual platform work: generations, resell, OpenClaw runs,
   bug scans, Pi-hole security. This is TRUTH. It already drives the sim.
2. **The Game Layer** — the pixel town. Every visible action is a *dramatization*
   of a real-layer event. Agents never do fake work; they act out real work.

"Autonomous but state-driven" = agents choose freely *within* the state the real
layer puts the town in. "The background grows and learns" = agents accumulate
skills/knowledge and the orchestrator assigns work to whoever's best — measurable
improvement over time (see §E).

---

## A. Skills & Idle Labour (RuneScape-style)  — FOUNDATION

Per-agent skills, each with XP → level (standard rising curve). Two families:

- **Gathering/craft:** Woodcutting, Mining, Farming, Fishing, Construction.
- **Combat/scholarly:** Attack, Defense, Knowledge (used by the raid + library).

Map gets **resource nodes**: trees (already drawn) → woodcut; rock/ore veins →
mine; farm plots → farm; fishing spots (pond edges) → fish; build sites →
construction. When an agent is IDLE (no real job) it picks the nearest node for
its chosen skill, walks there, plays the `work` animation, gains XP, and yields a
resource into the **company stockpile** (logs/ore/crops/fish) — which feeds the
coin economy and construction projects.

- Backend: `world_skills.py` + table `world_skills(agent_key, skill, xp)`.
- Frontend: node sprites (trees exist; add ore/farm/fishing/build via the prop
  pipeline) + the idle-skilling destination in `world_sim._choose`.

## B. Church & Library  (buildings placed — commit for that landed; behaviors next)

- **Library 📚 = Knowledge.** Study raises Knowledge, which **improves real-job
  success rate / speed** — the literal "learning to do stuff better". Ties to the
  trends/research dept.
- **Church ⛪ = Faith/Morale.** Visiting restores spirit/mood + a small buff; the
  calm counterweight to raid stress and where agents heal in RECOVERY.

## C. Seasons & The Orchestrator (the "choreography" state machine)

`world_orchestra.py` — a top-level conductor ABOVE the per-agent sim, ticked by
`world_ticker`. Owns the single baton everything reads from:

- **Seasons** Spring→Summer→Autumn→Winter over N in-game days: palette shift,
  which skills are productive (farming peaks spring/summer, woodcut autumn),
  seasonal festivals.
- **Town phase** (see §D).
- **Scheduled events:** market day, festival, and the raid.

Agents' visible behaviour, terrain mood, and event cadence all derive from the
orchestrator so the town stays in sync.

## D. The Raid / Debug Mode (security state machine — strongest real binding)

Town phase: **PEACE → WATCH → RAID (debug) → RECOVERY**, owned by the orchestrator.

- **Triggers (real signals):** scheduled sweeps, OR a real event — failing
  tests / error-log spike (bugs), Pi-hole flagging suspicious domains/clients,
  failed logins, a new device on the LAN.
- **During RAID the REAL layer runs:**
  - **Bug hunt:** linters / tests / error-log scan → each finding = an "enemy".
  - **Pi-hole audit:** query the Pi-hole API for suspicious queries/clients →
    block/blacklist them = "defeating" the threat. *(Needs the Pi-hole host + API
    token — confirm before building this half.)*
- **The GAME dramatizes it:** sky goes red-alert, agents rally from their jobs to
  combat stance, threat-monsters spawn (anokolisa has Skeleton/Orc mob sheets),
  agents fight — each real block/fix = a monster down → Attack/Defense/Knowledge
  XP. Mayor/Boss command the defense.
- **RECOVERY:** agents heal at the church, XP tallied, a security/bug **after-
  action report** generated (real: what was blocked/fixed). A dedicated
  **Warden/Sentinel** agent (+ the OpenClaw engineer) owns these systems.

## E. "Learning" — the honest ML answer

True Unity **ML-Agents / RL is not feasible** in this FastAPI+JS stack (no
training env, and the GPU is already booked by the LLMs). But the *felt* goal —
"the system gets better over time" — is achievable with a lightweight adaptive
layer:

- Every task/skill logs outcomes → success rates + best-performer stats.
- The orchestrator ASSIGNS work to the best-skilled agent (greedy policy);
  Knowledge/skill raises success → the town measurably improves.
- **Optional real online learning:** a small **multi-armed bandit** picks which
  idle activity / which agent for a task, learning from reward (coins/XP). No
  neural net; pure Python; fits the ticker.
- If true RL is ever wanted: export sim state + rewards to a separate Gymnasium
  service. Big separate project — the bandit gives ~80% of the feel for ~5% of
  the effort.

---

## Build order (phased)

1. **Skills substrate** — `world_skills.py` + table + resource nodes + idle
   skilling. Everything (combat, knowledge) sits on this. ← recommended start
2. **Library/Church behaviours** — study→job buff, church→morale/heal.
3. **Seasons + Orchestrator** — `world_orchestra.py`, the conductor + phase state.
4. **Raid/Debug mode** — real bug-scan + Pi-hole audit + combat dramatization + mobs.
5. **Adaptive layer** — stats-driven assignment; optional bandit.

Cross-refs: [[store-company-world]] for the built systems; `WORLD.md` module map.

---

# PHASE 2 — the depth pass (requested 2026-07-14)

A–E shipped. Phase 2 makes it deep and alive. Grouped into 5 chunks:

## Chunk 1 — Combat & State-Machine v2 (the raid, done right)
- Enemies **spawn from a random map edge** and advance toward the HQ (not popping in
  a ring). They fight their way in.
- **Waves keep coming until the real background tasks finish** — raid length is tied
  to actual store/OpenClaw work in flight, not a fixed timer. Spawns continue while
  `busy_now`/task_runs are non-empty.
- **Enemy tiers** (weak→strong: goblin→orc→skeleton→armored) and **BOSSES** every N
  waves; enemies scale up over a long raid.
- **Role split during a raid** (randomly assigned so skills spread across people, not
  all on one): FIGHTERS attack (attack XP) · BUILDERS raise & repair defenses
  (defense/construction XP). Half and half.
- **Defense structures**: walls & gates around the town with their own HP /
  destruction bar + **repair**; enemies must break them before reaching HQ.
- **Fighting animation** (lunge/attack — none yet) + agents level → clear enemies
  faster.
- **Proper IDLE**: agents "never stop moving" now → add a real idle state with
  sub-states (wander / pause / do-a-thing / do-another-thing) so movement reads
  natural, not jittery/clunky.

## Chunk 2 — Real AI Security (make the scan actually scan)
- The drill/raid must do REAL work: review Pi-hole queries, **scan store-system logs**,
  compare/search for suspicious activity (model work → GPU queue; the "combat" is the
  dramatization of that analysis).
- Every large store subsystem gets **logs + debugging tasks**; each agent is assigned a
  log/task set so **everyone always has real work**. Human-work randomly assigned;
  **model work still rides the orchestrator queue**.

## Chunk 3 — Company HQ & Production Flow
- HQ rework: **departments as rooms**, multiples of items, feels alive (not one bland
  room).
- Watch a **product move step 1→2→3→4** through departments; the finished product is a
  **movable in-game object**; build **storage** to review/stack them.
- Non-work builds show a **transparent ghost + build time** while under construction.

## Chunk 4 — Materials & Research Tiers
- Tiers **wood → rock → bronze → iron → steel**; start at wood; must **research/unlock**
  the next tier (build a library/database), find or craft it, and **push the research
  through GitHub** to advance.

## Chunk 5 — Town & World Rework
- Less square/gridy: **bigger organic ponds, mountains on one side**, bigger sub-grids
  for small-item placement.
- **Houses match the population count**; **furnish** them (they're empty); let agents
  hang **store-generated pictures as wall art** in their houses.
- Regression to fix: the town's solid **walls all became fences** — restore proper
  walls where intended.

Build order: Chunk 1 is foundational (state machine + roles underpin 2 & 3). Then
2 (real work for everyone), 3 (production feel), 4 (progression), 5 (world polish).
