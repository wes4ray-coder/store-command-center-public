# Store — Hardening Roadmap

The app is feature-rich but thin on foundations. This is the plan to fix that, in
priority order (most risk-reduction first). Worked top-down. Status updated as we go.

Context: ~22K LOC backend, 31 routers, 45 JS files, handles **real money** (Etsy/Printify
fees, a PayPal-backed budget ledger), runs live on `master` behind nginx/Cloudflare.

---

## 1. Automated tests  ✅ DONE (2026-07-15)
**Was:** effectively zero tests. Every change landed on live `master` unverified except by hand.

**Shipped:** `tests/` suite — `./run_tests.sh` → **42 passing**, isolated via `STORE_DATA_DIR`
(a hard `conftest` guard aborts if `DB_PATH` isn't the temp dir, so tests can never touch
live `store.db`):
- [x] `test_pricing.py` — `calc_retail_price` invariants ($X.99, achieves target margin, monotonic, doc example)
- [x] `test_prompts.py` — every key resolves a default, override/reset round-trips, templated prompts `.format()` without `KeyError`
- [x] `test_api_smoke.py` — auto-discovers safe GET endpoints from the OpenAPI schema, authenticates, asserts **no 5xx**; also asserts anon `/api` is 401
- [x] `run_tests.sh`; `tests/ui_regression.py` — Playwright E2E (all tabs + Studio sub-tabs + Prompts editor), password from `STORE_TEST_PASSWORD`, retry-de-flaked, **passes**

