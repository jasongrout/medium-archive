"""Post discovery: the publication sitemap tree, RSS feed, and the
Wayback Machine's index of past captures."""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup

from .dates import parse_date
from .net import fetch
from .urls import canonical_url, is_post_url, medium_id

WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"


def walk_sitemap(session, url, base_host, seen=None) -> list:
    """[(url, lastmod|None), ...] for every post URL in the sitemap tree."""
    seen = seen if seen is not None else set()
    if url in seen:
        return []
    seen.add(url)
    soup = BeautifulSoup(fetch(session, url).text, "xml")
    entries = []
    if soup.find("sitemapindex"):
        for loc in soup.select("sitemap > loc"):
            entries.extend(walk_sitemap(session, loc.text.strip(), base_host, seen))
    else:
        for node in soup.find_all("url"):
            loc = node.find("loc")
            if not loc:
                continue
            u = canonical_url(loc.text.strip())
            if is_post_url(u, base_host):
                lastmod = node.find("lastmod")
                entries.append((u, parse_date(lastmod.text) if lastmod else None))
    return entries


def parse_feed(xml_text: str, base_host: str) -> dict:
    """{url: {title, author, tags, date, content_html}} from RSS XML."""
    soup = BeautifulSoup(xml_text, "xml")
    items = {}
    for item in soup.find_all("item"):
        if not item.link:
            continue
        u = canonical_url(item.link.text.strip())
        if not is_post_url(u, base_host):
            continue
        pub = item.find("pubDate")
        creator = item.find("dc:creator") or item.find("creator")
        content = item.find("content:encoded") or item.find("encoded")
        items[u] = {
            "title": item.title.text.strip() if item.title else "",
            "author": creator.text.strip() if creator else "",
            "tags": [c.text.strip() for c in item.find_all("category") if c.text],
            "date": pub.text.strip() if pub else None,
            "content_html": content.text if content else "",
        }
    return items


def fetch_feed(session, base: str, raw_dir: Path) -> dict:
    """Download the RSS feed, save it to raw/feed.xml, and parse it."""
    xml_text = fetch(session, base.rstrip("/") + "/feed").text
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "feed.xml").write_text(xml_text, encoding="utf-8")
    return parse_feed(xml_text, urlparse(base).netloc)


def wayback_urls(session, base: str) -> list:
    """[(url, first_capture_date), ...] for every post URL the Wayback Machine
    has ever captured on the publication host.

    Medium's sitemap only reaches a few years back, so older posts -- still
    live on Medium -- are invisible to sitemap+feed discovery. The CDX index
    of past captures recovers their URLs; the posts themselves are then
    fetched from the live site as usual. Like sitemap lastmod, the
    first-capture date is an approximation that can only be later than the
    publish date.
    """
    p = urlparse(base)
    entries, resume = [], None
    while True:
        query = urlencode({
            "url": p.netloc + "/*",
            "fl": "original,timestamp",
            "collapse": "urlkey",     # one row per URL: its earliest capture
            "limit": 10000,
            "showResumeKey": "true",
        })
        if resume:
            query += "&resumeKey=" + resume   # returned already URL-encoded
        lines = fetch(session, f"{WAYBACK_CDX}?{query}").text.splitlines()
        resume = None
        for i, line in enumerate(lines):
            if not line.strip():              # blank line, then the resume key
                resume = next((l.strip() for l in lines[i + 1:] if l.strip()), None)
                break
            original, _, ts = line.strip().rpartition(" ")
            u = canonical_url(f"{p.scheme}://{p.netloc}{urlparse(original).path}")
            if not is_post_url(u, p.netloc):
                continue
            try:
                d = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError:
                d = None
            entries.append((u, d))
        if not resume:
            return entries
        time.sleep(1)


def discover(session, base: str, raw_dir: Path, wayback: bool = False) -> tuple[list, dict]:
    """([(url, approx_date, source)], feed_items). Saves the feed XML to
    raw/feed.xml. source is the first of feed/sitemap/wayback that listed the
    URL, so source == "wayback" means Medium itself no longer lists the post."""
    base_host = urlparse(base).netloc
    feed = {}
    try:
        feed = fetch_feed(session, base, raw_dir)
    except Exception as e:
        print(f"feed failed ({e}); continuing without feed bodies", file=sys.stderr)
    entries = [(u, parse_date(it["date"]), "feed") for u, it in feed.items()]
    try:
        entries += [(u, d, "sitemap") for u, d in
                    walk_sitemap(session, base.rstrip("/") + "/sitemap/sitemap.xml", base_host)]
    except Exception as e:
        print(f"sitemap failed ({e}); only feed posts will be available", file=sys.stderr)
    if wayback:
        try:
            found = wayback_urls(session, base)
            print(f"wayback: {len(found)} candidate post URLs", file=sys.stderr)
            entries += [(u, d, "wayback") for u, d in found]
        except Exception as e:
            print(f"wayback failed ({e}); continuing without it", file=sys.stderr)
    # Earlier sources win: feed (true publish dates), then sitemap, then
    # wayback. Keyed by Medium id so the same post under an old slug (Medium
    # redirects them) does not become a second entry.
    best = {}
    for u, d, s in entries:
        key = medium_id(u) or u
        if key not in best:
            best[key] = [u, d, s]
        elif best[key][1] is None and d is not None:
            best[key][1] = d
    return [tuple(e) for e in best.values()], feed
