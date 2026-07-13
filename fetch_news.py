#!/usr/bin/env python3
"""
fetch_news.py

Fetches the latest headlines from a set of public RSS feeds -- in English
plus five Indian regional languages (Hindi, Gujarati, Tamil, Telugu,
Kannada) -- and writes them to news.json, grouped by language then
category. Uses only the Python standard library, so it needs no extra
dependencies to run (works out of the box in GitHub Actions).

Run manually:      python3 fetch_news.py
Run automatically: see .github/workflows/update-news.yml (runs on a schedule)

To change the news sources, edit the FEEDS_BY_LANG dictionary below. Any
standard RSS 2.0 or Atom feed URL will work. To add another language,
add an entry to LANGUAGES and a matching entry to FEEDS_BY_LANG.
"""
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

try:
    from zoneinfo import ZoneInfo
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    PACIFIC_TZ = None  # fall back to UTC date if tzdata isn't available

USER_AGENT = "Mozilla/5.0 (compatible; SimpleNewsBot/1.0)"
TIMEOUT = 15
MAX_ITEMS_PER_CATEGORY = 12
MAX_TOP_STORIES = 14

# --- AI rewrite settings -----------------------------------------------
# If GEMINI_API_KEY is set (as a GitHub Actions secret), each article's
# summary is rewritten in original wording via Google's free Gemini API
# instead of just truncating the publisher's RSS snippet. Gemini's free
# tier (aistudio.google.com) needs no credit card. Results are cached in
# summary_cache.json so a given article is only ever rewritten once,
# keeping well within the free rate limits even though the workflow runs
# frequently.
#
# NOTE: this used to call Groq, but Groq's Cloudflare-based anti-abuse
# rules block requests from datacenter/CI IPs (including GitHub Actions
# runners) with a blanket 403 -- confirmed by Groq's own team on their
# community forum. Gemini does not have this restriction.
#
# NOTE 2: Google's documented free-tier limits for this model (15 RPM /
# 1000 RPD) turned out not to match what this specific account was
# actually granted -- checking aistudio.google.com/rate-limit showed this
# project's real cap is only 10 requests/minute and 20 requests/day. Since
# the workflow runs every 30 minutes (48x/day), a per-run cap alone isn't
# enough to stay under a *daily* limit -- so usage is tracked persistently
# across runs in ai_usage.json (committed alongside summary_cache.json),
# resetting at midnight Pacific time to match Google's reset schedule.
# If your account has higher limits, raise DAILY_AI_CALL_LIMIT accordingly
# (check your own numbers at the URL above).
#
# NOTE 3: this budget is now SHARED across all six languages (English +
# 5 regional). With the default of 15/day, AI-rewritten summaries roll
# out slowly across all languages combined, not 15 per language. Raise
# DAILY_AI_CALL_LIMIT if your account's real quota supports it.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
AI_MODEL = "gemini-2.5-flash-lite"
CACHE_FILE = "summary_cache.json"
USAGE_FILE = "ai_usage.json"
DAILY_AI_CALL_LIMIT = 15  # stays under this account's observed 20 requests/day cap
AI_CALL_DELAY_SECONDS = 7  # stays under this account's observed 10 requests/minute cap

# code -> display label (native script) + English name used in the AI prompt
LANGUAGES = {
    "en": {"label": "English", "ai_name": None},
    "hi": {"label": "हिन्दी", "ai_name": "Hindi"},
    "gu": {"label": "ગુજરાતી", "ai_name": "Gujarati"},
    "ta": {"label": "தமிழ்", "ai_name": "Tamil"},
    "te": {"label": "తెలుగు", "ai_name": "Telugu"},
    "kn": {"label": "ಕನ್ನಡ", "ai_name": "Kannada"},
}

