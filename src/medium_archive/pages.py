"""Post page parsing: metadata extraction and body cleanup.

Shared by fetch (for the publish-date check) and convert.
"""

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .images import is_tracking_pixel
from .urls import canonical_url

MEDIUM_FOOTER_RE = re.compile(
    r"was originally published (in|on) .*Medium|"
    r"continuing the conversation by highlighting|"
    r"Continue reading on Medium",
    re.I,
)

# Medium's JSON-LD currently types posts as SocialMediaPosting.
LD_POST_TYPES = ("NewsArticle", "Article", "BlogPosting", "SocialMediaPosting")

# Un-hydrated page chrome that renders as bare text: separator dots,
# clap/response count placeholders, the read-time line, story badges.
PAGE_NOISE_RE = re.compile(r"·|-{1,2}|\d+ min read|Featured|Member-only( story)?")

ZOOM_HINT = "Press enter or click to view image in full size"

APOLLO_TAGS_RE = re.compile(r'"tags":\[((?:\{"__ref":"Tag:[^"]+"\},?)+)\]')
TAG_REF_RE = re.compile(r'"Tag:([^"]+)"')


def parse_ld_json(soup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") in LD_POST_TYPES:
                return item
    return {}


def anchor_tags(soup) -> list:
    """Tag names from /tag/ or /tagged/ links (older rendered pages). The
    path must start there: a body link to e.g. a GitHub release also
    contains '/tag/' but is not a Medium tag."""
    out = []
    for a in soup.select("a[href]"):
        if urlparse(a["href"]).path.startswith(("/tag/", "/tagged/")):
            t = a.get_text(strip=True)
            if t and t not in out:
                out.append(t)
    return out


def apollo_tags(soup) -> list:
    """Tag slugs from the page's embedded Apollo state. The rendered tag
    pills are plain <span>s now, so there are no /tag/ links to scrape."""
    for tag in soup.find_all("script"):
        text = tag.string or ""
        if "__APOLLO_STATE__" not in text:
            continue
        m = APOLLO_TAGS_RE.search(text)
        if m:
            return TAG_REF_RE.findall(m.group(1))
    return []


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
        "tags": apollo_tags(soup) or anchor_tags(soup),
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


def page_body(soup, tags=()):
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
    # Clap/vote widgets render their count as bare text; zoom hints sit
    # inside the figure itself, next to the real image.
    for el in article.select('[class*="pw-multi-vote"]'):
        el.decompose()
    for el in article.find_all(["span", "div"]):
        if el.parent is not None and el.find("img") is None \
                and el.get_text(strip=True) == ZOOM_HINT:
            el.decompose()
    # Tag pills are <span>s whose whole text is a tag name; only remove
    # matches outside real content elements, so body words stay intact.
    slugs = {t.lower().replace(" ", "-") for t in tags}
    for el in article.find_all(["a", "span", "p"]):
        if (el.parent is None or el.find("img") is not None
                or "pw-post-body-paragraph" in (el.get("class") or [])):
            continue
        text = el.get_text(strip=True)
        if (PAGE_NOISE_RE.fullmatch(text)
                or (slugs and text.lower().replace(" ", "-") in slugs)):
            if el.find_parent(["p", "li", "h2", "h3", "h4", "blockquote", "figure", "pre"]) is None:
                el.decompose()
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
