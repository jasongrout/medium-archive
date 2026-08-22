"""Post page parsing: metadata extraction and body cleanup.

Shared by fetch (for the publish-date check) and convert.
"""

import json
import re

from bs4 import BeautifulSoup

from .images import is_tracking_pixel
from .urls import canonical_url

MEDIUM_FOOTER_RE = re.compile(
    r"was originally published (in|on) .*Medium|"
    r"continuing the conversation by highlighting|"
    r"Continue reading on Medium",
    re.I,
)


def parse_ld_json(soup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") in ("NewsArticle", "Article", "BlogPosting"):
                return item
    return {}


def meta(soup, **attrs) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    return tag.get("content") if tag else None


def extract_metadata(soup, url: str) -> dict:
    ld = parse_ld_json(soup)
    author = ld.get("author")
    if isinstance(author, list):
        author = author[0] if author else None
    author_name = author.get("name") if isinstance(author, dict) else author
    author_url = author.get("url") if isinstance(author, dict) else None
    canon = soup.find("link", rel="canonical")
    return {
        "url": canonical_url(canon["href"]) if canon and canon.get("href") else url,
        "title": ld.get("headline") or meta(soup, property="og:title")
                 or (soup.h1.get_text(strip=True) if soup.h1 else ""),
        "author": author_name or meta(soup, name="author") or "",
        "author_url": author_url,
        "date": ld.get("datePublished") or meta(soup, property="article:published_time") or "",
        "updated": ld.get("dateModified"),
        "description": ld.get("description") or meta(soup, name="description") or "",
        "tags": [t.get_text(strip=True) for t in soup.select('a[href*="/tag/"], a[href*="/tagged/"]')],
    }


def strip_medium_footer(node):
    """Remove the '<hr><p>... was originally published in ... on Medium ...</p>'
    boilerplate Medium appends to feed bodies (and the preceding <hr>)."""
    for p in node.find_all(["p", "div"]):
        if p.parent is None or not MEDIUM_FOOTER_RE.search(p.get_text(" ", strip=True)):
            continue
        prev = p.find_previous_sibling(True)
        if prev is not None and prev.name == "hr":
            prev.decompose()
        p.decompose()


def strip_tracking_pixels(node):
    for img in node.find_all("img"):
        if is_tracking_pixel(img.get("src") or ""):
            img.decompose()


def page_body(soup):
    """<article> with Medium chrome removed."""
    article = soup.find("article") or soup.body
    for sel in (
        "h1",                      # title lives in front matter
        '[data-testid="authorName"]',
        '[data-testid="storyPublishDate"]',
        '[data-testid="storyReadTime"]',
        '[data-testid="headerClapButton"]',
        '[data-testid="headerSocialShareButton"]',
        "button", "svg", "noscript", "footer",
    ):
        for t in article.select(sel):
            t.decompose()
    # Author header block: holds profile links, no paragraphs or figures.
    for a in article.select('a[href*="/@"], a[rel*="author"]'):
        header = a.find_parent("div")
        if header and not header.find("p") and not header.find("figure"):
            header.decompose()
    strip_tracking_pixels(article)
    strip_medium_footer(article)
    return article


def feed_body(content_html: str):
    soup = BeautifulSoup(f"<article>{content_html}</article>", "html.parser")
    article = soup.article
    strip_tracking_pixels(article)
    first = article.find(["h1", "h2", "h3", "h4"])
    if first and first is article.find(True):   # repeated title
        first.decompose()
    strip_medium_footer(article)
    return article
