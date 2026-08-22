#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "markdownify",
#     "lxml",
# ]
# ///
"""
Archive a Medium publication (default: https://blog.jupyter.org/) in two
independent steps:

    fetch    pull raw material from Medium: page HTML, RSS feed item, and
             full-resolution images, unmodified, into <out>/raw/
    convert  turn the raw archive into Markdown + front matter + local images
             in <out>/posts/, plus posts.json and redirects.csv

`convert` never touches the network, so it can be re-run freely while tuning
the conversion (selectors, Markdown style, output layout) without hitting
Medium again. `fetch` is incremental and resumable.

Output layout:
    <out>/
      README.md                        describes this layout, fields, caveats
      raw/
        index.json                       {url: {medium_id, sitemap_date, fetched_at}}
        feed.xml                         last RSS feed as downloaded
        <medium_id>/
          page.html                      post page, byte-for-byte as served
          feed_item.json                 this post's RSS item (if in the feed)
          images.json                    {source_url: filename} for images/
          images/<filename>              downloaded images
      posts.json                         converted posts, keyed by Medium URL
      redirects.csv                      original_path -> new post dir
      posts/<YYYY-MM-DD>-<slug>/
        index.md                         front matter (JSON, valid YAML) + Markdown
        images/<filename>                images referenced from index.md

Requirements:
    Dependencies are declared in the PEP 723 block above:
        uv run scrape_medium_blog.py <command> [options]
    Or: pip install requests beautifulsoup4 markdownify lxml

Usage:
    python scrape_medium_blog.py fetch                   # everything, newest first
    python scrape_medium_blog.py fetch --limit 5         # smoke test
    python scrape_medium_blog.py fetch --start 2024-12-31 --end 2024-01-01
    python scrape_medium_blog.py convert                 # raw -> posts/
    python scrape_medium_blog.py all --limit 5           # fetch then convert

Common options (fetch, convert, all):
    --out DIR         Archive root. Default: medium_export

fetch options:
    --base URL        Publication root; /sitemap/sitemap.xml and /feed must
                      resolve under it. Default: https://blog.jupyter.org/
    --urls FILE       Read post URLs from FILE (one per line, '#' comments)
                      instead of discovering them from sitemap + feed.
    --start DATE      Most recent publish date to include (YYYY-MM-DD or ISO
                      timestamp; a bare date includes the whole day). Fetching
                      proceeds backward in time from here. Default: now
    --end DATE        Oldest publish date to include. Default: no lower bound
    --oldest-first    Process from --end forward instead of --start backward.
    --limit N         Stop after fetching N new posts (already-fetched posts
                      do not count). 0 = no limit. Default: 0
    --existing DIR    Earlier archive(s) whose posts should be skipped
                      (raw/index.json, posts.json, or *.md with original_url).
                      Repeatable. The --out archive itself is always checked.
    --force           Re-fetch posts already in the raw archive.
    --delay SECONDS   Sleep between post requests; images sleep delay/4.
                      Raise to 2-3 s on 429s. Default: 1.5
    --no-images       Skip image downloads (convert will keep remote URLs).

convert options:
    --prefer-page     Always convert the page body. By default the RSS
                      <content:encoded> body is used when feed_item.json is
                      present, since it is cleaner HTML with proper code
                      blocks and full-resolution images.
    --only URL        Convert just this post (repeatable). Default: all.
    --clean           Delete <out>/posts/ before converting.

Notes:
  * Discovery: sitemap (complete archive) merged with the RSS feed (~10 most
    recent posts, with full bodies). Sitemap <lastmod> is a modification
    date; it orders and pre-filters, and the real publish date from each
    page is re-checked against --start/--end after fetching.
  * Redirects: front matter carries original_url, original_path (the path an
    old inbound link carries), medium_id (Medium also resolves /p/<id>) and
    slug; redirects.csv collects these for every converted post.
  * Medium's "was originally published in ... on Medium" footer and stat
    tracking pixels are removed. Embedded gists/iframes become links.
  * Medium rate-limits and may serve a bot wall; fetch is resumable.
Progress is written to stderr.
"""

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse, urlsplit, unquote

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
POST_ID_RE = re.compile(r"-([0-9a-f]{8,12})/?$")   # Medium post slugs end in a hex id
MIRO_RESIZE_RE = re.compile(r"/v2/(?:(?:resize|format|fill)[^/]*/)+")
MIRO_MAX_RE = re.compile(r"/max/\d+/")
MEDIUM_FOOTER_RE = re.compile(
    r"was originally published (in|on) .*Medium|"
    r"continuing the conversation by highlighting|"
    r"Continue reading on Medium",
    re.I,
)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


