"""Schema definitions for the Store DB, extracted verbatim from db.py.

Each function receives an open sqlite3 connection and creates the tables for one
domain (CREATE TABLE IF NOT EXISTS, so it is idempotent). This module must NOT
import db — it takes `conn` as a parameter to avoid an import cycle. db.init_db()
is the orchestrator that opens the connection and calls these in order.
"""


def create_library_table(conn):
    # Ensure library_links table exists
    c0 = conn.cursor()
    c0.executescript("""
    CREATE TABLE IF NOT EXISTS library_links (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        url         TEXT NOT NULL,
        title       TEXT,
        description TEXT,
        category    TEXT,
        submitted_by TEXT DEFAULT 'owner',
        status      TEXT DEFAULT 'pending',  -- pending | approved | rejected | archived
        page_content TEXT,                   -- fetched/archived content (markdown)
        page_path   TEXT,                   -- where it was saved in library
        tags        TEXT,                    -- comma-separated tags
        created_at  TEXT DEFAULT (datetime('now')),
        reviewed_at TEXT
    );
    """)
    conn.commit()


def create_security_tables(conn):
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS security_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT,            -- healthy | needs_attention | unknown
        last_scan_at TEXT,
        report_path TEXT,
        summary_json TEXT,      -- parsed summary for API
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS security_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT,            -- healthy | needs_attention | unknown
        last_scan_at TEXT,
        report_path TEXT,
        summary_json TEXT,      -- parsed summary for API
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS network_clients (
        ip              TEXT PRIMARY KEY,
        name            TEXT,
        first_seen      TEXT DEFAULT (datetime('now')),
        last_seen       TEXT DEFAULT (datetime('now')),
        total_queries   INTEGER DEFAULT 0,
        blocked_queries INTEGER DEFAULT 0,
        top_domains     TEXT,            -- json [[domain,count],...]
        suspicious      INTEGER DEFAULT 0,
        notes           TEXT
    );

    CREATE TABLE IF NOT EXISTS automation_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        action     TEXT,     -- launch | post | fill | inbox | reply | reset ...
        target     TEXT,     -- platform / listing / offer
        status     TEXT,     -- running | done | needs_login | failed
        detail     TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS pihole_actions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        action     TEXT,     -- ban | allow | unban | flag | analyze
        target     TEXT,     -- domain or client
        detail     TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS archive_snapshots (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        url         TEXT NOT NULL,
        title       TEXT,
        rel_path    TEXT NOT NULL,       -- file path under the archive dir
        size        INTEGER DEFAULT 0,
        captured_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS security_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fkey TEXT UNIQUE,        -- stable hash of the issue text
        issue TEXT,
        action TEXT,
        priority TEXT,           -- High | Medium | Low | (unknown)
        status TEXT DEFAULT 'pending',  -- pending | approved | ignored | remediated
        first_seen TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    """)


def create_design_tables(conn):
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        source TEXT,          -- 'trend' | 'news' | 'reddit' | 'manual'
        source_label TEXT,    -- e.g. 'Google Trends'
        tags TEXT,            -- comma separated: 'T-Shirt,Mug'
        status TEXT DEFAULT 'pending',  -- pending | approved | rejected
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS generations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id INTEGER,
        prompt TEXT NOT NULL,
        product_type TEXT DEFAULT 'T-Shirt',
        width INTEGER DEFAULT 1024,
        height INTEGER DEFAULT 1024,
        steps INTEGER DEFAULT 20,
        status TEXT DEFAULT 'queued',  -- queued | generating | done | failed
        image_path TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(proposal_id) REFERENCES proposals(id)
    );

    CREATE TABLE IF NOT EXISTS designs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generation_id INTEGER UNIQUE,
        image_path TEXT NOT NULL,
        prompt TEXT,
        product_type TEXT DEFAULT 'T-Shirt',
        status TEXT DEFAULT 'review',  -- review | approved | rejected
        printify_id TEXT,
        etsy_listing_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(generation_id) REFERENCES generations(id)
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS models3d (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path     TEXT NOT NULL,            -- absolute path to source 3D file
        file_name     TEXT,
        file_ext      TEXT,                     -- stl | obj | 3mf | glb | zip ...
        file_size     INTEGER DEFAULT 0,
        file_hash     TEXT UNIQUE,              -- sha256, dedups backlog rescans
        -- listing metadata (AI-proposed, fully user-editable)
        title         TEXT,
        description   TEXT,
        tags          TEXT,                     -- comma separated
        category_id   TEXT,
        subcategory_ids TEXT,                   -- json list
        price_cents   INTEGER DEFAULT 0,        -- download price; 0 = free
        currency      TEXT DEFAULT 'USD',
        license_code  TEXT DEFAULT 'standard',
        made_with_ai  INTEGER DEFAULT 0,
        -- images
        render_paths  TEXT,                     -- json list of turntable render PNGs
        hero_paths    TEXT,                     -- json list of SDXL hero PNGs
        primary_image TEXT,                     -- chosen cover image path
        -- pipeline
        status        TEXT DEFAULT 'backlog',   -- backlog|review|approved|published|rejected|error
        source        TEXT DEFAULT 'backlog',   -- backlog|generated
        gen_prompt    TEXT,                     -- prompt used if source=generated
        cults3d_id    TEXT,
        cults3d_url   TEXT,
        publish_error TEXT,
        notes         TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now'))
    );
    """)


