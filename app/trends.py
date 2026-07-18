"""
Trend scanner — pulls trending topics from:
  • Google Trends  (pytrends, no auth)
  • Reddit RSS     (feedparser, no auth — each subreddit has a public .rss feed)
  • Custom RSS     (feedparser, any RSS/Atom feed URL)

Then batches them through the local LLM to filter + generate proposals.
"""
import json, time, logging, re
from typing import Optional
import feedparser

log = logging.getLogger("trends")

# ── Google Trends ─────────────────────────────────────────────────────────────
def fetch_google_trends(region: str = "US", max_results: int = 20) -> list[str]:
    """Fetch trending searches via Google Trends RSS (no pytrends, no auth)."""
    try:
        import requests
        url = f"https://trends.google.com/trending/rss?geo={region.upper()}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        feed = feedparser.parse(r.text)
        return [e.get("title", "").strip() for e in feed.entries[:max_results] if e.get("title")]
    except Exception as e:
        log.warning("Google Trends fetch failed: %s", e)
        return []

# ── Reddit RSS ────────────────────────────────────────────────────────────────
DEFAULT_SUBS = [
    "gaming", "movies", "television", "Music", "memes",
    "funny", "sports", "anime", "technology", "Art",
]

def fetch_reddit_rss(subreddits: list[str], limit_per_sub: int = 8) -> list[str]:
    titles = []
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/rising.rss"
            feed = feedparser.parse(url)
            for e in feed.entries[:limit_per_sub]:
                t = e.get("title", "").strip()
                if t and len(t) > 5:
                    titles.append(f"{t} [{sub}]")
        except Exception as e:
            log.warning("Reddit RSS %s failed: %s", sub, e)
        time.sleep(0.3)   # be polite
    return titles

# ── Custom RSS ────────────────────────────────────────────────────────────────
DEFAULT_RSS_FEEDS = [
    "https://feeds.feedburner.com/TechCrunch",
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
]

def fetch_rss_feeds(feed_urls: list[str], limit_per_feed: int = 6) -> list[str]:
    titles = []
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:limit_per_feed]:
                t = e.get("title", "").strip()
                if t and len(t) > 5:
                    titles.append(t)
        except Exception as e:
            log.warning("RSS feed %s failed: %s", url, e)
    return titles

# ── LLM filter + proposal generator ──────────────────────────────────────────
TREND_SYSTEM = """You are a creative director for a print-on-demand humor merch store. Your specialty is finding absurdist, unexpected comedic angles on trending topics.

Your comedy framework — think of these as formulas:
  "1+1=3": Smash two unrelated trending things together into something funnier than either alone.
           Example: Tax season + Minecraft = "Your Inventory Is Full: $0 After Taxes"
  "Pointing out the obvious": The joke IS the absurdity. State what everyone is thinking.
           Example: Weather heat wave + meme format = "It Is In Fact Very Hot Outside. A Science Report."
  "The bridge": Find the one weird thing that connects two unrelated trends and put it on a shirt.

Topics that work great: weed humor, Texas jokes, weather complaints, taxes, small home/van life, 
gaming references, 3D printing nerd culture, tech fails, YouTuber culture, brand parodies (be careful), 
world news irony, local news absurdity.

SKIP: elected politicians by name, genuine tragedies, actual racism or hate, legally risky brand attacks, NSFW.
INCLUDE: absurdist mashups, ironic observations, niche community in-jokes, pointing out obvious absurdity.

For each proposal:
- Lead with the comedic concept or punchline idea in the description
- The title should work as the shirt text itself or be a punchy concept
- Think: would someone laugh, then immediately want to buy this for a friend?

Return ONLY valid JSON (no markdown, no code fences) — an array of 3–8 proposal objects.
Each object must have exactly these keys:
  trend:       the original trend text
  title:       short catchy product title or shirt slogan, max 8 words
  description: the comedic angle or punchline concept, 1-2 sentences
  tags:        comma-separated tags, 6-10 tags
  source:      one of "google_trends" | "reddit" | "rss"

Only include proposals with genuine comedic or merch potential. Quality over quantity."""


def generate_proposals_from_trends(
    trends: list[tuple[str, str]],   # [(trend_text, source_label), ...]
    call_lmstudio_fn,
    max_tokens: int = 3000,
) -> list[dict]:
    """
    trends: list of (text, source) tuples already deduplicated.
    call_lmstudio_fn: the _call_lmstudio function from main.py.
    Returns list of proposal dicts ready to insert into DB.
    """
    if not trends:
        return []

    # Format the trend list for the prompt
    trend_list = "\n".join(f"- {text} (source: {src})" for text, src in trends[:40])
    user_msg   = f"Here are today's trending topics:\n\n{trend_list}\n\nGenerate merch proposals for the best ones."

    try:
        raw = call_lmstudio_fn(TREND_SYSTEM, user_msg, max_tokens=max_tokens, json_mode=False)
        # Strip markdown fences if model added them
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(raw)
        if isinstance(data, dict):
            # Some models wrap the array: {"proposals": [...]}
            for key in ("proposals", "results", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            return []
        # Sanitise each proposal
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()[:120]
            desc  = str(item.get("description", "")).strip()[:400]
            tags  = str(item.get("tags", "")).strip()[:200]
            src   = str(item.get("source", "trend")).strip()
            trend = str(item.get("trend", "")).strip()[:200]
            if not title:
                continue
            out.append({
                "title":        title,
                "description":  desc,
                "tags":         tags,
                "source":       _source_label(src),
                "source_label": _source_display(src),
                "trend_text":   trend,
            })
        return out
    except Exception as e:
        log.error("LLM proposal generation failed: %s", e)
        return []


def _source_label(raw: str) -> str:
    raw = raw.lower()
    if "google" in raw or "trend" in raw:
        return "trend"
    if "reddit" in raw:
        return "reddit"
    return "news"

def _source_display(raw: str) -> str:
    raw = raw.lower()
    if "google" in raw or "trend" in raw:
        return "Google Trends"
    if "reddit" in raw:
        return "Reddit"
    return "News RSS"