# language code -> category -> list of (source name, RSS feed URL)
FEEDS_BY_LANG = {
    "en": {
        "India": [
            ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
            ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
            ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
            ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
        ],
        "World": [
            ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
            ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ],
        "Business": [
            ("Economic Times", "https://economictimes.indiatimes.com/rssfeedsdefault.cms"),
            ("BBC Business", "http://feeds.bbci.co.uk/news/business/rss.xml"),
            ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
        ],
        "Sports": [
            ("NDTV Sports", "https://feeds.feedburner.com/ndtvsports-latest"),
            ("ESPN Cricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
        ],
        "Technology": [
            ("Gadgets 360", "https://feeds.feedburner.com/gadgets360-latest"),
            ("BBC Technology", "http://feeds.bbci.co.uk/news/technology/rss.xml"),
        ],
        "Entertainment": [
            ("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms"),
            ("BBC Entertainment", "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
        ],
    },
    "hi": {
        "Top Stories": [
            ("BBC Hindi", "https://feeds.bbci.co.uk/hindi/rss.xml"),
            ("Oneindia Hindi", "https://hindi.oneindia.com/rss/feeds/hindi-news-fb.xml"),
        ],
        "Entertainment": [
            ("Oneindia Hindi", "https://hindi.oneindia.com/rss/feeds/hindi-entertainment-fb.xml"),
        ],
    },
    "gu": {
        "Top Stories": [
            ("BBC Gujarati", "https://feeds.bbci.co.uk/gujarati/rss.xml"),
            ("Oneindia Gujarati", "https://gujarati.oneindia.com/rss/feeds/gujarati-news-fb.xml"),
        ],
        "Entertainment": [
            ("Oneindia Gujarati", "https://gujarati.oneindia.com/rss/feeds/gujarati-entertainment-fb.xml"),
        ],
    },
    "ta": {
        "Top Stories": [
            ("BBC Tamil", "https://feeds.bbci.co.uk/tamil/rss.xml"),
            ("Oneindia Tamil", "https://tamil.oneindia.com/rss/feeds/tamil-news-fb.xml"),
        ],
        "Entertainment": [
            ("Oneindia Tamil", "https://tamil.oneindia.com/rss/feeds/tamil-entertainment-fb.xml"),
        ],
    },
    "te": {
        "Top Stories": [
            ("BBC Telugu", "https://feeds.bbci.co.uk/telugu/rss.xml"),
            ("Oneindia Telugu", "https://telugu.oneindia.com/rss/feeds/telugu-news-fb.xml"),
        ],
        "Entertainment": [
            ("Oneindia Telugu", "https://telugu.oneindia.com/rss/feeds/telugu-entertainment-fb.xml"),
        ],
    },
    "kn": {
        # No BBC Kannada edition exists, so this language relies on Oneindia only.
        "Top Stories": [
            ("Oneindia Kannada", "https://kannada.oneindia.com/rss/feeds/kannada-news-fb.xml"),
        ],
        "Entertainment": [
            ("Oneindia Kannada", "https://kannada.oneindia.com/rss/feeds/kannada-entertainment-fb.xml"),
        ],
    },
}

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def summarize(text, max_len=420):
    text = clean_text(text)
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len].rsplit(" ", 1)[0]
    return truncated.rstrip(",.;:-") + "…"


def parse_date(raw):
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def fetch_feed(source_name, url):
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        channel = root.find("channel")
        entries = channel.findall("item") if channel is not None else root.findall(f"{ATOM_NS}entry")

        for entry in entries:
            title = clean_text(entry.findtext("title"))
            link = entry.findtext("link")
            if not link:
                link_el = entry.find(f"{ATOM_NS}link")
                link = link_el.get("href") if link_el is not None else ""
            pub_raw = entry.findtext("pubDate") or entry.findtext(f"{ATOM_NS}published")
            pub_dt = parse_date(pub_raw)
            desc_raw = (
                entry.findtext("description")
                or entry.findtext(f"{ATOM_NS}summary")
                or entry.findtext(f"{ATOM_NS}content")
                or ""
            )
            summary = summarize(desc_raw)
            # Some feeds just repeat the title in the description — skip those
            if summary and summary.lower().rstrip(".…") == title.lower().rstrip(".…"):
                summary = ""
            if not title or not link:
                continue
            items.append({
                "title": title,
                "link": link.strip(),
                "source": source_name,
                "summary": summary,
                "published": pub_dt.isoformat() if pub_dt else None,
                "_sort": pub_dt or datetime.min.replace(tzinfo=timezone.utc),
            })
    except Exception as e:
        print(f"  [warn] failed to fetch {source_name} ({url}): {e}", file=sys.stderr)
    return items


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = it["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def today_str():
    now = datetime.now(PACIFIC_TZ) if PACIFIC_TZ else datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


def load_usage():
    """Returns how many AI calls have already been made today (resets when
    the Pacific-time date rolls over, matching Google's quota reset)."""
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today_str():
            return int(data.get("count", 0))
    except Exception:
        pass
    return 0


def save_usage(count):
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today_str(), "count": count}, f)


