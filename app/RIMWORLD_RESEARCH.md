# RimWorld → "The Company" Research & Mapping Report

*Deep-dive on RimWorld's automation/colony-sim mechanics and a concrete spec for porting the best ideas into our living pixel-town ("The Company"). Compiled from the RimWorld Wiki, Ludeon forums, Steam Workshop, and community guides — sources listed at the bottom.*

> **TL;DR for builders:** RimWorld's magic is a **global job scheduler** driven by a **per-pawn Work priority grid** (rows = pawns, cols = work types, cells = priority 1–4). Every idle pawn scans work types by priority and grabs the highest-priority **available, reachable, reservable** job. Replacing our ε-greedy bandit (`world_learn.py`) with this model is the single highest-impact change. Everything else (bills, stockpile priorities, mood breaks, manager mod) layers cleanly on top of what we already have.

---

## 1. RimWorld Core Gameplay Loop

RimWorld is a colony/base-management sim. You direct (but do not directly control) a handful of **colonists (pawns)**. You don't puppet each action — you set **rules, zones, priorities, and bills**, and pawns autonomously decide what to do next. The loop:

1. **Assign work** — set each pawn's Work priorities (who does what, how urgently).
2. **Designate & order** — mark trees to chop, ore to mine, blueprints to build, zones to grow/store.
3. **Queue production** — add **bills** to workbenches ("cook 10 meals", "smelt until you have 200 steel").
4. **Pawns autonomously execute** — the job system continuously finds each idle pawn the best available job.
5. **Survive events** — raids, weather, disease, mood spirals; the storyteller AI paces threats.
6. **Grow** — research unlocks tech; build better rooms; mood/needs must stay managed or pawns break.

The elegant core: **the player manages the *policy*, the game resolves the *actions*.** That is exactly the leap we want over a bandit that opaquely "picks."

---

## 2. The Work / Priority System *(the section that matters most)*

### 2.1 The Work tab (the grid)
The Work tab is a **matrix**: one **row per colonist**, one **column per work type**. Columns are ordered **left = more important → right = less important** by default. Two display modes:

- **Checkbox mode (simple):** each cell is on/off. When multiple pawns can do a job, the game breaks ties by **skill** and proximity.
- **Manual priorities mode (numbers):** each cell holds a number **1 (highest) → 4 (lowest)**; **blank = never do this**. This is the mode power users and we care about.

### 2.2 The work types (vanilla, in default left-to-right priority order)
Firefighting → Patient (accept treatment) → Doctor → Patient bed rest → Basic (flick/refuel/etc.) → Warden (prisoners) → Handling (animals) → Cooking → Hunting → Construction → Growing → Mining → Plant cutting → Smithing → Tailoring → Art → Crafting → Hauling → Cleaning → Research.

Notable: **Firefighting, Patient, Doctor sit far left** — self-preservation always outranks chores. **Hauling & Cleaning sit far right** — the "chore" jobs everyone does when nothing better exists. Each work type maps to one or more **skills** and gates on **capabilities** (a pawn incapable of Violence gets no Hunting box; a pawn incapable of Dumb Labor gets no Hauling/Mining, etc.).

### 2.3 The scheduler — how a pawn picks its next job (THE algorithm)
When a pawn becomes idle (finishes a job / spawns / wakes), the game runs a **JobGiver scan**:

1. **Iterate work types in priority order.** For manual mode: process all work types at priority 1 first (left-to-right within the same number), then priority 2, then 3, then 4. Lower number always wins over a lower-placed column, i.e. *priority number dominates; column order only breaks ties within the same number.*
2. **For each work type, ask its WorkGivers** "is there a job you can offer this pawn *right now*?" A job is only offered if it is:
   - **Available** (something actually needs doing — a plant to cut, an item to haul, a bill with ingredients),
   - **Reachable** (a valid path exists),
   - **Reservable / unreserved** (no other pawn has claimed that target — the **reservation system**),
   - **Allowed by the pawn's Allowed Area** and current **schedule** (Work vs Sleep vs Joy time),
   - **Within the pawn's capabilities & assignment** (the cell isn't blank).
3. **First hit wins.** The moment a work type yields a legal job, the pawn takes it. Higher-priority work types are never skipped in favor of lower ones.
4. **Within a work type, sub-jobs have their own fixed internal order** (e.g. Doctor: rescue downed → tend to bleeding → tend others → feed patient). *Fluffy's Work Tab mod exposes these sub-priorities to the player.*
5. **Commitment / no-jitter:** a pawn **finishes its current job before re-scanning.** It doesn't re-evaluate every tick. (We already emulate this with `DWELL_SEC` in `world_sim.py`.)

### 2.4 Tie-breaking when the same job could go to many pawns
When several pawns share the same priority for a needed job, the game assigns it to the pawn that is **best/closest** — generally the one who will do it fastest (skill + distance). This is why you set your best cook to Cooking=1 and everyone else to 3.

### 2.5 Passions, skills, and learning
Each skill (0–20) has a **passion**: none, minor flame (+50% learning, small mood), major double-flame (+100% learning, bigger mood). Skills **rust** (decay) above ~10 if unused. Passion influences *player* assignment (put passionate pawns on that work) but the scheduler itself keys off the **priority number you set**, not passion — passion just changes outcomes/speed and mood.

