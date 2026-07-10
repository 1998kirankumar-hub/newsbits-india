#!/usr/bin/env python3
"""
fetch_news.py

Fetches the latest headlines from a set of public RSS feeds (India + world
news) and writes them to news.json as short bullet-point items grouped by
category. Uses only the Python standard library, so it needs no extra
dependencies to run (works out of the box in GitHub Actions).

Run manually:      python3 fetch_news.py
Run automatically: see .github/workflows/update-news.yml (runs on a schedule)

To change the news sources, edit the FEEDS dictionary below. Any standard
RSS 2.0 or Atom feed URL will work.
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

USER_AGENT = "Mozilla/5.0 (compatible; SimpleNewsBot/1.0)"
TIMEOUT = 15
MAX_ITEMS_PER_CATEGORY = 12
MAX_TOP_STORIES = 14

# --- AI rewrite settings -----------------------------------------------
# If GROQ_API_KEY is set (as a GitHub Actions secret), each article's
# summary is rewritten in original wording via Groq's free API instead of
# just truncating the publisher's RSS snippet. Groq's developer tier is
# free with no credit card required (console.groq.com), rate-limited but
# plenty for this use case. Results are cached in summary_cache.json so a
# given article is only ever rewritten once, keeping well within the free
# rate limits even though the workflow runs frequently.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
AI_MODEL = "openai/gpt-oss-20b"  # free on Groq; check console.groq.com/docs/models if this is deprecated
CACHE_FILE = "summary_cache.json"
MAX_NEW_AI_CALLS_PER_RUN = 20  # stays well under Groq's free-tier per-minute limits
AI_CALL_DELAY_SECONDS = 1.5  # small pause between calls to stay under rate limits

# category -> list of (source name, RSS feed URL)
FEEDS = {
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


def ai_rewrite(title, source_name, snippet):
    """Ask Groq (free, no card required) to rewrite the snippet in original
    words. Returns None on any failure so the caller can fall back to the
    plain truncated snippet -- nothing breaks if the free API is unreachable
    or rate-limited."""
    prompt = (
        "You are writing a short news digest blurb for a site called NewsBits India. "
        "Using ONLY the headline and snippet below, write an original summary in your "
        "own words -- not copied phrasing -- that gives a busy reader the full gist of "
        "this story in roughly 7 to 10 short lines. If the snippet is thin, write less "
        "rather than padding it out -- never invent facts, numbers, quotes, or details "
        "that are not present in the input. Plain, clear, conversational language. "
        "Output only the summary text, no headings or preamble.\n\n"
        f"Headline: {title}\n"
        f"Source: {source_name}\n"
        f"Snippet: {snippet or '(no snippet available, headline only -- keep it brief)'}"
    )
    body = json.dumps({
        "model": AI_MODEL,
        "max_tokens": 250,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception as e:
        print(f"  [warn] AI rewrite failed for '{title[:60]}': {e}", file=sys.stderr)
        return None


def main():
    categories_raw = {}

    for category, sources in FEEDS.items():
        print(f"Fetching category: {category}")
        cat_items = []
        for source_name, url in sources:
            cat_items.extend(fetch_feed(source_name, url))
        cat_items = dedupe(cat_items)
        cat_items.sort(key=lambda x: x["_sort"], reverse=True)
        categories_raw[category] = cat_items[:MAX_ITEMS_PER_CATEGORY]

    # One representative item per unique article link, so a story that
    # appears in multiple categories only gets rewritten (and paid for) once.
    representative = {}
    for items in categories_raw.values():
        for it in items:
            representative.setdefault(it["link"], it)

    cache = load_cache()
    rewritten_by_link = {}
    ai_calls_used = 0

    for link, it in representative.items():
        if link in cache:
            rewritten_by_link[link] = cache[link]
        elif GROQ_API_KEY and ai_calls_used < MAX_NEW_AI_CALLS_PER_RUN:
            rewritten = ai_rewrite(it["title"], it["source"], it["summary"])
            ai_calls_used += 1
            if rewritten:
                rewritten_by_link[link] = rewritten
            time.sleep(AI_CALL_DELAY_SECONDS)

    for items in categories_raw.values():
        for it in items:
            if it["link"] in rewritten_by_link:
                it["summary"] = rewritten_by_link[it["link"]]

    # Persist only the links currently on-site, so the cache doesn't grow forever
    save_cache({link: text for link, text in rewritten_by_link.items() if link in representative})

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

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "categories": {"Top Stories": top_stories, **categories},
    }

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in output["categories"].values())
    if GROQ_API_KEY:
        note = f", {ai_calls_used} new AI rewrite(s) this run"
    else:
        note = " (GROQ_API_KEY not set -- using original publisher snippets)"
    print(f"Wrote news.json with {total} items across {len(output['categories'])} categories{note}.")


if __name__ == "__main__":
    main()
