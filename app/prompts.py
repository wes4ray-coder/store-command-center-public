"""Central registry of every LLM prompt/"bootstrap" the app uses.

One place to see and edit every system prompt. Each entry has a stable `key`, a
human `label`, a `category` (groups the Settings → Prompts tab), and a DEFAULT.
To avoid duplicating text, defaults that already live as module-level constants are
referenced lazily via `ref=(module, attr)`; a few prompts defined inline inside a
function carry their text here via `inline=`.

The LIVE value returned by `get_prompt(key)` is the settings override
(row `prompt__<key>` in the `settings` table, or a custom `settings_key`) when set,
otherwise the default. Call sites use `get_prompt(...)` instead of the raw constant —
that indirection is what makes every prompt editable from the UI, with zero behaviour
change until someone actually overrides one.

Import-safety: this module imports only `db` (which imports `config`), so there is no
cycle even though `deps` imports *this* module. `ref` targets are imported lazily at
call time, by which point every module is already loaded.
"""
from dataclasses import dataclass
from typing import Optional
import importlib

from db import get_conn


@dataclass
class PromptDef:
    key: str
    label: str
    category: str
    ref: Optional[tuple] = None       # (module_name, attr) — lazy default source
    inline: Optional[str] = None      # literal default (prompt defined inside a function)
    settings_key: Optional[str] = None
    help: str = ""
    templated: bool = False           # contains {placeholders}: keep them when editing

    @property
    def skey(self) -> str:
        return self.settings_key or f"prompt__{self.key}"

    def default(self) -> str:
        if self.inline is not None:
            return self.inline
        mod, attr = self.ref
        return getattr(importlib.import_module(mod), attr)