def ai_rewrite(title, source_name, snippet, ai_name):
    """Ask Gemini (free, no card required) to rewrite the snippet in original
    words. Returns None on any failure so the caller can fall back to the
    plain truncated snippet -- nothing breaks if the free API is unreachable
    or rate-limited. ai_name is the English name of the target language
    (e.g. "Hindi"), or None for English."""
    language_instruction = (
        f"Write the summary in {ai_name} language, using {ai_name} script "
        f"(not English, not transliterated) -- the headline and snippet below "
        f"are already in {ai_name}, so match that. "
        if ai_name else ""
    )
    prompt = (
        "You are writing a short news digest blurb for a site called NewsBits India. "
        "Using ONLY the headline and snippet below, write an original summary in your "
        "own words -- not copied phrasing -- that gives a busy reader the full gist of "
        "this story in roughly 7 to 10 short lines. "
        f"{language_instruction}"
        "If the snippet is thin, write less "
        "rather than padding it out -- never invent facts, numbers, quotes, or details "
        "that are not present in the input. Plain, clear, conversational language. "
        "Output only the summary text, no headings or preamble.\n\n"
        f"Headline: {title}\n"
        f"Source: {source_name}\n"
        f"Snippet: {snippet or '(no snippet available, headline only -- keep it brief)'}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 300},
    }).encode("utf-8")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{AI_MODEL}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text or None
    except Exception as e:
        print(f"  [warn] AI rewrite failed for '{title[:60]}': {e}", file=sys.stderr)
        return None


def fetch_language(lang_code, feeds_by_category):
    """Fetches + dedupes all categories for one language. Returns
    (categories_raw dict, representative dict of link -> item)."""
    categories_raw = {}
    for category, sources in feeds_by_category.items():
        print(f"  Fetching category: {category}")
        cat_items = []
        for source_name, url in sources:
            cat_items.extend(fetch_feed(source_name, url))
        cat_items = dedupe(cat_items)
        cat_items.sort(key=lambda x: x["_sort"], reverse=True)
        categories_raw[category] = cat_items[:MAX_ITEMS_PER_CATEGORY]

    representative = {}
    for items in categories_raw.values():
        for it in items:
            representative.setdefault(it["link"], it)

    return categories_raw, representative


def main():
    cache = load_cache()
    calls_today = load_usage()
    budget_left = max(0, DAILY_AI_CALL_LIMIT - calls_today)
    ai_calls_used = 0

    all_rewritten_by_link = {}
    languages_output = {}

    for lang_code, lang_info in LANGUAGES.items():
        print(f"Fetching language: {lang_info['label']} ({lang_code})")
        feeds_by_category = FEEDS_BY_LANG.get(lang_code, {})
        categories_raw, representative = fetch_language(lang_code, feeds_by_category)

        rewritten_by_link = {}
        for link, it in representative.items():
            if link in cache:
                rewritten_by_link[link] = cache[link]
            elif GEMINI_API_KEY and budget_left > 0:
                rewritten = ai_rewrite(it["title"], it["source"], it["summary"], lang_info["ai_name"])
                ai_calls_used += 1
                budget_left -= 1
                if rewritten:
                    rewritten_by_link[link] = rewritten
                time.sleep(AI_CALL_DELAY_SECONDS)

        for items in categories_raw.values():
            for it in items:
                if it["link"] in rewritten_by_link:
                    it["summary"] = rewritten_by_link[it["link"]]

        all_rewritten_by_link.update(rewritten_by_link)

        categories = {
            cat: [{k: v for k, v in it.items() if k != "_sort"} for it in items]
            for cat, items in categories_raw.items()
        }

        all_items = []
        for items in categories_raw.values():
            all_items.extend(items)
        all_items = dedupe(all_items)
        all_items.sort(key=lambda x: x["_sort"], reverse=True)
        top_stories = [{k: v for k, v in it.items() if k != "_sort"} for it in all_items[:MAX_TOP_STORIES]]

        # English keeps its own curated category set; regional languages get
        # an aggregated "Top Stories" plus whatever categories they define.
        if "Top Stories" in categories:
            ordered_categories = categories
        else:
            ordered_categories = {"Top Stories": top_stories, **categories}

        languages_output[lang_code] = {
            "label": lang_info["label"],
            "categories": ordered_categories,
        }

    save_usage(calls_today + ai_calls_used)

    # Persist only the links currently on-site, so the cache doesn't grow forever
    all_representative_links = set()
    for lang_data in languages_output.values():
        for items in lang_data["categories"].values():
            for it in items:
                all_representative_links.add(it["link"])
    save_cache({link: text for link, text in all_rewritten_by_link.items() if link in all_representative_links})

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "languages": languages_output,
    }

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(
        len(items) for lang_data in languages_output.values() for items in lang_data["categories"].values()
    )
    if GEMINI_API_KEY:
        note = (
            f", {ai_calls_used} new AI rewrite attempt(s) this run "
            f"({calls_today + ai_calls_used}/{DAILY_AI_CALL_LIMIT} of today's shared AI budget used)"
        )
    else:
        note = " (GEMINI_API_KEY not set -- using original publisher snippets)"
    print(f"Wrote news.json with {total} items across {len(languages_output)} languages{note}.")


if __name__ == "__main__":
    main()