def create_media_tables(conn):
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt TEXT NOT NULL,
        width INTEGER DEFAULT 832,
        height INTEGER DEFAULT 480,
        num_frames INTEGER DEFAULT 49,
        steps INTEGER DEFAULT 20,
        fps INTEGER DEFAULT 16,
        seed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'queued',
        video_path TEXT,
        model_id TEXT DEFAULT 'Wan-AI/Wan2.1-T2V-1.3B-Diffusers',
        chain_id INTEGER,
        chain_index INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS audio_clips (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kind         TEXT DEFAULT 'music',      -- music | voice
        prompt       TEXT NOT NULL,
        engine       TEXT DEFAULT 'musicgen',   -- musicgen | acestep | stable_audio | mms_tts
        model_id     TEXT,
        duration     INTEGER DEFAULT 8,
        status       TEXT DEFAULT 'queued',      -- queued | generating | done | failed
        audio_path   TEXT,
        progress     INTEGER DEFAULT 0,
        progress_msg TEXT,
        error        TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );
    """)


def create_resell_tables(conn):
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS resell_listings (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        title               TEXT NOT NULL DEFAULT 'Untitled Item',
        description         TEXT,
        condition           TEXT DEFAULT 'Good',
        category            TEXT,
        asking_price        REAL,
        ai_price_min        REAL,
        ai_price_max        REAL,
        ai_analysis         TEXT,
        price_mode          TEXT DEFAULT 'obo',
        min_accept_price    REAL,
        shipping_policy     TEXT DEFAULT 'pickup_only',
        will_ship_min_price REAL DEFAULT 50.0,
        payment_methods     TEXT DEFAULT '["cash"]',
        status              TEXT DEFAULT 'draft',
        platforms           TEXT DEFAULT '{}',
        notes               TEXT,
        created_at          TEXT DEFAULT (datetime('now')),
        updated_at          TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS resell_listing_images (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id  INTEGER NOT NULL,
        image_path  TEXT NOT NULL,
        is_primary  INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(listing_id) REFERENCES resell_listings(id)
    );

    CREATE TABLE IF NOT EXISTS resell_offers (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id      INTEGER NOT NULL,
        platform        TEXT,
        buyer_name      TEXT,
        buyer_message   TEXT,
        offer_amount    REAL,
        buyer_location  TEXT,
        distance_miles  REAL,
        gas_cost        REAL,
        status          TEXT DEFAULT 'pending',
        notified        INTEGER DEFAULT 0,
        created_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(listing_id) REFERENCES resell_listings(id)
    );

    CREATE TABLE IF NOT EXISTS resell_auto_tasks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id  INTEGER,
        platforms   TEXT,
        status      TEXT DEFAULT 'pending',
        result      TEXT,
        error       TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS video_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        concept TEXT,
        status TEXT DEFAULT 'pending',
        model_id TEXT DEFAULT 'Wan-AI/Wan2.1-T2V-1.3B-Diffusers',
        width INTEGER DEFAULT 832,
        height INTEGER DEFAULT 480,
        num_frames INTEGER DEFAULT 49,
        steps INTEGER DEFAULT 20,
        fps INTEGER DEFAULT 16,
        strength REAL DEFAULT 0.7,
        prompts TEXT,
        total_segments INTEGER DEFAULT 0,
        completed_segments INTEGER DEFAULT 0,
        compiled_path TEXT,
        error TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    """)