# ── The registry ──────────────────────────────────────────────────────────────
PROMPTS: list[PromptDef] = [
    # ── Studio (image / audio / video / 3D generation) ──
    PromptDef("image_enhance", "Image prompt enhancement", "Studio",
              ref=("deps", "ENHANCE_SYSTEM"), settings_key="enhance_system_prompt",
              help="Turns a rough idea into a rich image-generation prompt. Also used by "
                   "Quick Generate, the Proposal Approve/Enhance buttons."),
    PromptDef("image_research", "Image deep-research → prompt", "Studio",
              ref=("deps", "RESEARCH_SYSTEM"),
              help="Research a concept and return JSON {research_summary, enhanced_prompt, title, tags}."),
    PromptDef("image_describe", "Image describe (vision → merch)", "Studio",
              inline="""You are a creative merch designer. Describe the provided image in detail to create a print-on-demand merchandise prompt.
Focus on: visual style, subject matter, color palette, mood, any text/logos visible, what makes it funny or interesting.
Then suggest how it could be adapted into a merch design.
Return ONLY valid JSON with keys:
  description: detailed visual description (2-3 sentences)
  enhanced_prompt: vivid Stable Diffusion image generation prompt based on this image, 80-120 words
  title: suggested product title (max 8 words)
  tags: comma-separated tags (6-10)""",
              help="Vision model: describe an uploaded image and turn it into a merch prompt (JSON)."),
    PromptDef("audio_music", "Music prompt enhancement", "Studio",
              inline="You are a prompt engineer for AI music generators. Turn the user's idea into "
                     "ONE vivid description (20-40 words) covering genre/style, mood, key instruments, "
                     "tempo/energy, and production feel — no song title, no lyrics, no lists. "
                     "Output your result on ONE line starting exactly with 'FINAL:' and nothing after it.",
              help="Enhances a raw music idea. Output must end with a single line starting 'FINAL:'."),
    PromptDef("audio_voice", "Voice / narration prompt enhancement", "Studio",
              inline="Rewrite the user's text into a clear, natural line of narration to be spoken "
                     "aloud — friendly and concise, keeping their meaning. "
                     "Output your result on ONE line starting exactly with 'FINAL:' and nothing after it.",
              help="Enhances a narration line for TTS. Output must end with a single line starting 'FINAL:'."),
    PromptDef("video_chain", "Video multi-scene concept", "Studio",
              ref=("deps", "CHAIN_PROMPT_SYSTEM"),
              help="Turns a concept + scene count into a JSON array of sequential text-to-video prompts."),
    PromptDef("threed_enhance", "3D prompt enhancement", "Studio",
              inline="You improve short ideas into prompts for image-to-3D generation of a SINGLE "
                     "printable object. Return ONE vivid line (30-60 words): the object, its form, "
                     "style, and surface — centered, full object visible, clean silhouette, no scene, "
                     "no background, no text. Output ONLY the prompt line, nothing else.",
              help="Enhances an idea into a single-object image→3D prompt."),
    PromptDef("threed_listing", "3D listing (Cults3D) copy", "Studio",
              ref=("routers.models3d", "_PROPOSE_SYSTEM"),
              help="Generates Cults3D title/description/tags/price from model facts (JSON)."),

    # ── Storefront (listing copy + pricing) ──
    PromptDef("listing_copy", "Etsy / POD listing copy", "Storefront",
              ref=("deps", "LISTING_SYSTEM"),
              help="Produces TITLE / DESCRIPTION / TAGS for a design. Keep that exact output format."),
    PromptDef("pricing", "Etsy pricing", "Storefront",
              inline="You are a pricing expert for print-on-demand products sold on Etsy. "
                     "Respond ONLY with valid JSON: {\"price\": <number>, \"reasoning\": \"<1-2 sentence reason>\"}",
              help="Suggests an optimal retail price as JSON {price, reasoning}."),

    # ── Resell ──
    PromptDef("resell_analyze", "Resell photo analysis", "Resell",
              ref=("deps", "RESELL_ANALYZE_PROMPT"), templated=True,
              help="Analyzes an item photo → listing JSON. Contains {seller_context} and literal {{ }} JSON — keep them."),
    PromptDef("resell_price", "Resell price research", "Resell",
              ref=("deps", "RESEARCH_PRICE_PROMPT"), templated=True,
              help="Prices a used item. Contains {title}/{condition}/{category} and {{ }} JSON — keep them."),
    PromptDef("resell_posting", "Marketplace posting agent", "Resell",
              ref=("deps", "POSTING_AGENT_PROMPT"), templated=True,
              help="Drives browser posting. Contains many {placeholders} — keep every one."),
    PromptDef("resell_haggle", "Resell haggle / negotiate", "Resell",
              ref=("routers.resell_browser", "_HAGGLE_SYSTEM"),
              help="Generates a negotiation reply to a buyer offer."),
    PromptDef("resell_inbox", "Resell inbox parse", "Resell",
              ref=("routers.resell_browser", "_INBOX_PARSE_SYSTEM"),
              help="Parses marketplace inbox messages into structured offers."),

    # ── Social ──
    PromptDef("social_caption", "Social caption", "Social",
              inline="You are the social media manager for Acme, a playful indie shop selling geeky "
                     "graphic tees, 3D-printable models, free software, and curated gadget deals. Write ONE "
                     "short, scroll-stopping caption for {plats} in a {tone} tone, then 8-12 relevant "
                     "hashtags. Keep the caption under 300 characters, add 1-3 tasteful emoji. "
                     'Return STRICT JSON: {{"caption": "...", "hashtags": "#a #b #c"}} and nothing else.',
              templated=True,
              help="Writes a social caption. Contains {plats} and {tone} placeholders — keep them."),

    # ── Library ──
    PromptDef("library_rip", "Library: web page → markdown", "Library",
              ref=("routers.library", "_RIP_SYSTEM"),
              help="Converts a fetched web page into clean markdown."),
    PromptDef("library_gap", "Library: gap analysis", "Library",
              ref=("routers.library", "_GAP_SYSTEM"),
              help="Finds gaps/missing coverage in a document summary."),
    PromptDef("library_enrich", "Library: enrich", "Library",
              ref=("routers.library", "_ENRICH_SYSTEM"),
              help="Enriches a stored document."),
    PromptDef("library_summary", "Library: summarize", "Library",
              ref=("routers.library", "_SUMMARY_SYSTEM"),
              help="Summarizes a stored document."),

    # ── Security ──
    PromptDef("security_analyze", "Network security analysis", "Security",
              ref=("routers.security", "_ANALYZE_SYSTEM"),
              help="Analyzes network/security scan findings."),

    # ── Assistant ──
    PromptDef("assistant", "Dashboard AI assistant", "Assistant",
              ref=("routers.agent", "_ASSISTANT_SYSTEM"),
              help="The built-in dashboard chat assistant's system prompt."),

    # ── Dev Swarm ──
    PromptDef("swarm_planner",   "Dev Swarm: Planner",   "Dev Swarm", ref=("swarm", "PLANNER_SYS")),
    PromptDef("swarm_scout",     "Dev Swarm: Scout",     "Dev Swarm", ref=("swarm", "SCOUT_SYS")),
    PromptDef("swarm_architect", "Dev Swarm: Architect", "Dev Swarm", ref=("swarm", "ARCHITECT_SYS")),
    PromptDef("swarm_coder",     "Dev Swarm: Coder",     "Dev Swarm", ref=("swarm", "CODER_SYS")),
    PromptDef("swarm_reviewer",  "Dev Swarm: Reviewer",  "Dev Swarm", ref=("swarm", "REVIEWER_SYS")),
    PromptDef("swarm_auditor",   "Dev Swarm: Auditor",   "Dev Swarm", ref=("swarm", "AUDITOR_SYS")),
    PromptDef("swarm_system",    "Dev Swarm: System",    "Dev Swarm", ref=("swarm", "SYSTEM_SYS")),
    # ── Crypto (JellyCoin) ──
    PromptDef("jelly_mission", "JellyCoin push/sell mission", "Crypto",
              inline="You are a Company marketing agent for Acme. Draft ONE short pitch to "
                     "promote JellyCoin (JLY) — Acme's own GPU-mined token (old graphics cards "
                     "earn it, the crew's skilling boosts it, our art mints as NFTs on it). "
                     "First line = a punchy title. Then 3-6 sentences: the hook, the concrete "
                     "action, and why it's fun. Be honest — JLY is our community token, not an "
                     "investment; NEVER promise profit, price growth, or returns. The pitch is a "
                     "PROPOSAL for the owner to approve; do not claim anything is already live.",
              help="Drafts JLY promo/perk/sell missions (Crypto → JellyCoin). Every draft waits "
                   "for your approval — agents never post or sell on their own."),
    # ── Money & Mail ──
    PromptDef("money_gap_review", "Money: demand-gap review", "Assistant",
              ref=("routers.money", "MONEY_GAP_REVIEW_PROMPT"),
              help="Reviews shop search queries vs the catalog and proposes real-dollar "
                   "missions (product gaps, income ideas). Runs on the Money tab's cadence; "
                   "every mission still waits for your approval."),
    PromptDef("money_lead_hunt", "Money: carpentry lead screen", "Assistant",
              ref=("routers.money", "LEAD_HUNT_PROMPT"),
              help="Screens web-search results for REAL local carpentry work leads and "
                   "drafts carpentry_lead missions (approval-gated)."),
    PromptDef("mail_quote", "Mail: carpentry quote draft", "Assistant",
              ref=("routers.mail", "_QUOTE_SYS"),
              help="Drafts the labor-quote email reply (fixed terms baked in). Draft only — "
                   "nothing sends until you press Send reply."),
    # ── The Company (world) ──
    PromptDef("world_music_lyrics", "Company music: agent lyrics", "Studio",
              inline="You are {agent}, a musician in a small creative company, writing an original "
                     "song for the company store. Theme: {theme}. Write SHORT original lyrics — "
                     "2 verses and a chorus, under 120 words total, no explicit content, no real "
                     "artist/brand names. Plain text only: verse lines separated by newlines, the "
                     "chorus prefixed with 'Chorus:'. No commentary, titles, or markdown — just "
                     "the lyrics.",
              templated=True,
              help="When 'agents write their own lyrics' is on (Company Settings), this writes "
                   "the lyrics an agent sings on an ACE-Step vocal track. {agent} = the composer's "
                   "name, {theme} = the music idea."),
]

