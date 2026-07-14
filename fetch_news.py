#!/usr/bin/env python3
"""
fetch_news.py

Fetches the latest headlines from a set of public RSS feeds -- in English
plus six Indian regional languages (Hindi, Gujarati, Tamil, Telugu,
Kannada, Bengali) -- and writes them to news.json, grouped by language
then category. Uses only the Python standard library, so it needs no
extra dependencies to run (works out of the box in GitHub Actions).

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
# If GEMINI_API_KEY is set (as a GitHub Actions secret), articles get
# rewritten in original wording via Google's free Gemini API instead of
# just using the publisher's raw RSS snippet. Gemini's free tier
# (aistudio.google.com) needs no credit card. Results are cached in
# summary_cache.json so a given article is only ever rewritten once.
#
# NOTE: this used to call Groq, but Groq's Cloudflare-based anti-abuse
# rules block requests from datacenter/CI IPs (including GitHub Actions
# runners) with a blanket 403 -- confirmed by Groq's own team on their
# community forum. Gemini does not have this restriction.
#
# NOTE 2: Google's documented free-tier limits for this model (15 RPM /
# 1000 RPD) turned out not to match what this specific account was
# actually granted -- checking aistudio.google.com/rate-limit showed this
# project's real cap is only 10 requests/minute and 20 requests/day. Usage
# is tracked persistently across runs in ai_usage.json (committed
# alongside summary_cache.json), resetting at midnight Pacific time to
# match Google's reset schedule. If your account has higher limits, raise
# DAILY_AI_CALL_LIMIT accordingly (check your own numbers at the URL
# above).
#
# NOTE 3: this budget is SHARED across all seven languages. To make it go
# much further, articles are rewritten in BATCHES (BATCH_SIZE per API
# call) instead of one call per article -- one call can cover several
# articles' worth of summaries, which is what makes full-language AI
# coverage realistic under a ~15-20 calls/day cap. Non-English languages
# are processed BEFORE English, since their raw RSS snippets are often in
# English even when the headline is in the native script (a quirk of some
# regional publishers' feeds) -- until an article gets its AI rewrite, no
# summary is shown at all for non-English languages, rather than risking
# an English snippet appearing under a native-language headline.
#
# NOTE 4: every summary (all languages, including English) is a detailed
# 10-15 line rewrite, not a short blurb -- see the prompt in
# ai_rewrite_batch(). This costs more output tokens per call, which is
# why BATCH_SIZE is kept modest (5) even though a single call could
# technically ask for more articles at once.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# gemini-2.5-flash-lite was retired for new API keys/projects (confirmed via
# the actual Gemini error body: "This model models/gemini-2.5-flash-lite is
# no longer available to new users") -- gemini-3.1-flash-lite is its current
# direct replacement: same low-latency/low-cost tier, still free-tier
# eligible, same generateContent REST endpoint shape.
AI_MODEL = "gemini-3.1-flash-lite"
CACHE_FILE = "summary_cache.json"
USAGE_FILE = "ai_usage.json"
DAILY_AI_CALL_LIMIT = 18  # stays under this account's observed 20 requests/day cap
AI_CALL_DELAY_SECONDS = 7  # stays under this account's observed 10 requests/minute cap
BATCH_SIZE = 5  # articles rewritten per Gemini call, to stretch the daily budget

# code -> display label (native script) + English name used in the AI prompt
LANGUAGES = {
    "en": {"label": "English", "ai_name": None},
    "hi": {"label": "हिन्दी", "ai_name": "Hindi"},
    "gu": {"label": "ગુજરાતી", "ai_name": "Gujarati"},
    "ta": {"label": "தமிழ்", "ai_name": "Tamil"},
    "te": {"label": "తెలుగు", "ai_name": "Telugu"},
    "kn": {"label": "ಕನ್ನಡ", "ai_name": "Kannada"},
    "bn": {"label": "বাংলা", "ai_name": "Bengali"},
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
        # Navbharat Times, Patrika 404'd/timed out from the GitHub Actions
        # runner (confirmed via production log) even though some looked fine
        # from direct manual checks -- removed rather than left as dead weight.
        "Top Stories": [
            ("BBC Hindi", "https://feeds.bbci.co.uk/hindi/rss.xml"),
            ("Oneindia Hindi", "https://hindi.oneindia.com/rss/feeds/hindi-news-fb.xml"),
            ("Amar Ujala", "https://www.amarujala.com/rss/breaking-news.xml"),
            ("Dainik Bhaskar", "https://www.bhaskar.com/rss-feed/1061/"),
            ("Live Hindustan", "https://feed.livehindustan.com/rss/3127"),
        ],
        "Entertainment": [
            ("Oneindia Hindi", "https://hindi.oneindia.com/rss/feeds/hindi-entertainment-fb.xml"),
        ],
    },
    "gu": {
        # Gujarat Samachar and Oneindia Gujarati's entertainment/cinema feeds
        # 404'd from the GitHub Actions runner -- removed.
        "Top Stories": [
            ("BBC Gujarati", "https://feeds.bbci.co.uk/gujarati/rss.xml"),
            ("Oneindia Gujarati", "https://gujarati.oneindia.com/rss/feeds/gujarati-news-fb.xml"),
            ("Divya Bhaskar", "https://www.divyabhaskar.co.in/rss-feed/1037/"),
        ],
    },
    "ta": {
        # Puthiya Thalaimurai 404'd from the GitHub Actions runner -- removed.
        "Top Stories": [
            ("BBC Tamil", "https://feeds.bbci.co.uk/tamil/rss.xml"),
            ("Oneindia Tamil", "https://tamil.oneindia.com/rss/feeds/tamil-news-fb.xml"),
        ],
        "Entertainment": [
            # Oneindia Tamil calls this category "cinema", not "entertainment"
            ("Oneindia Tamil", "https://tamil.oneindia.com/rss/feeds/tamil-cinema-fb.xml"),
        ],
    },
    "te": {
        # Oneindia Telugu's "cinema" feed 404'd (only "entertainment" works).
        # Eenadu has no confirmed native RSS feed, so it's pulled via a
        # site-filtered Google News RSS search instead -- verified working
        # (100 items, real eenadu.net article titles) even though it wasn't
        # findable as a direct feed. Article links route through a Google
        # News redirect rather than straight to eenadu.net, but they resolve
        # fine for readers.
        "Top Stories": [
            ("BBC Telugu", "https://feeds.bbci.co.uk/telugu/rss.xml"),
            ("Oneindia Telugu", "https://telugu.oneindia.com/rss/feeds/telugu-news-fb.xml"),
            ("Sakshi", "https://www.sakshi.com/rss.xml"),
            ("Eenadu", "https://news.google.com/rss/search?q=site:eenadu.net&hl=te&gl=IN&ceid=IN:te"),
        ],
        "Entertainment": [
            ("Oneindia Telugu", "https://telugu.oneindia.com/rss/feeds/telugu-entertainment-fb.xml"),
        ],
    },
    "kn": {
        # No BBC Kannada edition exists, so this language leans on Oneindia +
        # Vijay Karnataka (Times Group, same reliable CMS as Times of India).
        "Top Stories": [
            ("Oneindia Kannada", "https://kannada.oneindia.com/rss/feeds/kannada-news-fb.xml"),
            ("Vijay Karnataka", "https://vijaykarnataka.com/rssfeedsdefault.cms"),
        ],
        "Entertainment": [
            ("Oneindia Kannada", "https://kannada.oneindia.com/rss/feeds/kannada-entertainment-fb.xml"),
        ],
    },
    "bn": {
        # Oneindia Bengali's whole rss/feeds/* family (news, entertainment,
        # cinema) 404'd from the GitHub Actions runner, and Ei Samay's
        # domain doesn't resolve at all (DNS failure) -- both removed.
        # Anandabazar Patrika has no discoverable native RSS feed (checked
        # common paths, all 404), so it's pulled via a site-filtered Google
        # News RSS search instead -- verified working (100 items, real
        # Anandabazar article titles in Bengali). Article links route
        # through a Google News redirect rather than straight to
        # anandabazar.com, but they resolve fine for readers.
        "Top Stories": [
            ("BBC Bangla", "https://feeds.bbci.co.uk/bengali/rss.xml"),
            ("Anandabazar Patrika", "https://news.google.com/rss/search?q=site:anandabazar.com&hl=bn&gl=IN&ceid=IN:bn"),
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


def is_low_quality_title(title):
    """Google-News-search-based feeds (used for sources with no native RSS,
    like Anandabazar Patrika and Eenadu) sometimes return non-article
    results instead of a single real headline: e-paper index/listing pages,
    or "digest" blocks that mash several unrelated headlines together.
    Filter those out rather than showing them as if they were one story."""
    t = title.lower()
    if "epaper" in t or "e-paper" in t:
        return True
    if re.search(r"-\s*page\s*\d+", t):
        return True
    # Multiple sentence-ending dandas ("।", used in both Bengali and Telugu
    # prose) in one title is a strong signal of several headlines glued
    # together rather than one clean headline.
    if title.count("।") >= 2:
        return True
    return False


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
            if is_low_quality_title(title):
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


def ai_rewrite_batch(items, ai_name):
    """Ask Gemini to rewrite a BATCH of articles' summaries in one call
    (much cheaper against the daily rate limit than one call per article).
    items: list of dicts with 'title', 'source', 'summary' (raw snippet).
    Returns a list the same length as items, each element either the
    rewritten text or None (on per-item or whole-batch failure) -- callers
    fall back to no summary on None, nothing breaks."""
    language_instruction = (
        f"Write every summary ENTIRELY in {ai_name} language, using {ai_name} script throughout. "
        f"Even if the headline or snippet below is partly or fully in English (this happens with "
        f"some regional feeds), translate and rewrite it into natural, fluent {ai_name} -- do not "
        f"leave any English sentences in your output (well-known proper nouns or brand names may "
        f"stay as-is if there's no natural translation). "
        if ai_name else ""
    )
    numbered = "\n\n".join(
        f"Item {i}:\nHeadline: {it['title']}\nSource: {it['source']}\n"
        f"Snippet: {it['summary'] or '(no snippet, headline only -- keep it brief)'}"
        for i, it in enumerate(items)
    )
    prompt = (
        "You are writing detailed news digest summaries for a site called NewsBits India. "
        f"Below are {len(items)} separate news items, each numbered starting at 0. For EACH item, "
        "write an original summary in your own words -- not copied phrasing -- that gives a reader "
        "the full context and gist of that story. Each summary must be a MINIMUM of 10 to 15 lines "
        "(roughly 120-200 words) -- expand on the who/what/when/where/why, background context, and "
        "why it matters, using only what's supported by the headline and snippet. "
        f"{language_instruction}"
        "Only write fewer lines than that if the item's snippet is so thin there is genuinely "
        "nothing more to say without inventing facts, numbers, quotes, or details that are not "
        "present in that item's own input -- never fabricate specifics. Plain, clear, conversational "
        "language, multiple sentences forming a real paragraph (not a bare bullet list).\n\n"
        f"Respond with ONLY a JSON array of {len(items)} strings, in the same order as the items "
        "below (element 0 = Item 0's summary, element 1 = Item 1's summary, etc). No other text, "
        "no markdown code fences, no explanation -- just the raw JSON array.\n\n"
        f"{numbered}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1200 * max(1, len(items))},
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
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Be tolerant of markdown fences / stray commentary around the array
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        parsed = json.loads(text)
        if isinstance(parsed, list) and len(parsed) == len(items):
            return [(s.strip() if isinstance(s, str) and s.strip() else None) for s in parsed]
        print(
            f"  [warn] batch AI rewrite returned unexpected shape "
            f"(got {len(parsed) if isinstance(parsed, list) else type(parsed).__name__}, wanted {len(items)})",
            file=sys.stderr,
        )
        return [None] * len(items)
    except urllib.error.HTTPError as e:
        # The default str(e) is just "HTTP Error 404: Not Found" -- Google's
        # actual error body (in the response) says exactly what's wrong
        # (bad API key, model not found, quota exceeded, etc), so surface it.
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body = "(could not read error body)"
        print(f"  [warn] batch AI rewrite failed for {len(items)} item(s): HTTP {e.code}: {body}", file=sys.stderr)
        return [None] * len(items)
    except Exception as e:
        print(f"  [warn] batch AI rewrite failed for {len(items)} item(s): {e}", file=sys.stderr)
        return [None] * len(items)


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

    # --- Phase 1: fetch every language's RSS feeds -------------------------
    fetched = {}
    for lang_code, lang_info in LANGUAGES.items():
        print(f"Fetching language: {lang_info['label']} ({lang_code})")
        feeds_by_category = FEEDS_BY_LANG.get(lang_code, {})
        fetched[lang_code] = fetch_language(lang_code, feeds_by_category)

    # --- Phase 2: AI rewrite, batched, ROUND-ROBIN across languages --------
    # Non-English feeds sometimes carry English-language RSS descriptions
    # even when the headline is in the native script, so non-English
    # languages get first claim on the shared daily AI budget -- English's
    # raw snippet is at least readable as a fallback while it waits its turn.
    #
    # IMPORTANT: this must cycle ONE BATCH PER LANGUAGE AT A TIME, not
    # exhaust language A's entire backlog before touching language B. An
    # earlier version did exactly that (in dict order hi/gu/ta/te/kn/bn) --
    # since Hindi/Gujarati/Tamil/Telugu alone regularly had 18+ calls worth
    # of uncached articles, Kannada and Bengali were pushed to the back of
    # the line every single run and never got a single AI summary, no
    # matter how many days passed. Round-robin guarantees every language
    # gets a turn each run as long as any shared budget remains.
    process_order = [c for c in LANGUAGES if c != "en"] + (["en"] if "en" in LANGUAGES else [])
    all_rewritten_by_link = {}

    to_rewrite_by_lang = {}
    for lang_code in process_order:
        _, representative = fetched[lang_code]
        for link in representative:
            if link in cache:
                all_rewritten_by_link[link] = cache[link]
        to_rewrite_by_lang[lang_code] = [(link, it) for link, it in representative.items() if link not in cache]

    cursor = {lang_code: 0 for lang_code in process_order}
    is_first_call = True
    while GEMINI_API_KEY and budget_left > 0:
        made_progress = False
        for lang_code in process_order:
            if budget_left <= 0:
                break
            items_left = to_rewrite_by_lang[lang_code]
            start = cursor[lang_code]
            if start >= len(items_left):
                continue
            made_progress = True
            batch = items_left[start: start + BATCH_SIZE]
            if not is_first_call:
                time.sleep(AI_CALL_DELAY_SECONDS)
            is_first_call = False
            results = ai_rewrite_batch(
                [{"title": it["title"], "source": it["source"], "summary": it["summary"]} for _, it in batch],
                LANGUAGES[lang_code]["ai_name"],
            )
            ai_calls_used += 1
            budget_left -= 1
            for (link, _it), rewritten in zip(batch, results):
                if rewritten:
                    all_rewritten_by_link[link] = rewritten
            cursor[lang_code] = start + BATCH_SIZE
        if not made_progress:
            break

    save_usage(calls_today + ai_calls_used)

    # --- Phase 3: apply rewrites and build the output ----------------------
    languages_output = {}
    for lang_code, lang_info in LANGUAGES.items():
        categories_raw, _representative = fetched[lang_code]

        for items in categories_raw.values():
            for it in items:
                if it["link"] in all_rewritten_by_link:
                    it["summary"] = all_rewritten_by_link[it["link"]]
                elif lang_code != "en":
                    # No AI rewrite yet for this non-English article -- don't
                    # risk showing a raw snippet that might be in English.
                    it["summary"] = ""

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
            f", {ai_calls_used} new AI batch call(s) this run "
            f"({calls_today + ai_calls_used}/{DAILY_AI_CALL_LIMIT} of today's shared AI budget used)"
        )
    else:
        note = " (GEMINI_API_KEY not set -- using original publisher snippets for English only)"
    print(f"Wrote news.json with {total} items across {len(languages_output)} languages{note}.")


if __name__ == "__main__":
    main()