def create_portal_tables(conn):
    conn.cursor().executescript("""
    -- ── PORTAL (WordPress / WooCommerce bridge) ──────────────────────────────
    -- Greenfield store of items that have no other home in the app: affiliate
    -- products (electronics→soap, links out to Amazon/Newegg/etc.) and software
    -- you promote. Everything else (Etsy/Printify/Cults3D/generated media) is
    -- aggregated live from its own source at push time.
    CREATE TABLE IF NOT EXISTS portal_affiliate (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kind         TEXT DEFAULT 'affiliate',   -- affiliate | software
        title        TEXT NOT NULL,
        description  TEXT,
        price        TEXT,                        -- display price string, e.g. "19.99" ("" = none)
        external_url TEXT NOT NULL,               -- the affiliate / download link (Buy button target)
        image_url    TEXT,                        -- public image URL (optional)
        category     TEXT,                        -- WooCommerce category name
        tags         TEXT,                        -- comma-separated
        button_text  TEXT DEFAULT 'Buy now',
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );

    -- Record of every push to WordPress so the UI can show "already on store"
    -- and offer unpublish. source_ref uniquely identifies the origin item.
    CREATE TABLE IF NOT EXISTS portal_pushes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source      TEXT NOT NULL,   -- affiliate|software|etsy|printify|cults3d|image|video
        source_ref  TEXT NOT NULL,   -- stable id within that source (uid)
        kind        TEXT DEFAULT 'product',  -- product | portfolio
        wp_id       INTEGER,         -- WooCommerce product id (or WP media id for portfolio)
        wp_link     TEXT,            -- permalink
        title       TEXT,
        pushed_at   TEXT DEFAULT (datetime('now')),
        UNIQUE(source, source_ref, kind)
    );

    -- Affiliate PROGRAMS you can sign up for. Seeded from a built-in catalog
    -- (routers/portal.py _seed_programs). After you sign up, save your tracking
    -- tag/publisher id here; it's auto-appended to affiliate product links that
    -- reference this program (see _apply_program_tag).
    CREATE TABLE IF NOT EXISTS portal_programs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        pkey        TEXT UNIQUE,       -- stable key, e.g. 'amazon'
        name        TEXT NOT NULL,
        network     TEXT,              -- Direct | Impact | Awin | CJ | Rakuten | …
        signup_url  TEXT,              -- where to apply
        tag_param   TEXT,              -- URL query param to append the tag (e.g. 'tag'); '' = manual
        tag_value   TEXT,              -- YOUR tag / tracking id after signup
        account_id  TEXT,              -- optional publisher/account id or login note
        notes       TEXT,
        signed_up   INTEGER DEFAULT 0, -- 0=not yet, 1=applied/approved
        sort        INTEGER DEFAULT 100,
        is_custom   INTEGER DEFAULT 0, -- 1 = user-added (deletable)
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now'))
    );
    """)


def create_social_tables(conn):
    conn.cursor().executescript("""
    -- ── SOCIAL tab: drafts + scheduler for Instagram / TikTok / YouTube / FB ──
    -- Phase 1 is draft/queue ("copy caption, open the app, mark posted"); the
    -- schema already carries what Phase-2 auto-posting (per-platform APIs) needs.
    CREATE TABLE IF NOT EXISTS social_posts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        title        TEXT,                  -- internal label (optional)
        caption      TEXT,                  -- post text
        hashtags     TEXT,                  -- "#a #b" or comma-separated
        platforms    TEXT,                  -- json list: instagram|tiktok|youtube|facebook
        media_type   TEXT DEFAULT 'none',   -- image | video | none
        media_path   TEXT,                  -- local file path (for download/preview)
        media_url    TEXT,                  -- public URL if uploaded
        status       TEXT DEFAULT 'draft',  -- draft | scheduled | posted
        scheduled_at TEXT,                   -- ISO datetime (optional)
        posted_at    TEXT,
        posted_on    TEXT,                   -- json list of platforms marked posted
        source       TEXT DEFAULT 'manual',  -- manual | generated
        notes        TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );
    """)


def create_swarm_tables(conn):
    conn.cursor().executescript("""
    -- ── DEV SWARM (GitHub tab) ───────────────────────────────────────────────
    -- A proposed job/project/fix the local-model agent swarm works on. Lives on a
    -- working branch (usually dev); when tested + human-approved it's promoted
    -- dev → master → retail. Only ONE model loads in VRAM, so agent turns run
    -- sequentially through the orchestrator.
    CREATE TABLE IF NOT EXISTS swarm_jobs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        title        TEXT NOT NULL,
        spec         TEXT,                     -- the ask / project description
        repo         TEXT,                     -- owner/name (github)
        branch       TEXT DEFAULT 'dev',       -- working branch
        autonomy     TEXT,                     -- gate|auto|step ; NULL = use global setting
        status       TEXT DEFAULT 'proposed',  -- proposed|planning|awaiting_input|coding|
                                               -- reviewing|voting|testing|awaiting_review|
                                               -- approved|pushing|done|failed|paused
        current_agent TEXT,                    -- role currently working
        plan         TEXT,                     -- json: steps the planner produced
        progress     INTEGER DEFAULT 0,
        progress_msg TEXT,
        result       TEXT,
        error        TEXT,
        cron_enabled INTEGER DEFAULT 0,        -- keep working this WIP job on a schedule
        cron_interval INTEGER DEFAULT 30,      -- minutes
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );

    -- Timeline of everything the swarm does on a job: comments, audits, votes,
    -- proposed diffs, plans, system notes. This is the reviewable audit trail.
    CREATE TABLE IF NOT EXISTS swarm_events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id     INTEGER NOT NULL,
        agent      TEXT,                        -- role/name (planner|coder1|reviewer|…)
        kind       TEXT,                        -- comment|audit|vote|diff|plan|question|answer|system|error|test
        content    TEXT,
        vote       TEXT,                        -- approve|reject|abstain (for kind=vote)
        model      TEXT,                        -- which local model produced this
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- Clarifying questions the swarm raises (before fuzzy work, on big changes /
    -- splits / direction). Human answers in the tab; the driver resumes.
    CREATE TABLE IF NOT EXISTS swarm_questions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id      INTEGER NOT NULL,
        agent       TEXT,
        question    TEXT NOT NULL,
        answer      TEXT,
        status      TEXT DEFAULT 'open',        -- open|answered
        created_at  TEXT DEFAULT (datetime('now')),
        answered_at TEXT
    );
    """)