**Bugs the suite caught + fixed on day one:** `/api/printify/images`, `/api/portal/wp-products`,
`/api/cults3d/creations` all returned **5xx for a missing-config error** (should be 4xx — a 5xx
would page you for something that's just "not set up yet"). Fixed: re-raise `HTTPException`
instead of wrapping it, and Cults3D errors now carry a proper status (`cults.py`).

**Discovered → both resolved 2026-07-16:**
- **World-tab 404 — FOUND + FIXED.** Not a static asset (verified all 9 character sheets, 7
  mob sheets, 34 `_extracted/` props, NPC + tilemap all exist; manifest has 0 atlases). It was
  the **community board** (`world-board.js` → `<img src="${it.url}">`): the board serves a
  design's generation-time `designs/pending/…` URL, but the file **moves** to approved/rejected
  on review, so the stale URL 404s (intermittent, state-dependent, benign). Fixed at the source
  — `routers/world_ops.py` `_designs_url()` resolves each image to its CURRENT folder (or skips
  it if truly gone) — AND in the UI: the board `<img>` now has an `onerror` → 🖼 placeholder.
  2 tests in `test_board_url.py`.
- **"Slow" cults3d/library/treasury — false positive.** Measured in isolation they paint in
  ~260ms each (faster than the dashboard's ~520ms). The audit's "slow/❌" was the rapid 15-tab
  sweep overloading external APIs, not a real blocking await (cults3d already loads async with a
  spinner + error state). Only Settings genuinely blocked (on Etsy) and was already fixed. No change.

## 2. Secrets at rest  ✅ DONE (2026-07-15)
**Was:** 14 credential keys (Etsy tokens, Cults3D/HF/LM Studio keys, WooCommerce, PayPal,
mail) sat **plaintext** in `store.db`.

**Shipped:** `app/crypto.py` — Fernet encryption; key from `STORE_SECRET_KEY` env or a local
`DATA_DIR/.secret_key` file (chmod 600, gitignored) — **never in the DB**. `dec()` is
passthrough-safe (legacy plaintext still reads), so the rollout is backward-compatible.
`migrate_encrypt_secrets()` runs on startup (idempotent). Reads decrypt transparently at the
choke points (`get_setting`, `_get_etsy_settings`, `_get_printify`, `cults_creds`, `dec_secrets`
on the inline dicts); writes encrypt secret keys (settings PATCH, etsy-token refresh, PayPal,
mail, generated tokens). GET `/api/settings` decrypts for the UI. 6 tests in `test_crypto.py`.

**Verified live (real creds):** after restart all 14 secrets are `enc:v1:…` in a raw DB dump,
yet Printify, Etsy, WooCommerce, and Cults3D all still authenticate; `/api/settings` returns
decrypted values to the UI; 48 tests green. Pre-migration backup at `backups/store-pre-encrypt-*`.

**MCP localhost bypass — reviewed, left as-is (deliberate):** external traffic arrives via nginx
as the docker-network IP (needs a session), so only genuine localhost processes hit the `/api/`
bypass — that's the intended trust boundary for OpenClaw/cron/agents. A per-request MCP token
would add defense-in-depth but would break the current integration; not worth it now.

**Done when:** ✅ secrets unreadable in a raw DB dump; app reads/writes them normally.

## 3. Money correctness  ✅ DONE (2026-07-15)
**Was:** `calc_retail_price` reassigned `rounded` 4× with dead branches + a `# Simplified:`
comment mid-function; the money code had no tests.
**Shipped:** rewrote `calc_retail_price` to a clean 6-line single path (smallest $X.99 ≥
base/(1−margin)). **Provably behavior-preserving** — 0 differences vs the old version across
51,395 base×margin combos. Added `test_ledger.py` (5 tests) for the God Console budget:
`balance_cents` (signed sum), negative-balance-means-owed, `cycle_spend_cents` (spends only),
`can_spend` cap enforcement (boundary, over-cap, zero/negative cost), cap-0 blocks all.
**Done when:** ✅ pricing + ledger have tests; pricing fn is a clean single path. 53 tests green.

## 4. Automated off-site backups  ✅ DONE (2026-07-15)
**Was:** backups were a manual button; `scheduler.py` had no backup job.
**Shipped:** `app/backups.py` — a CONSISTENT online SQLite snapshot (`sqlite3` backup API,
safe mid-write), gzipped, written to the local `backups/` dir AND an off-box destination,
with retention (`backup_keep`, default 14). Wired into `scheduler.py` to run on startup +
nightly (gated by `backup_enabled`, `backup_interval_min`). The `.secret_key` is copied
alongside each backup so a restore actually works (the DB is encrypted — secure the backup
medium accordingly). Endpoints `/api/system/db-backup` (run now) + `/api/system/db-backup/status`.
Settings: `backup_dest_dir` (off-box path; skipped gracefully if the drive is unmounted).
3 tests in `test_backups.py`.
**Verified live:** configured `backup_dest_dir=/media/user/Backup/store-backups`; a run wrote
2 copies (local + external drive); the external copy decompresses to a **valid, queryable DB
snapshot** (152 settings rows, secrets `enc:v1:`). 56 tests green.
**Done when:** ✅ runs on a schedule with no clicking; the off-box copy is a verified-restorable snapshot.

## 5. Unified GPU scheduler  ✅ DONE (2026-07-16, integrated live)
**Was:** store + OpenClaw fought over LM Studio's single VRAM slot; the orchestrator's LLM
queue was plain FIFO; the "universal queue" was display-only.

**Shipped:** `app/gpu_scheduler.py` — the pure decision core (`Job`, `effective_priority`
aging, `pick_next` = priority → model-affinity batching → anti-starvation aging), 8 unit tests.
**Integrated into the orchestrator** surgically: `submit_llm` now records `priority` +
`enqueued_at`; `_drain` picks the next task via `_pick_pending()` → `gpu_scheduler.pick_next`
(**FIFO fallback on any error** so it can never wedge the worker). Priorities set at the submit
sites: **background** (world cognition, dev-swarm, trend scan, security analysis) = 2;
**user-facing** (chat, Enhance, prompt-test) = 0; everything else + the OpenClaw proxy = 1. So
interactive UI work now preempts constant background LLM churn. The **OpenClaw LLM proxy already
existed** (`routers/llm.py` — `/api/llm/v1/chat/completions` runs inside `orch.submit_llm`), so
OpenClaw was already folded into the same queue. Model loading was already robust (evict→load→
verify→retry in `_ensure_loaded`).

**Verified live:** 4 orchestrator-pick tests (priority/affinity/FIFO-tier) + 8 scheduler tests;
generation runs end-to-end through the scheduler (confirmed order == FIFO for equal-priority
same-model, so no regression; a user-priority enhance returns real output). **68 tests green.**

**Optional future (not needed for correctness):** GPU_QUEUE.md's on_first_job/on_drain keep-warm
hooks (pre-warm the model / keep the VLM resident on idle) — a latency optimization only.

---
*Started 2026-07-15. Working #1 first — it's what makes #2/#3 safe to do.*
