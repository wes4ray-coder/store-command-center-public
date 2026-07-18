"""THE COMPANY — Mayor Vex & Boss Kane spend the company fund on REAL upgrades.

The two leaders never labour; their job is to reinvest what the town earns.
When the company fund is healthy, the next leader in rotation files a REAL
dev-swarm job (swarm_jobs, status 'proposed') describing a store/town upgrade
— the same pipeline you drive from the GitHub / Dev-Swarm tab, so nothing
runs until YOU approve it there. The upgrade's coin cost is only charged to
the company fund at the moment you approve the job (charge_on_approval,
hooked into the approve endpoint) — reject it and the fund is untouched.

Toggle: `world_leader_upgrades` (Company Settings → Governance). Cadence:
`world_leader_upgrade_hours` between proposals. Never drains the fund below
FUND_CUSHION.
"""
import json
import time

from world_defs import mget, mset, log_town

FUND_CUSHION = 200        # coins that always stay in the fund

# (leader, title, spec, cost🪙) — Mayor invests in the TOWN, Boss in the STORE.
UPGRADE_IDEAS = [
    ("Mayor Vex", "Town upgrade: richer park & plaza life",
     "Add more life to the town's public spaces in the world tab: benches that agents "
     "actually sit on, a picnic spot, and 1-2 new decorative structures agents visit "
     "during leisure. Keep it procedural (no new assets required).", 220),
    ("Boss Kane", "Store upgrade: product-page polish pass",
     "Improve the generated product listings: tighten title/tag templates, ensure every "
     "published item has consistent branding fields, and add one automated quality check "
     "before a listing is filed for review.", 260),
    ("Mayor Vex", "Town upgrade: night-life lighting pass",
     "Improve the night look of the pixel town: warmer window glow, a few street lamps "
     "along main paths, fireflies near water. Procedural only.", 240),
    ("Boss Kane", "Store upgrade: smarter trend scan",
     "Improve the trend-scan automation: de-duplicate near-identical proposals and rank "
     "them by the god-taste model before they reach the review queue.", 300),
    ("Mayor Vex", "Town upgrade: town noticeboard history",
     "Give the town feed a browsable history view (paged, filter by kind) so past events "
     "aren't lost after 24 entries.", 200),
    ("Boss Kane", "Store upgrade: publish-queue insights",
     "Add a small dashboard card summarizing the publish pipeline: waiting for review, "
     "approved-not-published, published this week — with links into each queue.", 240),
]


def _b(c, key, dflt="0"):
    import world_settings as WSET
    return WSET.b(key, c)


def maybe_upgrade(conn):
    """Ticker hook: at most one leader proposal per cadence window, only while
    the fund can afford it. Files a normal 'proposed' swarm job — user-gated."""
    c = conn.cursor()
    if not _b(c, "world_leader_upgrades"):
        return False
    import world_settings as WSET
    hours = max(1, WSET.i("world_leader_upgrade_hours", c) or 12)
    now = time.time()
    if now - float(mget(c, "leader_upgrade_t", 0) or 0) < hours * 3600:
        return False
    fund = int(float(mget(c, "company_fund", 0) or 0))
    n = int(float(mget(c, "leader_upgrade_n", 0) or 0))
    # rotate through ideas; skip ones already filed (open OR done) and unaffordable ones
    have = {r[0] for r in c.execute("SELECT title FROM swarm_jobs").fetchall()}
    pick = None
    for i in range(len(UPGRADE_IDEAS)):
        leader, title, spec, cost = UPGRADE_IDEAS[(n + i) % len(UPGRADE_IDEAS)]
        if title not in have and fund - cost >= FUND_CUSHION:
            pick = (leader, title, spec, cost)
            break
    if not pick:
        mset(c, "leader_upgrade_t", now)      # nothing affordable/new → wait a full window
        conn.commit()
        return False
    leader, title, spec, cost = pick
    spec = (f"{spec}\n\n[Filed by {leader} from the company fund — {cost}\U0001fa99 "
            f"is charged only when the owner APPROVES this job.]")
    jid = c.execute(
        "INSERT INTO swarm_jobs (title,spec,repo,branch,autonomy,status) "
        "VALUES (?,?,NULL,'dev',NULL,'proposed')", (title, spec)).lastrowid
    mset(c, f"leader_cost_{jid}", cost)
    mset(c, "leader_upgrade_t", now)
    mset(c, "leader_upgrade_n", n + 1)
    c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (NULL,'town',?)",
              (f"\U0001f3db️ {leader} filed an upgrade with the dev crew: “{title}” "
               f"({cost}\U0001fa99 from the company fund, pending your approval).",))
    log_town(f"{leader} proposed: {title} ({cost} coins, awaiting approval)")
    try:
        import world_ops as wo
        wo.note(f"\U0001f3db️ {leader} wants to invest {cost}\U0001fa99: {title} — "
                "approve or reject it in the Dev Swarm tab.", kind="need", conn=conn)
    except Exception:
        pass
    conn.commit()
    return True


def charge_on_approval(conn, jid):
    """Called when the user APPROVES a swarm job: if a leader filed it, deduct
    its cost from the company fund (once). Silent no-op for normal jobs."""
    c = conn.cursor()
    raw = mget(c, f"leader_cost_{jid}", None)
    if raw is None or raw == "":
        return False
    cost = int(float(raw))
    mset(c, f"leader_cost_{jid}", "")          # charge exactly once
    fund = int(float(mget(c, "company_fund", 0) or 0))
    mset(c, "company_fund", max(0, fund - cost))
    c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (NULL,'town',?)",
              (f"\U0001f4b0 The company fund paid {cost}\U0001fa99 for an approved upgrade "
               f"(job #{jid}). Fund: {max(0, fund - cost)}\U0001fa99.",))
    conn.commit()
    return True