### 2.6 Allowed Areas & Schedule (spatial + temporal gating)
- **Allowed Area:** a named region a pawn is restricted to (e.g. keep the cook out of the toxic zone). Jobs outside it are invisible to that pawn.
- **Schedule tab:** per-hour assignment of Work / Joy (recreation) / Sleep / Anything. During Sleep hours a pawn won't take work; during Joy hours it prioritizes recreation. Fluffy's Work Tab adds **time-sliced priorities** (e.g. "clean only 6–8am").

### 2.7 Manual override / queuing
Right-click a target with a pawn selected to **force** a specific job immediately (must be an enabled work type). **Shift-click chains** a queue of jobs. Forced jobs pre-empt the scan.

---

## 3. Jobs, Bills, Zones & Stockpiles

### 3.1 Jobs / JobDriver / Toils (execution layer)
- A **Job** = one discrete task with a target (e.g. "haul this steel to that stockpile", "mine this rock", "walk to B").
- A **JobDriver** is the worker that runs the job: it checks the job is still legal, **reserves** the targets/gear, and breaks the job into **Toils** — atomic steps (go to X → wait N ticks → do effect → drop). The pawn executes toils in sequence until done or the job is aborted (target vanished, interrupted by a higher-priority need, drafted, mental break).
- **Reservations** prevent two pawns fighting over one target — critical for our multi-agent town so two agents don't both "chop the same tree."
- **Interruptions:** urgent needs (starving, downed, fire, drafted) can cancel the current job mid-toil.

**Design takeaway:** model a job as `{work_type, target, toils[], reservation}` and a scheduler that assigns exactly one agent per target.

### 3.2 Bills (production orders)
Bills live on **workbenches** and are RimWorld's production automation. Each bill has:
- **Recipe** (what to make) + **repeat mode**:
  - **Do X times** — make N then stop/delete.
  - **Do until you have X** — maintain a target stock count; **the key auto-throttle**.
  - **Do forever** — never stops.
- **Pause when satisfied / Unpause at Y** — hysteresis band so a "keep 200 meals" bill sleeps at 200 and wakes at, say, 150. Prevents thrash.
- **Ingredient filters** — allowed materials, quality range, hit-point range, "cook from X food only."
- **Ingredient search radius** — cap how far a worker walks for ingredients.
- **Worker skill range** — only pawns with skill ≥ min (and ≤ max) take this bill (route fine work to experts, grind to novices).
- **Suspend** — temporarily disable without deleting.
- **Bill order = priority** — bills on a bench execute **top-to-bottom**; drag to reorder.
- **Counting gotcha:** "Do until you have X" only counts items **in a stockpile** (not loose on the floor), which is why players place a small stockpile at the crafter's feet.

**Design takeaway:** bills are literally **"do REAL platform work until we have N outputs, within a band."** This is a perfect fit for our generation queues (see §7).

### 3.3 Zones & Stockpiles
- **Stockpile zone:** a painted floor region that stores items. Config: **Priority** (Unstored < Low < Normal < Preferred < Important < Critical), **allowed item filter**, **quality/HP sliders.**
  - **Priority drives hauling:** haulers move items to the highest-priority stockpile with space — and will even **re-haul from a low-priority pile to a higher one.** This is how you get automatic item sorting with zero micromanagement.
  - **Dumping stockpile:** a low-priority pile for chunks/corpses/slag.
- **Growing zone:** painted region + chosen crop; pawns with Growing sow/harvest there. Fertility & light matter.
- **Home Area:** auto-painted around your buildings; defines where pawns **clean, repair, and firefight.** Outside it, no auto-maintenance.
- **Allowed Area** (see §2.6): restricts *pawn* movement, distinct from stockpiles which restrict *items*.

**Design takeaway:** stockpile **priority tiers with auto-reflow** are a beautifully simple resource-routing system. Our single flat company stockpile could gain per-resource "reserve/critical" thresholds that change what agents gather.

---

## 4. Needs, Mood & Mental Breaks

### 4.1 Needs
Pawns track needs on a **Needs tab**: **Food (hunger), Rest (sleep), Recreation/Joy, Comfort, Beauty, Outdoors, Space,** and (with DLC) more. Needs decay over time; unmet needs feed **Mood**. **We already have energy/fun/social/fulfillment/hunger** — a near-direct analog.

### 4.2 Recreation (Joy) types
Recreation has **types** (gaming, social, meditative, chemical, etc.). A pawn gets **diminishing returns from repeating one type** — variety matters, so you build a rec room with a chess table *and* horseshoes *and* a TV. Recreation is time-gated by the Schedule tab's Joy hours.

### 4.3 Mood
**Mood (0–100%)** is the running sum of **Thoughts** — timed **memories** with mood values that stack and decay:
- Negatives: "ate without a table (−3)", "slept on floor", "in pain", "witnessed death", "ugly environment", "colonist died (−X for days)."
- Positives: "ate a fine meal", "impressive bedroom", "recreation recently", "slept in a nice room."
- **Traits & needs** modify mood (e.g. "too cold", "hungry", drug withdrawal).
- After a mental break ends, the **Catharsis** thought grants **+40 mood for 2.5 days**, damping death-spirals.

### 4.4 Mental Break Threshold & the three tiers
Every pawn has a **Mental Break Threshold** stat (default **35%**). When mood falls below a threshold, there's a **rising per-tick chance** of a break of the corresponding severity:
- **Minor** — triggered below the full threshold (~35% default). Examples: **Sad wander, Food binge, Hide in room, Insulting spree, Crying, Giggling.**
- **Major** — below **4/7 of threshold (~20% default)**. Examples: **Tantrum (smashes things), Psychotic daze/wander, Bedroom tantrum, Social drug binge, Sadistic rage, Corpse obsession.**
- **Extreme** — below **1/7 of threshold (~5% default)**. Examples: **Berserk (melee-attacks anyone nearby), Fire-starting spree, Hard drug binge, Catatonic breakdown.**