def fetch(session: requests.Session, url: str, retries: int = 4, **kw) -> requests.Response:
    backoff = 2.0
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} for {url}")
            r.raise_for_status()
            return r
        except (requests.RequestException, requests.HTTPError) as e:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1}/{retries - 1} after error: {e}", file=sys.stderr)
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def parse_date(text: str | None) -> datetime | None:
    """ISO-8601 (sitemap/JSON-LD) or RFC-2822 (RSS) -> aware UTC datetime."""
    if not text:
        return None
    text = text.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_cli_date(text: str, end_of_day: bool) -> datetime:
    dt = parse_date(text)
    if dt is None:
        raise argparse.ArgumentTypeError(f"unrecognised date: {text!r}")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def in_window(dt: datetime | None, start: datetime, end: datetime | None) -> bool:
    if dt is None:
        return True
    if dt > start:
        return False
    if end is not None and dt < end:
        return False
    return True


# --------------------------------------------------------------------------- #
# URLs and identifiers
# --------------------------------------------------------------------------- #
def canonical_url(url: str) -> str:
    return url.split("?")[0].split("#")[0].rstrip("/")


def medium_id(url: str) -> str | None:
    m = POST_ID_RE.search(urlparse(url).path)
    return m.group(1) if m else None


def slug_of(url: str) -> str:
    last = urlparse(url).path.strip("/").split("/")[-1]
    return POST_ID_RE.sub("", last)[:80] or "post"


def is_post_url(url: str, base_host: str) -> bool:
    p = urlparse(url)
    if p.netloc != base_host:
        return False
    if p.path.startswith(("/tagged/", "/search", "/archive", "/about", "/sitemap")):
        return False
    return bool(POST_ID_RE.search(p.path))


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
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


def discover(session, base: str, raw_dir: Path) -> tuple[list, dict]:
    """([(url, approx_date)], feed_items). Saves the feed XML to raw/feed.xml."""
    base_host = urlparse(base).netloc
    feed = {}
    try:
        xml_text = fetch(session, base.rstrip("/") + "/feed").text
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "feed.xml").write_text(xml_text, encoding="utf-8")
        feed = parse_feed(xml_text, base_host)
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


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
def original_image_url(url: str) -> str:
    """Strip Medium's resize/format path segments -> full-resolution asset."""
    url = url.split("?")[0]
    url = MIRO_RESIZE_RE.sub("/v2/", url)
    url = MIRO_MAX_RE.sub("/", url)
    return url


def largest_from_srcset(srcset: str) -> str | None:
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") else 0
        if w > best_w:
            best, best_w = bits[0], w
    return best


def image_source(img_tag) -> str | None:
    """Best source URL for an <img>, considering sibling <source> tags."""
    picture = img_tag.find_parent("picture")
    if picture:
        for src in picture.find_all("source"):
            if src.get("srcset"):
                u = largest_from_srcset(src["srcset"])
                if u:
                    return original_image_url(u)
    for attr in ("srcset", "data-srcset"):
        if img_tag.get(attr):
            u = largest_from_srcset(img_tag[attr])
            if u:
                return original_image_url(u)
    for attr in ("src", "data-src"):
        if img_tag.get(attr) and not img_tag[attr].startswith("data:"):
            return original_image_url(img_tag[attr])
    return None


def is_tracking_pixel(src: str) -> bool:
    return "medium.com/_/stat" in src or "/_/stat?" in src


def safe_filename(url: str, index: int) -> str:
    name = unquote(Path(urlsplit(url).path).name) or "image"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
    if "." not in name:
        name += ".bin"
    return f"{index:03d}-{name}"


