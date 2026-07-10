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
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "Mozilla/5.0 (compatible; SimpleNewsBot/1.0)"
TIMEOUT = 15
MAX_ITEMS_PER_CATEGORY = 12
MAX_TOP_STORIES = 14

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


def summarize(text, max_len=200):
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


def main():
    categories = {}
    all_items = []

    for category, sources in FEEDS.items():
        print(f"Fetching category: {category}")
        cat_items = []
        for source_name, url in sources:
            cat_items.extend(fetch_feed(source_name, url))
        cat_items = dedupe(cat_items)
        cat_items.sort(key=lambda x: x["_sort"], reverse=True)
        cat_items = cat_items[:MAX_ITEMS_PER_CATEGORY]
        all_items.extend(cat_items)
        categories[category] = [{k: v for k, v in it.items() if k != "_sort"} for it in cat_items]

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
    print(f"Wrote news.json with {total} items across {len(output['categories'])} categories.")


if __name__ == "__main__":
    main()