_BY_KEY = {p.key: p for p in PROMPTS}

# Category display order for the UI.
CATEGORIES = ["Studio", "Storefront", "Resell", "Social", "Library", "Security", "Assistant", "Dev Swarm", "Crypto"]


def _override(skey: str) -> Optional[str]:
    try:
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (skey,)).fetchone()
        conn.close()
        v = row["value"] if row else None
        return v if v and v.strip() else None
    except Exception:
        return None


def get_prompt(key: str) -> str:
    """The single read path for a prompt: settings override if set, else the default."""
    p = _BY_KEY.get(key)
    if not p:
        raise KeyError(f"unknown prompt key: {key}")
    ov = _override(p.skey)
    return ov if ov is not None else p.default()


def list_prompts() -> list[dict]:
    out = []
    for p in PROMPTS:
        ov = _override(p.skey)
        out.append({
            "key": p.key, "label": p.label, "category": p.category,
            "help": p.help, "templated": p.templated,
            "default": p.default(),
            "value": ov if ov is not None else p.default(),
            "overridden": ov is not None,
        })
    return out


def set_prompt(key: str, value: str) -> None:
    p = _BY_KEY.get(key)
    if not p:
        raise KeyError(f"unknown prompt key: {key}")
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (p.skey, value))
    conn.commit()
    conn.close()


def reset_prompt(key: str) -> None:
    p = _BY_KEY.get(key)
    if not p:
        raise KeyError(f"unknown prompt key: {key}")
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key=?", (p.skey,))
    conn.commit()
    conn.close()