A break is a **temporary loss of control** — the pawn stops doing assigned work and does the break behavior until it expires. Traits (e.g. "Volatile", "Iron-willed") shift the threshold up/down.

**Design takeaway:** mood is just a **decaying weighted sum of tagged events**, and breaks are **thresholded state changes that suspend normal job selection.** Extremely portable, and dramatic in a pixel town.

---

## 5. Research & Combat

### 5.1 Research
- Presented as a **tech tree**; later projects sit further right and require **prerequisites** (you must finish A before B is visible/startable).
- Progress is measured in **research points**, produced by pawns doing **Research** work at a **research bench** (skilled Intellectual pawns are faster; lighting/room quality add small bonuses).
- **Bench tiers gate advanced projects:** simple bench → **Hi-Tech research bench** (unlocked by Microelectronics; +33% speed) → **Multi-analyzer** structure linked within 8 tiles (+10% and *required* for the most advanced projects).
- Some projects also require **tech prints / analyzing items** in expansions. Completing a project **unlocks** buildings, recipes, apparel, etc.

**We already have this** (`world_tech.py` TIERS: wood→stone→bronze→iron→steel gated by research points + stockpiled materials). The borrowable refinement is a **branching tree with prerequisites & bench requirements** rather than a single linear ladder.

### 5.2 Combat & Health (high level)
- Pawns **draft** into manual control for combat; undrafted, threats trigger flee/fight per AI.
- **Ranged combat:** hit chance from shooter skill, weapon accuracy, range, cover, lighting, target size. **Cover** (walls, sandbags) is huge.
- **Melee:** block a chokepoint (door/hallway) so only one enemy engages at a time — the classic **"melee block."**
- **Health/Injury:** damage lands on **body parts** with types (cut/blunt/burn) affecting **pain, bleed rate, infection chance.** **Bleeding** ticks down blood; unattended → death. **Tending** (Doctor work + medicine) stops bleeding immediately and sets healing quality.
- **Downed:** a pawn goes **down from pain shock (pain ≥ Pain Shock Threshold), blood loss, or losing a leg** — can't move/fight; must be **rescued** to a medical bed (Doctor/Warden work). Downed ≠ dead — a huge tension mechanic (capture, rescue, bleed-out race).
- **Defense structures:** walls, doors, **sandbags/barricades (cover)**, **turrets** (auto-fire but need power & can explode), traps (deadfall/IED), killboxes. Raiders prioritize whoever is shooting at them, else attack random structures.

**We already have** a wave/monster raid with walls (HP+repair) and fighter/builder split (`world_raid.py`). Borrowable: **cover, downed-not-dead + rescue/doctor loop, and per-"body-part" (per-subsystem) injuries.**

---

## 6. Automation & Quality-of-Life Mods → Ideas to Borrow

| Mod | What it does | Design idea to borrow for The Company |
|---|---|---|
| **Work Tab** (Fluffy) | Replaces vanilla Work tab. **Per-sub-task priorities** (Ctrl-click a column to expand a work type into its individual jobs), **up to 9 priority levels**, **time-sliced priorities** (priority only during a time window), bulk edit rows/cols via shift+scroll. | Our **priority-grid UI** should expand a work type into sub-jobs, allow >4 levels, and optionally support time-of-day slots. This is the blueprint for replacing the bandit. |
| **Colony Manager / Colony Manager Redux** (Fluffy / ilyvion) | **Set target stock levels** ("keep 200 wood", "keep 50 meat") and the manager **auto-designates** hunting/logging/mining/foraging/livestock to hit them — no manual designation ever. | A **"Manager" panel**: user sets `keep N of resource X`; the town auto-issues gather orders (bills for gathering) until satisfied. Bridges bills + stockpile thresholds. **High value.** |
| **Allow Tool** | Mass allow/forbid, "haul urgently," and one-click "do all" verbs: hunt all, harvest all ripe, rearm all traps. | **Batch commands** in our UI: "harvest all ready generations," "publish all approved," "rearm defenses." One button → many jobs. |
| **Pick Up And Haul** | Pawns fill their **inventory with multiple stacks** and haul in one trip instead of one-item-at-a-time. | Let a hauling/resell agent **batch multiple pending outputs** into a single "run" rather than one task per trip — throughput + fewer state flips. |
| **While You're Up / Common Sense** | **Opportunistic hauling** — a pawn walking past an item on the way to a job grabs it; Common Sense adds "clean before cooking," "auto-refuel," "unload inventory," smarter defaults. | **Opportunistic sub-tasks:** an idle agent passing a ready output hauls/publishes it en route; add "common sense" chained prerequisites (clean workspace before a job). |
| **Numbers** | A fully **customizable colonist spreadsheet** — pick any columns (skills, mood, work, gear) and sort/compare the whole colony at a glance. | A **sortable roster table** view of all agents: skills, mood, current job, output stats — management at a glance, complements the pixel view. |
| **RimHUD** | Dense **info overlay** per pawn: health, food, rest, rec, mood bars, skills, current activity, gear, all in one pane. | Rich **agent inspector panel** on click: needs bars + skills + current job + recent thoughts. We have pieces; unify them. |
| **Better Workbench Management** | Adds bill features: **copy/paste bills between benches, "link" bills, better counting/ingredient controls.** | **Bill templates**: define a production rule once, apply to many agents/queues; copy config between agents. |
| **Smart Speed / RocketMan / Performance Optimizer** | Extra game-speed multipliers + **tick-throttling** distant/idle pawns to keep TPS high with big colonies. | **Tick budget:** simulate off-screen/idle agents at a coarser cadence; only fully tick "active" ones. Scales the town cheaply. |
| **Replace Stuff / Wall Light / etc.** | Build-QoL: replace materials in place, embed lights in walls, snap builds. | Minor: **in-place upgrades** of built structures (wood wall → stone wall) without demolish-rebuild. |
| **Dubs Bad Hygiene** | Adds **needs** (bladder/hygiene) + plumbing infrastructure that pawns must satisfy on a schedule. | Optional flavor: extra needs (a "break room" need) that drive agents to specific town locations on a cadence — more life, more routing. |
| **YouDoYou / Work Manager** | **Auto-assigns** work priorities from pawn skills, passions, and colony needs so you don't manage the grid at all. | An **"Auto" toggle** on our priority grid: derive priorities from skill levels + current stockpile deficits (a smarter successor to the bandit that still respects the priority model). Best of both worlds. |