def collect_image_urls(page_html: str, feed_item: dict | None) -> list:
    """All image URLs a conversion might need, from both the page body and
    the feed body, deduplicated in order of appearance."""
    urls = []
    sources = [BeautifulSoup(page_html, "html.parser")]
    if feed_item and feed_item.get("content_html"):
        sources.append(BeautifulSoup(feed_item["content_html"], "html.parser"))
    for soup in sources:
        root = soup.find("article") or soup
        for img in root.find_all("img"):
            src = image_source(img)
            if src and not is_tracking_pixel(src) and src not in urls:
                urls.append(src)
    return urls


# --------------------------------------------------------------------------- #
# Page parsing (shared by fetch for the date check, and by convert)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Archive README
# --------------------------------------------------------------------------- #
README_TEMPLATE = """\
# Medium archive of {base}

Generated by `{script}` on {date}. This directory is a self-contained
archive of the publication, intended to support migrating the blog off
Medium. It has two layers:

* `raw/` is the **source of truth**: material downloaded from Medium,
  unmodified. It is produced by `{script} fetch` and should be backed up.
  It is the only part that cannot be regenerated once the Medium site is
  gone.
* `posts/`, `posts.json` and `redirects.csv` are **derived**: produced by
  `{script} convert` from `raw/` alone, with no network access. They can
  be deleted and regenerated at any time (`convert --clean`), and are the
  layer to change when adapting the archive to a new site generator.

## Layout

```
README.md                     this file
raw/
  index.json                  every fetched post, keyed by its Medium URL:
                                medium_id, title, published (from the page),
                                sitemap_date, fetched_at, images, in_feed
  feed.xml                    the publication RSS feed as downloaded
  <medium_id>/                one directory per post (12-hex Medium id)
    page.html                 the post page, byte-for-byte as served
    feed_item.json            the post's RSS item, when the feed covered it
                                at fetch time (title, author, tags, date,
                                content_html). Only ~10 recent posts have one.
    images.json               {{source_url: filename}} for images/
    images/<filename>         full-resolution images referenced by the post
posts.json                    converted posts, keyed by Medium URL; same
                                fields as each post's front matter plus `dir`
redirects.csv                 original_path, medium_id, original_url,
                                new_dir, date, title -- one row per post
posts/
  <YYYY-MM-DD>-<slug>/        one directory per converted post
    index.md                  front matter + Markdown body
    images/<filename>         images copied from raw/, referenced relatively
```

## Front matter (posts/*/index.md)

The front matter block between `---` lines is JSON, which is valid YAML.

| field           | meaning |
|-----------------|---------|
| `title`         | post title |
| `author`        | author display name (JSON-LD, or RSS `dc:creator`) |
| `author_url`    | author profile URL on Medium, if present |
| `date`          | publish timestamp (ISO 8601, UTC) |
| `updated`       | last-modified timestamp, if present |
| `original_url`  | canonical Medium URL of the post |
| `original_path` | path component of `original_url`; what an old inbound link carries |
| `medium_id`     | Medium's hex post id; Medium also resolves `/p/<id>` |
| `slug`          | `original_path` with the id suffix removed |
| `description`   | Medium's summary/description text |
| `tags`          | tags (RSS categories when available, else scraped tag links) |
| `images`        | relative paths of images used by the body |
| `body_source`   | `feed` (RSS `content:encoded`) or `page` (rendered HTML) |

## Redirects

`redirects.csv` has everything needed to map old Medium URLs to the new
site once its URL scheme is decided. Inbound links to Medium posts may use
the full slug+id path (`original_path`) or the short form `/p/<medium_id>`;
both should be redirected.

## Conventions and caveats

* Bodies are Markdown produced by markdownify from Medium HTML. Code
  blocks, lists and headings are generally fine; tables and embeds are
  not: gists and other iframes appear as `[embed: <url>]` links and need
  manual replacement.
* Medium boilerplate ("was originally published in ... on Medium", stat
  tracking pixels, clap/share UI, author header) is stripped in `convert`.
  It is still present in `raw/page.html`.
* `body_source: feed` posts are usually cleaner than `page` posts. Medium
  only exposes feed bodies for recent posts, so most of the archive is
  `page`. Review `page` posts for leftover chrome.
* Links inside bodies that point at other posts in this publication still
  point at Medium; rewrite them using `redirects.csv` when migrating.
* Image filenames are `<NNN>-<original basename>`; the same asset served
  from `miro.medium.com` and `cdn-images-1.medium.com` is stored once.

## Regenerating

    uv run {script} --out {out} fetch              # incremental; add new posts
    uv run {script} --out {out} convert --clean    # rebuild posts/ from raw/
"""