def create_world_tables(conn):
    conn.cursor().executescript("""
    -- ── The Company: gamified pixel-art world ────────────────────────────────
    -- Persistent, named characters. Each maps to a real job class or OpenClaw
    -- agent; identity/XP/level survive restarts (hybrid binding).
    CREATE TABLE IF NOT EXISTS world_agents (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        key         TEXT UNIQUE,                 -- stable id (openclaw agent id or worker slot)
        name        TEXT,                        -- display name (user-renameable)
        kind        TEXT DEFAULT 'worker',       -- openclaw | worker
        job_class   TEXT,                        -- image|video|audio|models3d|etsy|resell|portal|trends|agent
        dept        TEXT,                        -- department desk key
        color       TEXT,                        -- hex accent for the sprite
        sprite      TEXT,                         -- generated sprite PNG path (nullable)
        xp          INTEGER DEFAULT 0,
        level       INTEGER DEFAULT 1,
        coins       INTEGER DEFAULT 0,           -- spendable wallet (earned by REAL completed work)
        coins_earned INTEGER DEFAULT 0,          -- lifetime coins earned
        earn_mult   REAL DEFAULT 1.0,            -- earnings multiplier (raised by upgrades)
        upgrades    TEXT DEFAULT '[]',           -- JSON list of purchased upgrade ids
        debt        INTEGER DEFAULT 0,           -- unpaid rent/bills (drives 'broke' mood)
        -- Sims-style needs (0..100); decay over time, restored by activities/places
        energy      REAL DEFAULT 80,
        fun         REAL DEFAULT 70,
        social      REAL DEFAULT 70,
        fulfillment REAL DEFAULT 55,             -- sense of purpose; only real work refills it
        hunger      REAL DEFAULT 80,
        mood_emoji  TEXT DEFAULT '🙂',
        mood_label  TEXT DEFAULT 'settling in',
        goal        TEXT,                        -- current behavior goal (why they're moving)
        state       TEXT DEFAULT 'idle',         -- idle|working|leisure|sleep|commute
        location    TEXT DEFAULT 'home',         -- symbolic location key
        mood        TEXT,                        -- latest thought/want
        jobs_done   INTEGER DEFAULT 0,
        last_active TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS world_props (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        kind        TEXT DEFAULT 'furniture',    -- building|furniture|decor
        label       TEXT,                        -- castle|chair|computer|table
        location    TEXT,                        -- symbolic location / zone
        x           REAL,
        y           REAL,
        image_path  TEXT,                        -- generated pixel PNG (nullable → placeholder)
        prompt      TEXT,
        status      TEXT DEFAULT 'placeholder',  -- placeholder|queued|generating|done
        owner_key   TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS world_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_key   TEXT,
        kind        TEXT,                        -- thought|want|levelup|job_start|job_done|system|bill|opinion|meeting|move
        text        TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    -- key/value store for sim bookkeeping (last tick, seen-work counters, priority…)
    CREATE TABLE IF NOT EXISTS world_meta (
        key         TEXT PRIMARY KEY,
        value       TEXT
    );
    -- every coin movement (wage/bonus/bill/purchase) for audit + per-agent logs
    CREATE TABLE IF NOT EXISTS world_ledger (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_key     TEXT,
        delta         INTEGER,
        reason        TEXT,
        balance_after INTEGER,
        created_at    TEXT DEFAULT (datetime('now'))
    );
    -- agents' opinions on how to improve the business (feed town meetings)
    CREATE TABLE IF NOT EXISTS world_suggestions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_key   TEXT,
        text        TEXT,
        category    TEXT,                        -- products|marketing|ops|pricing|quality|automation
        votes       INTEGER DEFAULT 0,
        status      TEXT DEFAULT 'open',         -- open|chosen|shelved|done
        created_at  TEXT DEFAULT (datetime('now'))
    );
    -- town meetings: what the crew voted the top priority to fix/build next
    CREATE TABLE IF NOT EXISTS world_meetings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        topic       TEXT,
        decision    TEXT,
        tally       TEXT,                        -- JSON: [{suggestion,votes}]
        created_at  TEXT DEFAULT (datetime('now'))
    );
    -- the town's current actionable mandate (from the latest meeting/vote)
    CREATE TABLE IF NOT EXISTS world_directives (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        text        TEXT,
        source      TEXT DEFAULT 'meeting',      -- meeting|manual
        status      TEXT DEFAULT 'active',       -- active|done|dropped
        created_at  TEXT DEFAULT (datetime('now')),
        resolved_at TEXT
    );
    -- company milestones earned (data-driven registry in world_balance)
    CREATE TABLE IF NOT EXISTS world_achievements (
        id          TEXT PRIMARY KEY,
        label       TEXT,
        earned_at   TEXT DEFAULT (datetime('now'))
    );
    """)


