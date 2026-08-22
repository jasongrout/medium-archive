"""Post discovery: the publication sitemap tree and RSS feed."""

import sys
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .dates import parse_date
from .net import fetch
from .urls import canonical_url, is_post_url


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


def discover(session, base: str, raw_dir: Path) -> tuple[list, dict]:
    """([(url, approx_date)], feed_items). Saves the feed XML to raw/feed.xml."""
    base_host = urlparse(base).netloc
    feed = {}
    try:
        feed = fetch_feed(session, base, raw_dir)
    except Exception as e:
        print(f"feed failed ({e}); continuing without feed bodies", file=sys.stderr)
    entries = [(u, parse_date(it["date"])) for u, it in feed.items()]
    try:
        entries += walk_sitemap(session, base.rstrip("/") + "/sitemap/sitemap.xml", base_host)
    except Exception as e:
        print(f"sitemap failed ({e}); only feed posts will be available", file=sys.stderr)
    best = {}
    for u, d in entries:          # feed entries come first; their dates are true publish dates
        if u not in best or best[u] is None:
            best[u] = d
    return list(best.items()), feed