---

## 7. MAPPING TO "THE COMPANY" *(the build spec — ranked by impact)*

Our modules today: bandit + reward in `world_learn.py`; sim loop/needs/mood in `world_sim.py`; skills/stockpile in `world_skills.py`; defs (`NEEDS`, `LEISURE`, `WORKER_POOL`, `DEPARTMENTS`) in `world_defs.py`; tech ladder in `world_tech.py`; construction in `world_construct.py`; raid/walls in `world_raid.py`.

The mapping principle: **RimWorld work types ↔ our real platform jobs.** "Cooking" is a chore that produces meals; our "image generation" is a job that produces an asset. A pawn choosing the highest-priority available job = an agent choosing the highest-priority real task that has work waiting.

---

### ⭐ #1 — Replace the bandit with a Work-Priority Tab + global job scheduler  *(highest impact)*
**RimWorld concept:** the Work tab grid + priority scan (§2).

**Maps to:** a **matrix UI** of *agents × work types*, each cell **0 (off) / 1–4**. Work types are our real activities: `image_gen, video_gen, audio_gen, resell/haul, security/defense, research/study, curation/cleaning, construction, 3d`. Each idle agent scans work types in priority order and takes the **first work type that has an available, unclaimed job.**

**Implementation sketch:**
- **New module `world_work.py`** (replaces `world_learn.choose_activity` as the selector; keep `world_learn` around for the optional "Auto" heuristic).
- **New table `world_work_priority(agent_key, work_type, priority INTEGER)`** — `priority 0` = disabled; 1–4 (allow up to 9 for a Fluffy-style option).
- **WorkGivers:** one function per work type, `available_job(conn, agent) -> job|None`, that answers "is there a real task this agent could start now?" e.g. `image_gen` → any queued generation unclaimed; `resell` → any approved-but-unpublished asset; `security` → any active threat; `research` → tech not yet unlocked. This mirrors §2.3 and reuses `world_defs.live_activity()` counts.
- **Reservation table `world_job_claims(target_id, agent_key, claimed_at)`** so two agents never grab the same task (§3.1). Release on completion/timeout.
- **Scheduler loop** (in `world_sim.simulate`, replacing the `choose_activity` call at line ~165):
  ```
  for wt in work_types_sorted_by(priority_number, then column_order):
      if priority[agent][wt] == 0: continue
      job = WORKGIVERS[wt].available_job(conn, agent)
      if job and reserve(job, agent): assign(agent, job); break
  else:
      idle_or_gather(agent)   # fall to skilling/leisure like today
  ```
- **Tie-break** by skill level (`world_skills.skills_for`) + a stable agent order, matching §2.4 (best/closest pawn wins).
- **Keep DWELL** (`DWELL_SEC`) = RimWorld's "finish current job before re-scanning" (§2.3.5) — we already have it.
- **UI:** a `/company` sub-tab rendering the grid; click a cell to cycle 0→1→2→3→4; shift-click a column header to bump a whole column (Fluffy UX). Add an **"Auto" per-row toggle** that derives priorities from skills + stockpile deficits (YouDoYou idea) — this is the graceful retirement of the bandit: it becomes *one optional policy* inside the priority framework, not the whole brain.

**Why #1:** it converts an opaque bandit into a **player-legible control surface**, which is the entire appeal of RimWorld and directly requested.

---

### ⭐ #2 — Bills: "produce until we have N" for real outputs
**RimWorld concept:** bills with **Do-until-X + pause/unpause band** and worker-skill range (§3.2).

**Maps to:** production targets on our real pipelines. "Keep 20 unpublished images ready," "generate audio until 10 clips queued for the store," throttled by a hysteresis band so we don't over-generate.

**Implementation sketch:**
- **Table `world_bills(id, work_type, target_count, unpause_at, suspended, min_skill, order_idx)`.**
- A bill makes its work type "available" in the scheduler (§1) **only while current output count < target** (and stays off until it drops to `unpause_at`). Counting mirrors RimWorld's "only counts stocked items" — count *finished/available* outputs, not in-flight ones.
- `min_skill` routes complex bills to high-level agents (§3.2), grind bills to novices.
- **UI:** a "Production" panel listing bills, drag to reorder (bill order = priority within a work type), suspend toggle. This is the bridge from "agents wander and gather" to "the town fulfills concrete production goals tied to real store demand."