def create_queue_history_table(conn):
    conn.cursor().executescript("""
    -- ── UNIFIED QUEUE completion history ─────────────────────────────────────
    -- The orchestrator's task dict is in-memory only, so finished LLM work used
    -- to vanish from the unified queue the moment it completed (and entirely on
    -- restart). Every LLM task now writes ONE row here at its terminal
    -- transition (done|error|cancelled) — see Orchestrator._record_history.
    -- Media jobs (image/video/audio/3D) already persist their lifecycle in
    -- generations/videos/video_chains/audio_clips, so they are NOT duplicated
    -- here; GET /api/queue/history unions them in at read time.
    CREATE TABLE IF NOT EXISTS queue_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        kind        TEXT DEFAULT 'llm',   -- llm (media kinds union in at read time)
        label       TEXT,                 -- the task desc shown in the queue
        task        TEXT,                 -- prompt-registry task key (if any)
        source      TEXT,                 -- system that submitted it (world|proxy|studio|…)
        model       TEXT,
        status      TEXT,                 -- done | error | cancelled
        error       TEXT,                 -- truncated failure reason
        enqueued_at TEXT,
        started_at  TEXT,
        finished_at TEXT,
        duration_s  REAL
    );
    CREATE INDEX IF NOT EXISTS idx_qhist_finished ON queue_history(finished_at);
    """)


