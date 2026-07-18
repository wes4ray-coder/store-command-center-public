# The Company — architecture & scalability blueprint

A living pixel-art "company town" where every character maps to real work on the
platform. Agents earn coins for **real completed store work**, have Sims-style needs
and moods, pay rent, wander, voice opinions, vote in town meetings, and unlock
company milestones. This document is the map: how it's built, how to extend it, and
where it scales.

## Design tenets

1. **Truth-backed.** Coins/XP come only from real completed work (monotonic DB
   counters), never from idling. The world reflects the platform, it doesn't invent.
2. **One writer, many readers.** A single background ticker advances the sim; the API
   only ever reads. Any number of browser tabs is cheap.
3. **Never dump models on the GPU.** Every LLM call goes through the orchestrator
   queue (`world_defs.run_llm_job`); image gen through `orch.image_acquire`.
4. **Data-driven content.** New milestones, incidents, departments, upgrades, needs
   and places are dict entries in `world_balance.py` / `world_defs.py` — not code.
5. **Thin transport.** `routers/world.py` is endpoints only; behaviour lives in modules.

## Module map

| Module | Responsibility | Depends on |
|---|---|---|
| `world_defs.py`   | constants, roster, `seed`, `live_activity`, meta/log helpers, **`run_llm_job`** (the one GPU-queue gateway) | deps |
| `world_balance.py`| **all tuning** + data-driven registries (`ACHIEVEMENTS`, `INCIDENTS`) | — |
| `world_sim.py`    | the tick: event-driven economy, needs, bills, behaviour, mood | defs, balance |
| `world_gov.py`    | thoughts, opinions, meetings & voting, directives (LLM via queue) | defs |
| `world_systems.py`| achievements, incidents, event retention, company summary | defs, balance |
| `world_build.py`  | pixel-art prop generation + autobuild (image gen via queue) | defs, deps |
| `world_ticker.py` | **background loop** that owns advancement (started in `main.py`) | all above |
| `routers/world.py`| HTTP surface — endpoints only, read-only state | all above |

Frontend: `static/js/tab-world.js` (canvas renderer + panels; symbolic locations,
client-side animation). DB: `world_agents`, `world_props`, `world_events`,
`world_meta`, `world_ledger`, `world_suggestions`, `world_meetings`,
`world_directives`, `world_achievements` (schema in `db.py`).

## Data flow

```
                 ┌─────────────── world_ticker (daemon, every 8s) ───────────────┐
                 │ simulate → autobuild → achievements                           │
                 │ cadenced: opinion(queue) · incident · meeting → directive · prune │
                 └───────────────────────────┬──────────────────────────────────┘
 real store work (generations/videos/designs/…, OpenClaw task_runs)  writes world_* tables
                                             │
 browser ──GET /api/world/state (read-only)──┘ ──►  canvas + panels (poll 3s, animate 60fps)
 browser ──POST think/opinion/meeting/want/buy/directive──► queue/DB
```

## Extension points (how to add …)

- **A department:** add to `DEPARTMENTS` (world_defs) + a desk position in
  `DEPT_POS` (tab-world.js) + optionally a `DEPT_TOOL` entry.
- **A paid work signal:** add a row to `WORK_METRICS` (world_sim): a monotonic
  `COUNT(*)` SQL + the job_class it credits. Pay is automatic on the delta.
- **An upgrade:** append to `UPGRADES` (world_defs). **A need:** add to `NEEDS`
  (defs) + `NEED_DECAY`/`PLACE_RESTORE` (balance) + a bar in tab-world.js.
- **A place:** add to `PLACE_RESTORE` (balance) + `TOWN_POS` (tab-world.js).
- **A milestone:** append a dict with a `check(summary)` lambda to `ACHIEVEMENTS`.
- **An incident:** append a dict with `effects` to `INCIDENTS`.
All picked up automatically — no engine edits.

## Scalability

- **Sim ⟂ viewers:** the ticker is the only writer; reads are O(rows). To scale past
  one process, move the ticker to a dedicated worker (or APScheduler/systemd) and
  keep the API read-only — no code change to the endpoints.
- **Bounded growth:** `world_events` is pruned to `EVENTS_RETENTION`; `world_ledger`
  is append-only (rotate/prune later if needed).
- **GPU is the scarce resource:** serialized by the orchestrator (one image render at
  a time via `_gen_lock`; LLM jobs queued). World load never competes uncoordinated.
- **Single-writer caveat:** run exactly one ticker against a given `store.db`
  (prod). Extra short-lived instances double-tick; the 2s debounce softens it.

## Roadmap (next systems — scoped for drop-in)

- **"Play god" edit mode (requested):** a toggle that lets the user directly move,
  place, resize and customise things on the grid — drag buildings/props to new
  tiles, resize via handles, drop new shops/houses/trees, edit a location's size &
  placement, recolour/relabel. Persist edits (a `world_layout` override table or
  JSON) so a hand-tuned map survives regeneration. Needs: hit-testing in world
  space (WM.screenToWorld), a selection/drag/resize layer over the canvas, and a
  save endpoint. The map generator already exposes `WM.buildings`/`WM.locations`/
  `WM.decor` to seed it.
- **Generated futuristic pixel-art tilesets** — replace flat tile colors + procedural
  decor with generated sprites (grass/road/wall/tree/roof), via the image pipeline.

- **Directive → action:** the voted directive triggers a real store action (e.g.
  "re-run top themes" → enqueue generations), closing the loop from vote to work.
- **Relationships/social graph:** per-pair affinity that grows when agents share a
  place; enables friendships, rivalries, mood contagion. Table `world_bonds`.
- **Skills & specialization:** per-agent skill levels per work type (beyond global
  level); faster/better output as they specialize.
- **Roster growth (hiring/firing):** treasury-funded hiring when a department is
  overloaded; retirement when perpetually idle.
- **Treasury megaprojects:** spend `company_fund` on shared builds (fountain, statue,
  new wing) proposed and voted in meetings.
- **Seasons / day-night:** a world clock scaling activity, decor, and events.
- **Notifications & daily digest:** surface achievements/incidents to the user; a
  end-of-day town summary written to `_TOWN_HALL.md`.
- **Agent chat:** short LLM dialogues between co-located agents (queued, throttled).

## Balance knobs

All in `world_balance.py`: wages/XP, rent/bills + cycle, company tax, tick + cadence
intervals, needs decay/restore, event retention, and the achievement/incident
content. Tune there; never in the engine.