---

### ⭐ #3 — Stockpile priority tiers + a Manager panel
**RimWorld concept:** stockpile priorities with **auto-reflow** (§3.3) + **Colony Manager** target-driven gathering (§6).

**Maps to:** our single flat `world_skills` stockpile gains **per-resource thresholds**; a **Manager** sets `keep ≥ N logs / ore / planks`, and when a resource dips below its floor the scheduler **raises the priority of the matching gather job** automatically (agents shift to mining when steel is low, to woodcutting when logs are low).

**Implementation sketch:**
- **Table `world_stock_targets(resource, floor, ceil)`.**
- In the WorkGiver for each gather skill, gate/boost availability on `stock[resource] < floor` (make it available, high urgency) and stop at `ceil`. This is Colony Manager expressed through our existing skill/stockpile system — minimal new surface, big autonomy win.
- **UI:** Manager panel with a slider per resource; shows current vs floor/ceil.

---

### ⭐ #4 — Mood → tagged-thought sum + mental breaks that suspend work
**RimWorld concept:** mood = decaying weighted sum of Thoughts; thresholded breaks (§4).

**Maps to:** we already have mood emoji/labels and needs. Upgrade mood to an **explicit thought ledger** and add **breaks** that temporarily hijack an agent's job selection (drama + stakes).

**Implementation sketch:**
- **Table `world_thoughts(agent_key, label, mood_delta, expires_at)`.** Real events write thoughts: "shipped a sale (+8, 1 day)", "job failed/GPU error (−6)", "worked while broke (−4)", "raid won (+12 catharsis, 2.5 days)". Mood = clamp(base + Σ active deltas).
- **Break tiers** keyed off a per-agent `break_threshold` (default 35%): minor (sad-wander around town), major (tantrum — refuses work, kicks a prop), extreme (berserk — attacks a nearby agent / storms off). While broken, the scheduler skips the agent (§4.4). Emit **Catharsis +40 / 2.5d** on recovery to prevent spirals.
- Reuses our existing pixel-movement + emoji layer; mostly new state + a branch in the sim loop (`world_sim._mood`).

---

### #5 — Job driver / toil model + reservations for clean multi-agent execution
**RimWorld concept:** JobDriver → Toils, reservations, interruption (§3.1).

