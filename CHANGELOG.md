# Changelog

All notable changes to **Store Command Center**. This project is in active development —
**v2 is on the way**. Dates are the working line; entries land here as they're built.

Everything autonomous is **gated and defaults off**. Three floors never move, in any version:
real money movement (payouts / withdrawals / transfers) always requires an explicit human
action; the minors/CSAM and non-consensual-intimate-imagery protections are always-on and
**not** toggleable; autonomy only ever operates *inside* the existing approval gates.

---

## [Unreleased] — v2 (in progress)

### Added — features
- **Video Studio** — drop a storyboard prompt → scenes / shots → **matched, layered audio**
  (a voiceover reads the script/captions via TTS, over background music + sound effects) →
  export. Short and long videos; multiple clips stitch into a scene, scenes into a film.
- **Multi-platform social publishing** — **YouTube**, **TikTok**, and **Instagram / Facebook**
  adapters (gated, opt-in). Publishes real videos; post-analytics feed back into the taste model.
- **Content loop** — trends → auto-storyboard, a **meme quick-mode** (idea → short + caption +
  audio), a real **auto-scheduler** that publishes at the set time, and analytics → taste.
- **Company agents produce real content** on the clock (fixes idle departments).
- **Reworked God Panel** — a 30-capability catalog in tidy groups, a live **agent-loops graph**
  (who's in charge, capability access, votes/reviews, schedules), and optional god-tier
  **lieutenants** you manage:
  - **✝️ Jesus** — an optional constructive stand-in operator (pure delegation, gated).
  - **😈 Satan** — his adversarial mirror: a red-team / worst-case reviewer. Together they give
    every prediction, review and forecast a **best *and* worst case** (a calibrated 0–10 band)
    instead of one optimistic number — the "angel and devil on your shoulder," with you in the
    middle. Both default **off**; both are held to the exact same gates and floors as every agent.
- **Company HQ rework** — an Iron/Steel-age multi-section complex (warehouse & shipping, offices,
  utilities) with saved **progression stages** so the HQ evolves through eras.
- **Image sizing / export** — download any design at Etsy-spec (square, size-capped) or web sizes.
- **Income tracking** — manual entry plus **read-only** PayPal / Printify / on-chain importers
  (money-*in* visibility only; there is no autonomous spend path anywhere).
- **Per-model VRAM gating for video** — models that won't fit the GPU fail fast with a clear
  message instead of an out-of-memory crash.

### Fixed — bugs
- **Long-format video** now reliably compiles multiple clips into one file (concat fallback for
  mismatched segments).
- **NSFW prompt-enhancer** no longer false-refuses and echoes the prompt back.
- **Image generation** prompt-quoting fixed — rich prompts no longer break the generator.
- **Unified GPU queue** — fixed VRAM starvation from out-of-queue model loads; scheduler
  anti-starvation for image/video work.
- **TikTok publishing** — frame-rate + audio transcode and creator-info gating (fixes upload
  rejections).
- **Social media picker** — filters videos vs images; NSFW media excluded from the attach picker.
- **Etsy** — a clean "reconnect needed" state instead of repeated 400 errors.
- **Rogue-agent watch** — recognizes authorized system actors (no more false "unknown actor"
  alerts) while still watching them for anomalous bursts.
- **Design records** — path-integrity repair for moved data directories.

### Safety — always-on (restated)
- Real money movement always requires explicit human approval.
- Minors/CSAM and non-consensual-intimate-imagery protections are always-on and not toggleable.
- New autonomous features default **off** and act only inside the existing gates.

---

## [1.x] — current stable (`main`)

The shipped feature set — the dashboard, **The Company** pixel-art town, the buddy system,
local image/video/audio/3D generation on a unified GPU queue, the storefront + services
pipeline, JellyCoin, and the full gates-and-toggles system. See the
[README](README.md) and the [wiki](../../wiki) for the complete reference.