def create_bills_tables(conn):
    """REAL personal bills tracker (Finance → 📆 Bills pane; routers/money/bills.py).

    NOT the game world's in-game bills — those live in world_bills (world_bills.py).
    No credentials are stored here by design: portal_url + notes only.
    Called from routers/money/bills.py at import (same one-time-ensure pattern as
    the money package's _base._ensure_schema), so db.py needs no wiring."""
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS bills (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        category     TEXT DEFAULT '',      -- free-text user category ("utilities", …)
        portal_url   TEXT DEFAULT '',      -- the biller's payment/login page (link only — never passwords)
        portal_note  TEXT DEFAULT '',      -- account nickname / how-to-pay notes (keep secrets out)
        amount_cents INTEGER,              -- NULL = variable amount (prompted at mark-paid)
        cycle        TEXT DEFAULT 'monthly', -- monthly|weekly|yearly|quarterly|once|custom-N-days
        due_day      INTEGER,              -- day-of-month anchor (1-31) so a 31st bill survives Feb
        next_due     TEXT,                 -- YYYY-MM-DD of the next expected payment
        autopay      INTEGER DEFAULT 0,
        active       INTEGER DEFAULT 1,    -- 0 = deactivated (kept for history)
        extra        TEXT DEFAULT '{}',    -- JSON object of arbitrary user-defined fields
        created_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS bill_payments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id      INTEGER NOT NULL,
        paid_at      TEXT DEFAULT (datetime('now')),  -- YYYY-MM-DD (or full datetime)
        amount_cents INTEGER DEFAULT 0,
        note         TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_bills_next_due ON bills(active, next_due);
    CREATE INDEX IF NOT EXISTS idx_bill_payments_bill ON bill_payments(bill_id, paid_at);
    """)
    conn.commit()


def run_migrations(conn):
    c = conn.cursor()
    # Migrations — add columns that might be missing in older DBs
    for migration in [
        "ALTER TABLE generations ADD COLUMN model TEXT DEFAULT 'sdxl_base_1.0.safetensors'",
        "ALTER TABLE designs ADD COLUMN printify_image_id TEXT",
        "ALTER TABLE videos ADD COLUMN model_id TEXT DEFAULT 'Wan-AI/Wan2.1-T2V-1.3B-Diffusers'",
        "ALTER TABLE videos ADD COLUMN chain_id INTEGER",
        "ALTER TABLE videos ADD COLUMN chain_index INTEGER",
        "ALTER TABLE generations ADD COLUMN source TEXT DEFAULT 'pipeline'",
        "ALTER TABLE designs ADD COLUMN source TEXT DEFAULT 'pipeline'",
        # Resell migrations
        "ALTER TABLE resell_listings ADD COLUMN price_mode TEXT DEFAULT 'obo'",
        "ALTER TABLE resell_listings ADD COLUMN min_accept_price REAL",
        "ALTER TABLE resell_listings ADD COLUMN shipping_policy TEXT DEFAULT 'pickup_only'",
        "ALTER TABLE resell_listings ADD COLUMN will_ship_min_price REAL DEFAULT 50.0",
        "ALTER TABLE resell_listings ADD COLUMN payment_methods TEXT DEFAULT '[\"cash\"]'",
        "ALTER TABLE resell_listings ADD COLUMN image_path TEXT",
        # Resell v2 — seller context fields
        "ALTER TABLE resell_listings ADD COLUMN seller_description TEXT",
        "ALTER TABLE resell_listings ADD COLUMN why_selling TEXT",
        "ALTER TABLE resell_listings ADD COLUMN whats_included TEXT",
        "ALTER TABLE resell_listings ADD COLUMN known_defects TEXT",
        "ALTER TABLE resell_listings ADD COLUMN tags TEXT",
        # Network security: link findings to a specific domain (for ban action)
        "ALTER TABLE security_findings ADD COLUMN domain TEXT",
        # Video: store the failure reason so the UI isn't a black box
        "ALTER TABLE videos ADD COLUMN error TEXT",
        # Video: live progress (0-100) + a human phase message, for a real progress bar
        "ALTER TABLE videos ADD COLUMN progress INTEGER DEFAULT 0",
        "ALTER TABLE videos ADD COLUMN progress_msg TEXT",
        # 3D models: preserve source folder structure as reference/review context
        "ALTER TABLE models3d ADD COLUMN rel_dir TEXT",     # path relative to backlog root
        "ALTER TABLE models3d ADD COLUMN category TEXT",    # top-level folder name
        # 3D generation: live progress message so the UI isn't a black box
        "ALTER TABLE models3d ADD COLUMN progress_msg TEXT",
        # Video→audio bridge: a muxed copy with music/voice + its own status
        "ALTER TABLE videos ADD COLUMN audio_path TEXT",
        "ALTER TABLE videos ADD COLUMN audio_status TEXT",
        "ALTER TABLE videos ADD COLUMN audio_error TEXT",
        # Audio clips: lyrics for ACE-Step (songs with vocals)
        "ALTER TABLE audio_clips ADD COLUMN lyrics TEXT",
        # Portal: link an affiliate product to a signup program (for tag auto-append)
        "ALTER TABLE portal_affiliate ADD COLUMN program_id INTEGER",
        # Portal programs: two-level model — network (join this) vs merchant (apply inside a network)
        "ALTER TABLE portal_programs ADD COLUMN ptype TEXT DEFAULT 'merchant'",  # network | merchant
        "ALTER TABLE portal_programs ADD COLUMN via TEXT",                       # hosting network(s) for merchants
        # The Company world economy: coin wallet + upgrade multiplier
        "ALTER TABLE world_agents ADD COLUMN coins INTEGER DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN coins_earned INTEGER DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN earn_mult REAL DEFAULT 1.0",
        "ALTER TABLE world_agents ADD COLUMN upgrades TEXT DEFAULT '[]'",
        # The Company simulation: Sims-style needs + mood + bills
        "ALTER TABLE world_agents ADD COLUMN debt INTEGER DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN energy REAL DEFAULT 80",
        "ALTER TABLE world_agents ADD COLUMN fun REAL DEFAULT 70",
        "ALTER TABLE world_agents ADD COLUMN social REAL DEFAULT 70",
        "ALTER TABLE world_agents ADD COLUMN fulfillment REAL DEFAULT 55",
        "ALTER TABLE world_agents ADD COLUMN hunger REAL DEFAULT 80",
        "ALTER TABLE world_agents ADD COLUMN mood_emoji TEXT DEFAULT '🙂'",
        "ALTER TABLE world_agents ADD COLUMN mood_label TEXT DEFAULT 'settling in'",
        "ALTER TABLE world_agents ADD COLUMN goal TEXT",
        # The Company state-machine v2: dwell hysteresis (stop the jitter) + idle sub-state + raid role
        "ALTER TABLE world_agents ADD COLUMN dwell_until REAL DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN substate TEXT",
        "ALTER TABLE world_agents ADD COLUMN role TEXT",
        # RimWorld-style mood: mental-break state (breakdown timer + kind)
        "ALTER TABLE world_agents ADD COLUMN break_until REAL DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN break_kind TEXT",
        # combat depth (#8): raid HP + downed/rescue state
        "ALTER TABLE world_agents ADD COLUMN raid_hp REAL DEFAULT 100",
        "ALTER TABLE world_agents ADD COLUMN downed INTEGER DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN downed_at REAL DEFAULT 0",
        # flux system: monotony streaks (penalise grinding one activity) + god's blessing buff
        "ALTER TABLE world_agents ADD COLUMN streak_state TEXT",
        # self-generated appearance: custom pixel sprite (agents earn a makeover)
        "ALTER TABLE world_agents ADD COLUMN sprite_path TEXT",
        "ALTER TABLE world_agents ADD COLUMN streak_since REAL DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN blessed_until REAL DEFAULT 0",
        # play-god pick-up/drop: post an agent to a spot/task (RCT-style)
        "ALTER TABLE world_agents ADD COLUMN posted_to TEXT",
        "ALTER TABLE world_agents ADD COLUMN posted_kind TEXT",
        "ALTER TABLE world_agents ADD COLUMN posted_until REAL DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN posted_col INTEGER DEFAULT 0",
        "ALTER TABLE world_agents ADD COLUMN posted_row INTEGER DEFAULT 0",
        # The Company world-builder's eyes: vision score + notes on each prop
        "ALTER TABLE world_props ADD COLUMN score INTEGER",
        "ALTER TABLE world_props ADD COLUMN verdict TEXT",
        # god's like/reject on a world creation (+1 like / -1 reject / null unrated) → taste
        "ALTER TABLE world_props ADD COLUMN user_verdict INTEGER",
        # NSFW ("Private Studio") mode: nsfw jobs are NORMAL rows flagged nsfw=1 —
        # same pipelines, but regular listings exclude them and only the gated
        # /api/nsfw/library returns them (see app/nsfw.py for the toggle model).
        "ALTER TABLE generations ADD COLUMN nsfw INTEGER DEFAULT 0",
        "ALTER TABLE generations ADD COLUMN nsfw_category TEXT",   # Private-Studio category name
        "ALTER TABLE generations ADD COLUMN nsfw_agent TEXT",      # world agent key when a Company agent made it
        "ALTER TABLE designs ADD COLUMN nsfw INTEGER DEFAULT 0",
        "ALTER TABLE designs ADD COLUMN nsfw_category TEXT",
        "ALTER TABLE videos ADD COLUMN nsfw INTEGER DEFAULT 0",
        "ALTER TABLE video_chains ADD COLUMN nsfw INTEGER DEFAULT 0",
        "ALTER TABLE audio_clips ADD COLUMN nsfw INTEGER DEFAULT 0",
        "ALTER TABLE models3d ADD COLUMN nsfw INTEGER DEFAULT 0",
    ]:
        try:
            c.execute(migration)
            conn.commit()
        except Exception:
            pass   # column already exists


def create_ledger_tables(conn):
    """💵 personal money ledger — paychecks IN + purchases OUT (routers/money/ledger.py).

    The sibling of create_bills_tables(). Bills own recurring obligations and their
    payment history (bill_payments); this owns income and NON-bill spending.
    `purchases` deliberately has NO bill_id: bill payments already live in
    bill_payments, so a bill entered here too would double-count in every total.
    Outgoings = purchases + bill_payments, two disjoint sets.

    Called from routers/money/ledger.py at import (same one-time-ensure pattern as
    create_bills_tables), so db.py needs no wiring.

    NOT the game world's economy (world_ledger / world_ops_ledger) — unrelated."""
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS paychecks (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        source            TEXT NOT NULL,        -- employer or client name
        amount_cents      INTEGER NOT NULL,     -- net (take-home); may be derived from hours × rate
        gross_cents       INTEGER,              -- before withholding, optional
        received_at       TEXT,                 -- YYYY-MM-DD the money landed
        hours             REAL,                 -- optional, for hourly/contract work
        hourly_rate_cents INTEGER,              -- per-entry rate — never a hardcoded constant
        cycle             TEXT DEFAULT 'irregular', -- weekly|biweekly|semimonthly|monthly|irregular
        notes             TEXT DEFAULT '',
        extra             TEXT DEFAULT '{}',    -- JSON object of arbitrary user-defined fields
        created_at        TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS purchases (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        purchased_at  TEXT,                     -- YYYY-MM-DD
        merchant      TEXT NOT NULL,
        amount_cents  INTEGER NOT NULL,
        category      TEXT DEFAULT '',          -- free text; shares the bills category vocabulary
        method        TEXT DEFAULT '',          -- card / cash / transfer / …
        notes         TEXT DEFAULT '',
        extra         TEXT DEFAULT '{}',        -- JSON object of arbitrary user-defined fields
        created_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_paychecks_received ON paychecks(received_at);
    CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(purchased_at);
    CREATE INDEX IF NOT EXISTS idx_purchases_category ON purchases(category, purchased_at);
    """)
    conn.commit()


def create_game_listing_tables(conn):
    """🎮 Games → shop listing drafts (routers/games_publish.py).

    ONE row per shop listing the owner is hand-building for a game project. This is
    deliberately a private, opt-in table: a project only appears here because the
    owner opened the publish editor on it. Nothing scans projects into this table,
    and nothing in the app lists these rows publicly.

    `wp_id` is set only after an explicit push, and the pushed product is always a
    WooCommerce DRAFT — re-pushing updates that same id rather than duplicating.
    Images live as files under DATA_DIR/game_listings/<id>/; the `images` JSON array
    records {file, kind, label, wp_url?} for each one.

    Called from routers/games_publish.py at import (same one-time-ensure pattern as
    create_bills_tables / create_ledger_tables), so db.py needs no wiring."""
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS game_listings (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        project_path  TEXT NOT NULL,          -- where the project lives on the node (NEVER pushed)
        project_name  TEXT DEFAULT '',
        engine        TEXT DEFAULT '',        -- godot | unity | unreal
        title         TEXT NOT NULL,
        slug          TEXT DEFAULT '',
        price_cents   INTEGER DEFAULT 0,      -- money is cents everywhere in this app
        short_desc    TEXT DEFAULT '',
        long_desc     TEXT DEFAULT '',
        category      TEXT DEFAULT 'Games',
        tags          TEXT DEFAULT '',        -- comma separated
        external_url  TEXT DEFAULT '',        -- optional link/download target
        button_text   TEXT DEFAULT 'Get the game',
        images        TEXT DEFAULT '[]',      -- JSON array of image records
        status        TEXT DEFAULT 'draft',   -- draft (local only) | pushed
        wp_id         INTEGER,                -- WooCommerce product id, once pushed
        wp_link       TEXT DEFAULT '',
        wp_admin_url  TEXT DEFAULT '',
        wp_status     TEXT DEFAULT '',        -- what Woo reported back; always 'draft' from here
        pushed_at     TEXT,
        created_at    TEXT DEFAULT (datetime('now')),
        updated_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_game_listings_project ON game_listings(project_path);
    """)
    conn.commit()


def create_budget_tables(conn):
    """🧮 Budget + grocery planner — item-level purchases, envelopes, AI plan drafts.

    The three tables the budget engine adds on top of the existing money schema
    (bills / bill_payments / paychecks / purchases). Nothing here duplicates an
    amount that already lives elsewhere:

      purchase_items    the line items OF an existing `purchases` row. The parent
                        purchase keeps owning the authoritative amount_cents (a
                        receipt total includes tax/fees the lines do not), so
                        totals and budgets are ALWAYS summed from `purchases`,
                        never from these lines. Lines exist to answer "what did I
                        buy, how much of it, at what unit price, how often" —
                        they are detail, not a second copy of the money.
                        `normalized_name` is the match key across trips
                        ("Milk 1 gal" and "milk gallon" both normalize to "milk");
                        `name` keeps the raw text exactly as typed, for display.

      budget_envelopes  one row per category the owner budgets (food, gas,
                        savings, other, …). `kind` is 'fixed' (amount_cents) or
                        'percent' (percent of the period's income basis). The
                        allocation is COMPUTED per period, never stored — a
                        stored allocation would go stale the moment income moves.

      budget_plans      AI grocery-list drafts. ADVISORY ONLY: a plan is never
                        applied to a budget and never becomes a purchase on its
                        own. It sits at status 'draft' until the owner accepts or
                        rejects it, and turning an accepted plan into a real
                        purchase is a separate, explicit owner action.
                        `items` / `observations` / `llm_notes` are JSON.

    The pay cycle and the feature toggles live in `settings`
    (budget_pay_cycle / budget_period_anchor / budget_planner_enabled /
    budget_calendar_predictions), not here — they are single scalars.

    Called from routers/money/budget.py at import (same one-time-ensure pattern as
    create_bills_tables / create_ledger_tables), so db.py needs no wiring."""
    conn.cursor().executescript("""
    CREATE TABLE IF NOT EXISTS purchase_items (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id      INTEGER NOT NULL,     -- FK -> purchases.id (lines die with the purchase)
        name             TEXT NOT NULL,        -- raw, as typed — shown to the owner verbatim
        normalized_name  TEXT NOT NULL,        -- match key across trips (see normalize_item_name)
        qty              REAL DEFAULT 1,       -- how many units this line covers
        unit             TEXT DEFAULT '',      -- gal / lb / ct / pack / … free text
        unit_price_cents INTEGER,              -- price of ONE unit; NULL when not known
        line_total_cents INTEGER NOT NULL,     -- what this line cost (qty × unit price, or as entered)
        category         TEXT DEFAULT '',      -- falls back to the parent purchase's category
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS budget_envelopes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        category     TEXT NOT NULL UNIQUE,     -- matches purchases.category (case-insensitive)
        kind         TEXT DEFAULT 'fixed',     -- fixed | percent
        amount_cents INTEGER DEFAULT 0,        -- used when kind='fixed'
        percent      REAL DEFAULT 0,           -- used when kind='percent' (of income basis)
        active       INTEGER DEFAULT 1,
        sort         INTEGER DEFAULT 0,
        notes        TEXT DEFAULT '',
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS budget_plans (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        period_start   TEXT,                   -- YYYY-MM-DD the plan was drawn for
        period_end     TEXT,
        envelope_cents INTEGER,                -- food envelope REMAINING at generation time
        est_total_cents INTEGER DEFAULT 0,     -- sum of the validated lines, priced from OUR history
        status         TEXT DEFAULT 'generating', -- generating | draft | accepted | rejected | failed
        items          TEXT DEFAULT '[]',      -- JSON: validated grocery lines
        rejected_items TEXT DEFAULT '[]',      -- JSON: lines the validator dropped, with the reason
        observations   TEXT DEFAULT '[]',      -- JSON: OUR computed facts (not the model's)
        llm_notes      TEXT DEFAULT '[]',      -- JSON: the model's advisory notes, labelled as such
        error          TEXT DEFAULT '',
        task_id        INTEGER,                -- orchestrator task that produced it
        purchase_id    INTEGER,                -- set only if the owner turned it into a real purchase
        created_at     TEXT DEFAULT (datetime('now')),
        updated_at     TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_purchase_items_purchase ON purchase_items(purchase_id);
    CREATE INDEX IF NOT EXISTS idx_purchase_items_norm ON purchase_items(normalized_name);
    CREATE INDEX IF NOT EXISTS idx_budget_plans_status ON budget_plans(status, id);
    """)
    conn.commit()