**Maps to:** formalize each assignment as `job = {work_type, target, toils, claim}`. Toils = `go_to(location) → work(ticks) → deliver`. Reservations (from #1's `world_job_claims`) stop double-work. Urgent needs (a raid, an agent "starving"/broke) **interrupt** the current job. This makes the town's behavior legible and debuggable and is the substrate the priority scheduler drives.

---

### #6 — Allowed Areas + Schedule (spatial/temporal gating)
**RimWorld concept:** Allowed Area + Schedule tab (§2.6).

**Maps to:** optionally restrict an agent to a zone (e.g. the "security" agent stays near the walls) and add **day/night schedule rows** (we already have a day/night clock + seasons): agents sleep at night, do recreation in "off" hours, work during work hours. Fluffy-style **time-sliced priorities** ("curate only in the morning") layer on top of #1.

---

### #7 — Research tree with prerequisites & bench tiers
**RimWorld concept:** branching tree, prerequisites, bench requirements (§5.1).

**Maps to:** evolve `world_tech.py`'s linear TIERS into a small **graph** where nodes have `prereqs[]` and some require a "bench" (e.g. a built structure from `world_construct.py`). Research points still come from `study` work (now a scheduler work type). Low-cost, adds meaningful build-order decisions.

---

### #8 — Combat depth: cover, downed-not-dead, doctor/rescue loop
**RimWorld concept:** cover, pain-shock downing, rescue + tend (§5.2).

**Maps to:** in `world_raid.py`, add **cover** (walls give defenders a hit-chance bonus), and make a losing fighter go **"downed"** (not removed) — another agent with a "doctor/security" priority must **rescue & tend** them before they're lost. Turns raids into a rescue drama and gives the Doctor/Patient work types (from #1) a real purpose.

---

### #9 — QoL surface: batch commands, roster table, agent inspector
**RimWorld concept:** Allow Tool verbs, Numbers, RimHUD (§6).

**Maps to:** (a) **batch buttons** ("publish all approved", "rearm defenses", "harvest all ready outputs") that enqueue many jobs at once; (b) a **sortable roster table** (Numbers) of all agents with skills/mood/current-job columns; (c) a **click-to-inspect panel** (RimHUD) with needs bars + skills + current job + recent thoughts. Pure UI, high polish-per-effort.

---

### #10 — Performance: tick budget for idle agents
**RimWorld concept:** RocketMan/Smart Speed tick-throttling (§6).

**Maps to:** simulate idle/off-screen agents on a coarser cadence than active workers so the town scales to many agents cheaply — a `next_tick_at` per agent, active ones every loop, idle ones every N loops.

---

## Build order recommendation
1. **#1 Work-Priority Tab + scheduler + reservations** (foundational; unlocks the rest).
2. **#2 Bills** and **#3 Stockpile targets/Manager** (they *feed* the scheduler concrete goals — this is where autonomy really appears).
3. **#4 Mood/thoughts/breaks** (drama & stakes, mostly independent).
4. Then **#5–#10** as polish/depth.

Ship #1–#3 and the town goes from "a bandit wanders agents around" to "the user sets policy and the town autonomously fulfills production goals" — which is exactly RimWorld's appeal.

---

## 11. Construction / Building System — deep dive + mapping

*Focused follow-up: our current build is one sequential project at a single site (`world_construct.py` — a lone `build_project` in `world_meta`, an agent's construction-skilling nudges one progress bar, finish → `_start_next`). RimWorld's system is fundamentally **many concurrent, individually-placed jobs** fed by hauled materials and picked up by any free builder via the same work scheduler. Here's how it works and how to get there.*

### 11.1 The Blueprint → Frame → Built pipeline
RimWorld builds anything (walls, doors, furniture, turrets, art) through a **three-stage lifecycle**:

1. **Blueprint (ghost).** The player places a translucent blueprint on the grid — free, instant, no materials committed. It's just an *intent* marker with a **material bill** attached (e.g. a stone wall blueprint "owes" 5 stone blocks). Blueprints can be cancelled instantly with zero cost. Nothing is reserved from stockpiles yet.
2. **Frame (materials arriving).** Once a blueprint exists, it generates **hauling jobs**: "deliver resource X to this blueprint." Haulers (or the builder itself) carry materials from stockpiles to the site. As materials arrive the ghost becomes a **frame** — a half-real skeleton that now physically holds the delivered resources. A frame only becomes buildable **when all its material debt is satisfied.** If you cancel/deconstruct a frame, the already-delivered materials drop on the ground (partial refund of what was hauled).
3. **Built (construction work).** With materials in place, a pawn with **Construction** enabled does **Work-To-Build** — a fixed work amount (a stat per building; e.g. a wall is cheap, a sculpture is huge) modulated by the builder's **Construction Speed**. When work fills up, the frame becomes the **finished building**, and (for furniture/art) a **quality roll** is made from the builder's skill (§11.4).

Key design point: **material delivery and construction labor are separate job types** (Hauling vs Construction). This is why builds parallelize so well — one pawn hauls bricks while another lays them. *(A builder is always allowed to haul materials to a building it is personally working on, even if Hauling is disabled for it — "haul to blueprint" is otherwise a low-priority hauling task, below haul-to-stockpile.)*

### 11.2 Multiple simultaneous projects (the big one)
There is **no single "build site."** Every blueprint is an **independent job on the map**, and a large wall you drag out is actually **N separate per-tile blueprints**, not one order. Consequences:

- **Any** idle constructor scans for the **nearest reachable frame/blueprint** whose materials are ready (or, if it can also haul, an unbuilt blueprint it can supply) and takes it — same first-available-highest-priority scan as all work (§2.3). Many builders naturally spread across many builds.
- **Reservations** (§3.1) ensure two builders don't claim the same tile; they fan out to different tiles/projects.
- Vanilla: **one pawn per blueprint tile** at a time (mods like **MultiConstruction / Team Builders** let several pawns co-work one blueprint to finish faster). Wall-drags are already "parallel" because each tile is its own job.
- **Pro tip the game rewards:** a temporary **Critical stockpile at the build area** so builders don't run across the map per brick — i.e. **material staging** matters.

So "multiple concurrent projects" isn't a special mode in RimWorld — it's the *default*, because a build is just a pile of small independent jobs the scheduler distributes.

### 11.3 Placement & validity
- **Grid + rotation.** Buildings occupy 1+ cells; rotate before placing (doors/furniture have a facing + an "interaction spot" that must stay clear).
- **Collision/terrain rules.** Can't place on impassable/occupied cells, over existing buildings (unless the mod allows replace), or on invalid terrain (some need solid ground, not water/marsh). Blueprint turns **red** if invalid.
- **Roofs** are a separate paint-on **"build roof area"** designation — **no materials**, built/removed by construction work; auto-collapse if unsupported (max 6 tiles from a support). Analogous to our "zones," not to material builds.
- **Mass placement / templates.** Drag to place many; the **Blueprints mod** lets you **capture an existing room (walls+floors+furniture) and paste it** repeatedly as a batch of blueprints — copy-paste rooms.

### 11.4 Quality & skill
Furniture, art, and some structures roll a **quality tier**: **Awful → Poor → Normal → Good → Excellent → Masterwork → Legendary.** The roll is a distribution centered on the builder's **Construction skill (0–20)**:
- Skill 0 ≈ Awful mean; **Normal mean around skill 6**; ~skill 4 gives ~50% chance of ≥Normal.
- **Legendary is unreachable by normal work** even at skill 20 — it requires an **Inspiration** (and even then ~60%).
- Quality drives **beauty, market value, and effectiveness** (a Masterwork bed gives better rest; a good turret, etc.).
- **Build failure:** low-skill builders have a chance to **fail** a construction tick, wasting a fraction of materials (resources can be lost). Higher skill = higher **Construction Success Chance** + faster **Construction Speed**.
- **The "finisher" trick:** let a novice grind a high-work item to ~99%, then the master lays the final tick to capture the quality roll.

### 11.5 Deconstruct / re-build / repair
- **Deconstruct** (a Construction job): removes a building and **refunds ~50% of its build cost** in materials (found map ruins deconstruct for free materials). Speed scales with the item's work-to-build and the pawn's construction speed.
- **Cancel** a blueprint = free; **cancel a frame** = drops the materials already hauled.
- **Repair:** damaged buildings **inside the Home Area** are auto-repaired (no materials) by any pawn with Construction, eventually — or force-prioritized. Outside Home Area, no auto-repair. (This ties to our raid/wall repair already in `world_raid.py`.)
- **Replace-in-place** (mod **Replace Stuff**): upgrade a wall's *material* (wood→stone) without a demolish/rebuild cycle — it only charges the material delta.

### 11.6 Relevant mods → ideas to borrow
| Mod | What it does | Idea to borrow |
|---|---|---|
| **Blueprints** | Capture a room's walls/floors/furniture and **paste the whole template** as a batch of blueprints; export/import to disk. | **Room/preset templates**: user saves a cluster of structures and stamps it as many blueprints at once. |
| **MultiConstruction / Team Builders** | Let **several builders co-work one blueprint** for faster finish. | Allow **N builders assigned to one big project**, summing their per-tick construction points. |
| **Smarter Construction** | Fixes pawns boxing themselves in / building in an order that blocks access — **build-order pathing awareness.** | When auto-ordering builds, respect **dependency/adjacency** (don't strand a builder or build the door last). |
| **Replace Stuff** | Upgrade a structure's material **in place**, charging only the delta. | **In-place upgrade** action: wood statue → stone statue costs only the difference, keeps the slot. |
| **Achtung!** | **Draft-drag** to issue construction/orders to a whole group by dragging across tiles. | **Drag-to-place** many blueprints and **drag-assign** several agents to a project in the play-god editor. |
| **Perfect Placement / auto-rotation** | Placement QoL: snapping, ghost interaction-spot preview, auto-rotate. | Placement UX in our map editor: snap to grid, show footprint validity (red/green ghost). |

---

### 11.7 MAPPING → evolve "The Company" from one sequential build to a RimWorld-grade system

**Goal:** replace the single `build_project` with **many concurrent, user-placed ghost blueprints** that (a) pull **materials from the company stockpile** via a per-project **material debt**, then (b) accrue **construction work from any available agent** through the **Work-Priority scheduler (§7 #1)**, producing a **quality-tiered** finished structure, with **deconstruct/repair**. This turns construction into a first-class *work type* rather than a hidden progress bar.

**Data model — extend `world_construct.py` into a real table (`world_structures`).** Replace the two JSON blobs in `world_meta` with rows:
```
world_structures(
  id INTEGER PK,
  kind TEXT, name TEXT,          -- from STRUCTURES catalog
  x INTEGER, y INTEGER, rot INTEGER,   -- placed grid position (play-god)
  tier INTEGER,                  -- min tech tier gate (keep existing)
  status TEXT,                   -- 'blueprint' → 'frame' → 'built'  (+ 'deconstructing')
  material_cost TEXT (json),     -- what it owes, e.g. {"ore":20,"planks":10}
  material_have  TEXT (json),    -- what's been hauled so far
  work_total INTEGER,            -- = STRUCTURES.work  (Work-To-Build)
  work_done  INTEGER,
  quality TEXT,                  -- rolled on completion (awful..legendary)
  built_by TEXT,                 -- agent_key who laid the final tick
  hp INTEGER, max_hp INTEGER,    -- for repair (ties to raid/walls)
  created_at, built_at
)
world_build_claims(structure_id, agent_key, role, claimed_at)  -- role: 'haul' | 'build'
```

**Lifecycle (mirrors §11.1), driven by the scheduler, not a global tick:**
1. **Place (play-god / map editor).** User drops a ghost → insert row `status='blueprint'`, `material_have={}`, validity-checked against grid+tier. **No stockpile spend yet** (RimWorld commits nothing at blueprint stage — big change from our current up-front `WS.spend`).
2. **Haul work type (new/extends `resell`/hauling in §7 #1).** A blueprint with unmet `material_cost` emits a **haul job** per missing resource; a hauling-enabled agent "reserves" it, decrements the **company stockpile** (`world_skills.spend` incrementally), and adds to `material_have`. When `material_have >= material_cost` → `status='frame'`. This is where materials get "allocated from the stockpile hauled/allocated" — incrementally, cancellable (refund `material_have` on cancel).
3. **Construction work type.** A frame becomes an **available Construction job** in the scheduler. Any agent with Construction priority > 0 reserves the nearest frame, and each tick adds `construction_points = BASE * skill_mult(agent) * tech_bonus` to `work_done` (reuse the math already in `advance()`), with a small **failure chance** at low skill (waste a bit of `material_have`). At `work_done >= work_total` → `status='built'`, **roll quality** from the finisher's Construction level, set `built_by`, place the permanent sprite at (x,y).
4. **Parallelism for free.** Because each structure is its own row with its own claim, **many agents build many projects at once** — exactly RimWorld's default. Optionally allow **multiple builders per project** (MultiConstruction) by summing points from all `role='build'` claims on that id.

**Scheduler tie-in (this is the crux).** Add two WorkGivers to the §7 #1 framework:
- `construction.available_job(agent)` → nearest `status='frame'` with an open build-claim.
- `hauling.available_job(agent)` → nearest `status='blueprint'` still owing materials the stockpile can supply.
Priority number on the Work grid decides who builds vs. who keeps generating images. Tie-break by Construction skill + distance (agent x,y vs structure x,y). **This retires the "single build site + `advance(points)` firehose"** in favor of per-agent, per-project reservations.

**Quality (§11.4).** `roll_quality(level)`: distribution centered ~level/3 across `[awful,poor,normal,good,excellent,masterwork]` (legendary only via an "Inspiration" event). Store on the row; surface as a ⭐ badge; feed **beauty/mood thoughts** (a Masterwork statue → "+ impressive art nearby" thought in §7 #4) and, where relevant, function (a good Watchtower → bonus in `world_raid.py`).

**Deconstruct / repair (§11.5).**
- **Deconstruct** = a Construction job on a `built` (or the user right-clicks in play-god): work it down, then **refund ~50%** of `material_cost` to the stockpile, delete row / free the slot.
- **Cancel blueprint** = free delete; **cancel frame** = refund `material_have`.
- **Repair** = reuse the raid/wall repair loop: a `built` with `hp < max_hp` in "home area" emits a Construction repair job (no materials), restoring hp. Unifies with `world_raid.py` walls so defenses and décor share one repair system.
- **Replace-in-place** (Replace Stuff): an upgrade action that charges only the material delta and swaps `kind`/tier without demolishing.

**UI (play-god map editor + Company tab).**
- **Ghost placement:** click-to-place / drag-to-place blueprints on the grid; red/green footprint validity; rotate. Show each ghost with a **materials bar** (have/owe) and a **work bar** (done/total), plus assigned-builder pips.
- **Templates (Blueprints mod idea):** save a selected cluster as a named preset, stamp it as many blueprints.
- **Build queue panel:** list all in-flight structures with status blueprint/frame/built, %, and quality on completion — the construction analog of the §7 #2 bills panel.

**Migration.** Keep the `STRUCTURES` catalog (add `footprint`, optional `hp`); one-time convert the current `built_structures` JSON into `world_structures` rows with `status='built'`; drop the singleton `build_project`. `snapshot()` returns the row list instead of one `current`.

**Build order:** (1) table + lifecycle statuses + incremental material debt; (2) two WorkGivers wired into the §7 #1 scheduler + claims; (3) quality roll + thoughts; (4) deconstruct/repair + replace-in-place; (5) play-god placement UI + templates. Steps 1–2 alone deliver the headline win: **the town builds many things at once, placed by the user, materials hauled from the stockpile, work shared by whichever agents are free.**

---

## Sources
- [Work — RimWorld Wiki](https://rimworldwiki.com/wiki/Work) · [Menus](https://rimworldwiki.com/wiki/Menus)
- [Bill — RimWorld Wiki](https://rimworldwiki.com/wiki/Bill)
- [Stockpile zone](https://rimworldwiki.com/wiki/Stockpile_zone) · [Zone/Area](https://rimworldwiki.com/wiki/Zone/Area) · [Growing zone](https://rimworldwiki.com/wiki/Growing_zone) · [Home area](https://rimworldwiki.com/wiki/Home_area) · [Allowed area](https://rimworldwiki.com/wiki/Allowed_area)
- [Mood](https://rimworldwiki.com/wiki/Mood) · [Mental break](https://rimworldwiki.com/wiki/Mental_break) · [Mental Break Threshold](https://rimworldwiki.com/wiki/Mental_Break_Threshold) · [Thoughts](https://rimworldwiki.com/wiki/Thoughts)
- [Research](https://rimworldwiki.com/wiki/Research) · [Multi-analyzer](https://rimworldwiki.com/wiki/Multi-analyzer) · [Hi-tech research bench](https://rimworldwiki.com/wiki/Hi-tech_research_bench)
- [Combat](https://rimworldwiki.com/wiki/Combat) · [Injury](https://rimworldwiki.com/wiki/Injury) · [Health](https://rimworldwiki.com/wiki/Health) · [Downed](https://rimworldwiki.com/wiki/Downed) · [Defense tactics](https://rimworldwiki.com/wiki/Defense_tactics)
- Modding: [Job/Toil tutorial](https://rimworldwiki.com/wiki/Modding_Tutorials/Code_MendingJob) · [How Pawns Think](https://github.com/roxxploxx/RimWorldModGuide/wiki/SHORTTUTORIAL:-How-Pawns-Think)
- Mods: [Work Tab (Fluffy) GitHub](https://github.com/fluffy-mods/WorkTab) · [Work Tab Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=725219116) · [Colony Manager GitHub](https://github.com/fluffy-mods/ColonyManager) · [Colony Manager Redux](https://steamcommunity.com/sharedfiles/filedetails/?id=3310027356) · [Better Workbench Management](https://steamcommunity.com/sharedfiles/filedetails/?id=935982361) · [RocketMan](https://steamcommunity.com/sharedfiles/filedetails/?id=2479389928)
- Guides: [GameRant — 7 Best QoL Mods](https://gamerant.com/rimworld-best-quality-life-mods/) · [PCGamesN — Best RimWorld Mods](https://www.pcgamesn.com/rimworld/best-rimworld-mods) · [Work Tab Mod — RimWorld Base](https://rimworldbase.com/work-tab-mod/)
- Construction: [Work To Build](https://rimworldwiki.com/wiki/Work_To_Build) · [Quality](https://rimworldwiki.com/wiki/Quality) · [Deconstruct](https://rimworldwiki.com/wiki/Deconstruct) · [Hauling](https://rimworldwiki.com/wiki/Hauling) · [Colony Building Guide](https://rimworldwiki.com/wiki/Colony_Building_Guide) · [Roof](https://rimworldwiki.com/wiki/Roof)
- Construction mods: [Blueprints](https://steamcommunity.com/sharedfiles/filedetails/?id=708455313) · [MultiConstruction](https://steamcommunity.com/sharedfiles/filedetails/?id=3562530209) · [Team Builders](https://steamcommunity.com/sharedfiles/filedetails/?id=3570660265) · [Smarter Construction](https://steamcommunity.com/sharedfiles/filedetails/?id=2202185773) · [Builders Being Dumb? (guide)](https://rimworldhub.com/post/rimworld_builders_being_dumb_heres_the_fix)