def write_readme(out: Path, base: str):
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text(README_TEMPLATE.format(
        base=base.rstrip("/"),
        script=Path(sys.argv[0]).name or "scrape_medium_blog.py",
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        out=out,
    ), encoding="utf-8")


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
def load_existing(dirs: list) -> set:
    """Medium URLs already archived elsewhere (raw/index.json, posts.json,
    or *.md with an original_url front-matter line)."""
    urls = set()
    pat = re.compile(r'["\']?original_url["\']?\s*:\s*["\']?(https?://[^\s"\',]+)')
    for d in dirs:
        d = Path(d).expanduser()
        if not d.is_dir():
            print(f"warning: --existing {d} not found, ignoring", file=sys.stderr)
            continue
        for name in ("index.json", "posts.json"):
            for mf in d.rglob(name):
                try:
                    urls.update(canonical_url(k) for k in json.loads(mf.read_text()))
                except (OSError, json.JSONDecodeError, AttributeError):
                    pass
        for md in d.rglob("*.md"):
            try:
                head = md.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            urls.update(canonical_url(m.group(1)) for m in pat.finditer(head))
    return urls


def read_index(raw_dir: Path) -> dict:
    p = raw_dir / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


def write_index(raw_dir: Path, index: dict):
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))


def fetch_post(session, url: str, dest: Path, feed_item: dict | None,
               delay: float, images: bool) -> dict:
    """Save page.html, feed_item.json, images/ and images.json into dest."""
    r = fetch(session, url)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "page.html").write_text(r.text, encoding="utf-8")
    if feed_item:
        (dest / "feed_item.json").write_text(json.dumps(feed_item, indent=2, ensure_ascii=False))

    img_map = {}
    if images:
        img_dir = dest / "images"
        by_basename = {}   # the same asset appears as miro.medium.com/v2/<id> and cdn-images-1.medium.com/<id>
        for i, src in enumerate(collect_image_urls(r.text, feed_item), start=1):
            base = Path(urlsplit(src).path).name
            if base in by_basename:
                img_map[src] = by_basename[base]
                continue
            fname = safe_filename(src, i)
            if (img_dir / fname).exists():
                img_map[src] = by_basename[base] = fname
                continue
            try:
                resp = fetch(session, src, stream=True)
                img_dir.mkdir(parents=True, exist_ok=True)
                with open(img_dir / fname, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        fh.write(chunk)
                img_map[src] = by_basename[base] = fname
                time.sleep(delay / 4)
            except Exception as e:
                print(f"  image failed {src}: {e}", file=sys.stderr)
        (dest / "images.json").write_text(json.dumps(img_map, indent=2))

    info = extract_metadata(BeautifulSoup(r.text, "html.parser"), url)
    return {"published": info["date"], "title": info["title"], "image_count": len(img_map)}


def cmd_fetch(args):
    raw_dir = args.out / "raw"
    start = args.start or datetime.now(timezone.utc)
    end = args.end
    if end is not None and end > start:
        sys.exit("--end must not be later than --start")

    session = make_session()
    base_host = urlparse(args.base).netloc
    feed = {}
    if args.urls:
        lines = [l.strip() for l in args.urls.read_text().splitlines()]
        entries = [(canonical_url(l), None) for l in lines if l and not l.startswith("#")]
        try:
            xml_text = fetch(session, args.base.rstrip("/") + "/feed").text
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "feed.xml").write_text(xml_text, encoding="utf-8")
            feed = parse_feed(xml_text, base_host)
        except Exception:
            pass
    else:
        entries, feed = discover(session, args.base, raw_dir)

    entries = [e for e in entries if in_window(e[1], start, end)]
    dated = sorted((e for e in entries if e[1] is not None), key=lambda e: e[1],
                   reverse=not args.oldest_first)
    entries = dated + [e for e in entries if e[1] is None]
    direction = "oldest -> newest" if args.oldest_first else "newest -> oldest"
    print(f"{len(entries)} candidate posts, {direction}, start={start:%Y-%m-%d}"
          f"{'' if end is None else f', end={end:%Y-%m-%d}'}", file=sys.stderr)

    index = read_index(raw_dir)
    skip = set(index) | load_existing(args.existing or [])
    fetched = 0
    for n, (url, approx) in enumerate(entries, 1):
        if args.limit and fetched >= args.limit:
            print(f"reached --limit {args.limit}", file=sys.stderr)
            break
        if url in skip and not args.force:
            continue
        pid = medium_id(url) or re.sub(r"[^A-Za-z0-9]", "_", url)[-40:]
        dest = raw_dir / pid
        tmp = raw_dir / f"_tmp_{pid}"
        print(f"[{n}/{len(entries)}] {url}", file=sys.stderr)
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            info = fetch_post(session, url, tmp, feed.get(url), args.delay, not args.no_images)
            if not in_window(parse_date(info["published"]), start, end):
                print(f"  skipped: published {info['published']} is outside window", file=sys.stderr)
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            if dest.exists():
                shutil.rmtree(dest)
            tmp.rename(dest)
            index[url] = {
                "medium_id": pid,
                "title": info["title"],
                "published": info["published"],
                "sitemap_date": approx.isoformat() if approx else None,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "images": info["image_count"],
                "in_feed": url in feed,
            }
            write_index(raw_dir, index)
            fetched += 1
        except Exception as e:
            print(f"  FAILED {url}: {e}", file=sys.stderr)
            shutil.rmtree(tmp, ignore_errors=True)
        time.sleep(args.delay)
    write_readme(args.out, args.base)
    print(f"fetch done: {fetched} new, {len(index)} total in {raw_dir}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# convert
# --------------------------------------------------------------------------- #
def convert_post(url: str, raw: Path, posts_root: Path, prefer_page: bool) -> dict:
    page_html = (raw / "page.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(page_html, "html.parser")
    info = extract_metadata(soup, url)

    feed_item = None
    if (raw / "feed_item.json").exists():
        feed_item = json.loads((raw / "feed_item.json").read_text())
        info["author"] = info["author"] or feed_item.get("author", "")
        info["title"] = info["title"] or feed_item.get("title", "")
        if feed_item.get("tags"):
            info["tags"] = feed_item["tags"]
        if not info["date"] and feed_item.get("date"):
            d = parse_date(feed_item["date"])
            info["date"] = d.isoformat() if d else ""

    img_map = {}
    if (raw / "images.json").exists():
        img_map = json.loads((raw / "images.json").read_text())

    if feed_item and feed_item.get("content_html") and not prefer_page:
        body, body_source = feed_body(feed_item["content_html"]), "feed"
    else:
        body, body_source = page_body(soup), "page"
    doc = body if body.parent is None else soup   # owner for new_tag()

    out_dir = posts_root / f"{(info['date'] or '')[:10] or 'undated'}-{slug_of(url)}"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    used_images = []
    for img in body.find_all("img"):
        src = image_source(img)
        if not src:
            img.decompose()
            continue
        fname = img_map.get(src)
        if fname and (raw / "images" / fname).exists():
            (out_dir / "images").mkdir(exist_ok=True)
            shutil.copy2(raw / "images" / fname, out_dir / "images" / fname)
            local = f"images/{fname}"
            used_images.append(local)
        else:
            local = src                         # not downloaded; keep remote URL
        new_img = doc.new_tag("img", src=local, alt=img.get("alt", ""))
        picture = img.find_parent("picture")
        (picture or img).replace_with(new_img)

    for iframe in body.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        iframe.replace_with(doc.new_tag("a", href=src, string=f"[embed: {src}]"))

    markdown = html_to_md(str(body), heading_style="ATX", bullets="-", strip=["span"])
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    markdown = re.sub(r"(?:\n-{3,}\n)?\n[^\n]*was originally published[^\n]*\n*$", "\n", markdown)
    if "Continue reading on" in markdown and len(markdown) < 2000:
        print("  warning: body looks truncated", file=sys.stderr)
    if len(markdown) < 200:
        print(f"  warning: body is only {len(markdown)} chars; check selectors", file=sys.stderr)

    canon = canonical_url(info["url"])
    front = {
        "title": info["title"],
        "author": info["author"],
        "author_url": info["author_url"],
        "date": info["date"],
        "updated": info["updated"],
        "original_url": canon,
        "original_path": urlparse(canon).path,
        "medium_id": medium_id(canon),
        "slug": slug_of(canon),
        "description": info["description"],
        "tags": sorted(set(info["tags"])),
        "images": used_images,
        "body_source": body_source,
    }
    with open(out_dir / "index.md", "w", encoding="utf-8") as fh:
        fh.write("---\n")
        fh.write(json.dumps(front, indent=2, ensure_ascii=False))   # JSON is valid YAML
        fh.write("\n---\n\n")
        fh.write(markdown)
    return {**front, "dir": str(out_dir.relative_to(posts_root.parent))}


def write_redirects(manifest: dict, out: Path):
    def q(v):
        v = "" if v is None else str(v)
        return '"' + v.replace('"', '""') + '"' if any(c in v for c in ',"\n') else v
    rows = ["original_path,medium_id,original_url,new_dir,date,title"]
    for url, p in sorted(manifest.items(), key=lambda kv: kv[1].get("date") or ""):
        rows.append(",".join(q(x) for x in (
            p.get("original_path"), p.get("medium_id"), url, Path(p["dir"]).name,
            (p.get("date") or "")[:10], p.get("title"))))
    (out / "redirects.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def cmd_convert(args):
    raw_dir = args.out / "raw"
    index = read_index(raw_dir)
    if not index:
        sys.exit(f"nothing to convert: {raw_dir}/index.json missing or empty (run fetch first)")
    posts_root = args.out / "posts"
    if args.clean:
        shutil.rmtree(posts_root, ignore_errors=True)
    manifest_path = args.out / "posts.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() and not args.clean else {}

    targets = [canonical_url(u) for u in args.only] if args.only else list(index)
    ok = 0
    for n, url in enumerate(targets, 1):
        entry = index.get(url)
        if not entry:
            print(f"[{n}/{len(targets)}] not in raw archive: {url}", file=sys.stderr)
            continue
        raw = raw_dir / entry["medium_id"]
        print(f"[{n}/{len(targets)}] {url}", file=sys.stderr)
        try:
            manifest[url] = convert_post(url, raw, posts_root, args.prefer_page)
            ok += 1
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    if manifest:
        write_redirects(manifest, args.out)
    if not (args.out / "README.md").exists():
        write_readme(args.out, getattr(args, "base", "https://blog.jupyter.org/"))
    print(f"convert done: {ok}/{len(targets)} posts -> {posts_root}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_fetch_args(p):
    p.add_argument("--base", default="https://blog.jupyter.org/")
    p.add_argument("--urls", type=Path)
    p.add_argument("--start", type=lambda t: parse_cli_date(t, True), default=None)
    p.add_argument("--end", type=lambda t: parse_cli_date(t, False), default=None)
    p.add_argument("--oldest-first", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--existing", action="append", metavar="DIR")
    p.add_argument("--force", action="store_true")
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--no-images", action="store_true")


def add_convert_args(p):
    p.add_argument("--prefer-page", action="store_true")
    p.add_argument("--only", action="append", metavar="URL")
    p.add_argument("--clean", action="store_true")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="medium_export", type=Path)
    sub = ap.add_subparsers(dest="command", required=True)
    add_fetch_args(sub.add_parser("fetch", help="download raw material into <out>/raw/"))
    add_convert_args(sub.add_parser("convert", help="convert <out>/raw/ into <out>/posts/"))
    both = sub.add_parser("all", help="fetch then convert")
    add_fetch_args(both)
    add_convert_args(both)
    args = ap.parse_args()

    if args.command in ("fetch", "all"):
        cmd_fetch(args)
    if args.command in ("convert", "all"):
        cmd_convert(args)


if __name__ == "__main__":
    main()
