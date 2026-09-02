"""Post page parsing: metadata extraction and body cleanup.

Shared by fetch (for the publish-date check) and convert.
"""

import json
import re
from urllib.parse import urljoin, urlparse

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

# What a title leaves behind when it is cut off the front of a summary:
# the space after it, and the sentence or clause punctuation Medium wrote
# between the two halves.
TITLE_TAIL_RE = re.compile(r"^[\s.,:;|\u00b7\u2013\u2014-]+")


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


ELLIPSIS = "\u2026"


def norm_title(s: str) -> str:
    """A title or heading in comparable form: case-folded, with the
    whitespace Medium varies (non-breaking and hair spaces, line breaks)
    collapsed to single spaces."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


def heading_is_title(heading: str, title: str) -> bool:
    """Whether a body heading is the post title.

    Medium gives an untitled post the text of its opening heading as its
    title, cut to about a hundred characters with an ellipsis; the
    truncated form is what the stored title, the JSON-LD headline and
    og:title all carry, while the heading itself keeps the full text.
    So a title ending in an ellipsis matches a heading it is a prefix
    of, as well as an exact repeat.
    """
    h, t = norm_title(heading), norm_title(title)
    if not h or not t:
        return False
    if h == t:
        return True
    return t.endswith(ELLIPSIS) and h.startswith(t[:-1].rstrip())


def untruncated_title(title: str, heading: str) -> str:
    """The title, completed from the post's opening heading when Medium
    truncated it (see heading_is_title); otherwise the title as given."""
    title = (title or "").strip()
    heading = re.sub(r"\s+", " ", heading or "").strip()
    if title.endswith(ELLIPSIS) and heading_is_title(heading, title):
        return heading
    return title


def strip_title_prefix(description: str, title: str) -> str:
    """A description with the post title dropped from the front of it.

    Medium composes its summary text as "<title> <excerpt>", so the
    title arrives twice: once as the title, once at the head of the
    description. The account export's subtitle is the excerpt alone,
    which is what a description should be everywhere -- every page
    already renders the title above it, and a search result or a share
    card that repeats it spends its one line saying nothing.

    Matching ignores case and the whitespace Medium varies (non-breaking
    spaces, line breaks), and eats the punctuation left behind. A title
    that is itself ellipsis-truncated is left alone: there is no telling
    where it ended, so cutting it would strand the tail of the title at
    the front of the description.
    """
    description, title = (description or "").strip(), (title or "").strip()
    if not description or not title or title.endswith(("\u2026", "...")):
        return description
    m = re.match(r"\s+".join(map(re.escape, title.split())), description, re.I)
    return TITLE_TAIL_RE.sub("", description[m.end():]) if m else description


def _description(soup, ld: dict, title: str) -> str:
    """The post's summary, without the title it repeats.

    Medium caps its JSON-LD and <meta name=description> text, and spends
    the first of those characters on the title, so og:description -- the
    excerpt alone -- is both cleaner and longer; prefer it. The title
    still leads the excerpt on posts that open with it in the body
    (Medium's own early years, and the Ghost-era posts migrated into
    it), hence the strip on every candidate. A candidate that is nothing
    but the title says nothing the title doesn't, so fall through to the
    next one rather than describing the post with an empty string.
    """
    for text in (meta(soup, property="og:description"),
                 ld.get("description"),
                 meta(soup, name="description")):
        summary = strip_title_prefix(text or "", title)
        if summary:
            return summary
    return ""


def extract_metadata(soup, url: str) -> dict:
    ld = parse_ld_json(soup)
    author = ld.get("author")
    if isinstance(author, list):
        author = author[0] if author else None
    author_name = author.get("name") if isinstance(author, dict) else author
    author_url = author.get("url") if isinstance(author, dict) else None
    canon = soup.find("link", rel="canonical")
    # The rendered title heading keeps the full text of a title Medium
    # truncated in the headline and og:title (see untruncated_title).
    h1 = soup.find("h1", attrs={"data-testid": "storyTitle"}) or soup.h1
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    title = untruncated_title(
        ld.get("headline") or meta(soup, property="og:title") or "", h1_text
    ) or h1_text
    return {
        "url": canonical_url(canon["href"]) if canon and canon.get("href") else url,
        "title": title,
        "author": author_name or meta(soup, name="author") or "",
        "author_url": author_url,
        "date": ld.get("datePublished") or meta(soup, property="article:published_time") or "",
        "updated": ld.get("dateModified"),
        "description": _description(soup, ld, title),
        "tags": apollo_tags(soup) or anchor_tags(soup),
    }


def is_ghost_page(soup) -> bool:
    """Pages saved by import-ghost: Ghost stamps every page it renders
    with a generator meta tag, across versions and themes."""
    return (meta(soup, name="generator") or "").startswith("Ghost")


def ghost_metadata(soup, url: str) -> dict:
    """extract_metadata plus Ghost fallbacks. Newer Ghost versions emit
    JSON-LD, which extract_metadata already reads; older ones (0.x) only
    have Open Graph tags, and the author and tags live in theme markup."""
    info = extract_metadata(soup, url)
    if not info["date"]:
        t = soup.find("time", datetime=True)
        if t:
            info["date"] = t["datetime"]
    if not info["author"]:
        # Casper-style footer: <section class="author"><h4><a href="/author/x">
        for a in soup.select('.author h4 a, .author-card-name a, a[href*="/author/"]'):
            name = a.get_text(strip=True)
            if name and not name.lower().startswith("more posts"):
                info["author"] = name
                info["author_url"] = urljoin(info["url"], a.get("href", "")) or None
                break
    article = soup.find("article")
    if article:
        # Ghost puts each tag on the article element as a tag-<slug> class.
        tags = [c[len("tag-"):] for c in article.get("class", [])
                if c.startswith("tag-") and len(c) > len("tag-")]
        if tags:
            info["tags"] = tags
    return info


def ghost_body(soup):
    """The post content of a Ghost page, theme chrome removed. Ghost themes
    keep the content in a dedicated section (Casper: .post-content, later
    .post-full-content), separate from the title/date header and the
    author/share footer."""
    article = soup.find("article") or soup.body
    body = article.select_one('[class*="post-full-content"], [class*="post-content"]')
    if body is None:
        body = article
        for sel in ("header", "footer", 'h1[class*="title"]'):
            for t in body.select(sel):
                t.decompose()
    for sel in ("script", "style", "noscript", "form", "button", "svg",
                '[class*="subscribe"]'):
        for t in body.select(sel):
            t.decompose()
    return body


def collapse_br_pairs(node):
    """Undo Medium's Ghost-migration line-break damage: the importer turned
    each wrapped source line of the original post into a <br><br> pair
    mid-paragraph, so a pair stands for the space of a line wrap. Only for
    posts with a Ghost origin -- in posts authored in Medium's own editor a
    <br><br> is an intentional paragraph break. Inside <pre> a pair is a
    blank code line, and a lone <br> anywhere is a genuine soft break."""
    for br in node.find_all("br"):
        if br.parent is None:           # second of a pair, already removed
            continue
        nxt = br.next_sibling
        if getattr(nxt, "name", None) == "br" and br.find_parent("pre") is None:
            nxt.extract()
            br.replace_with(" ")


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


def split_pre_paragraphs(article):
    """Rendered pages pack consecutive code paragraphs as sibling <span>s
    inside a single <pre>, so converting loses the boundary between them;
    the account export keeps one <pre> per paragraph. Split to match."""
    doc = BeautifulSoup("", "html.parser")
    for pre in article.find_all("pre"):
        kids = [c for c in pre.children
                if c.name is not None or str(c).strip()]
        if len(kids) < 2 or any(c.name != "span" for c in kids):
            continue
        for span in kids:
            new_pre = doc.new_tag("pre")
            pre.insert_before(new_pre)
            new_pre.append(span.extract())
        pre.decompose()


def page_body(soup, tags=(), title=""):
    """<article> with Medium chrome removed."""
    article = soup.find("article") or soup.body
    for sel in (
        "h1",                      # title lives in front matter
        ".pw-subtitle-paragraph",  # subtitle is metadata, not body
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
    # Authors with a custom subdomain (name.medium.com) have no /@ in the
    # href, but every byline link carries a source=post_page---byline tag.
    for a in article.select('a[href*="/@"], a[rel*="author"], '
                            'a[href*="source=post_page---byline"]'):
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
    # Section dividers render as <div role="separator"> with dot <span>s,
    # not <hr>; the export uses a real <hr>.
    for el in article.select('div[role="separator"]'):
        el.replace_with(soup.new_tag("hr"))
    # Some pages render the post title as a body <h3> instead of the <h1>
    # Medium normally uses (removed above); the title lives in the front
    # matter, so a leading heading that repeats it is a duplicate.
    first = article.find(["h1", "h2", "h3", "h4", "p", "figure", "pre",
                          "ul", "ol", "blockquote"])
    if (first is not None and first.name.startswith("h")
            and heading_is_title(first.get_text(" ", strip=True), title)):
        first.decompose()
    split_pre_paragraphs(article)
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
