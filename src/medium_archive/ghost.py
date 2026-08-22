"""The import-ghost step: recover a Ghost blog's posts from the Wayback
Machine into <out>/raw/.

A separate import path from `fetch`: fetch handles Medium URLs (hex-id
slugs) from the live site, while this step handles Ghost URLs -- often a
publication's former or parallel home on the same domain, surviving only
as web.archive.org captures. It scans the Wayback CDX index for every page
ever captured on the blog host, fetches candidate snapshots, and keeps the
ones that are Ghost post pages -- identified by the page's own
<meta name="generator" content="Ghost ..."> tag, so it works for any Ghost
site and version, with no assumptions about permalink style.

A post that also exists on Medium (it was migrated between the platforms,
recognized by slug or title) gets its Ghost capture attached to the
archived post's directory as ghost.html + ghost.json, alongside page.html
-- like import-export attaches export.html. The Ghost source is often
cleaner (real code blocks, the exact original timestamp, the original
URL for redirects), and `convert --prefer-ghost` can use it as the body.
Posts with no archived counterpart are imported as posts of their own.
"""

import json
import sys
import time
from datetime import datetime, timezone
from hashlib import md5
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import read_index, write_index
from .images import image_source, safe_filename
from .net import fetch, make_session
from .pages import ghost_body, ghost_metadata, is_ghost_page, meta
from .readme import write_readme
from .urls import POST_ID_RE, canonical_url, norm_key, slug_of

WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
# id_ returns the capture byte-for-byte as crawled, without the Wayback
# toolbar or rewritten links; im_ resolves to the nearest image capture.
SNAPSHOT = "https://web.archive.org/web/{ts}id_/{url}"
IMAGE_SNAPSHOT = "https://web.archive.org/web/{ts}im_/{url}"
MAX_SNAPSHOT_TRIES = 4

NON_POST_PREFIXES = (
    "/tag/", "/tagged/", "/author/", "/page/", "/rss", "/feed",
    "/assets/", "/content/", "/public/", "/ghost/", "/sitemap",
    "/cdn-cgi/", "/search", "/about", "/archive", "/wp-",
    "/p/", "/m/", "/@",     # Medium-era paths on the same host
)


def may_be_post(path: str) -> bool:
    """Cheap pre-filter on the URL path alone; the fetched page's generator
    meta tag is the real test. Medium-style URLs (hex id suffix) are a
    different import path -- fetch's, from the live site."""
    if path.rstrip("/") == "":
        return False
    if path.startswith(NON_POST_PREFIXES):
        return False
    if path.rstrip("/").endswith("/amp"):
        return False
    if "." in path.rstrip("/").split("/")[-1]:      # favicon.ico, *.xml, ...
        return False
    return not POST_ID_RE.search(path)


def ghost_captures(session, base: str) -> dict:
    """{url: [timestamp, ...]} for every candidate post page the Wayback
    Machine captured successfully on the publication host, timestamps
    newest first."""
    p = urlparse(base)
    captures, resume = {}, None
    while True:
        query = urlencode({
            "url": p.netloc + "/*",
            "fl": "original,timestamp",
            "filter": "statuscode:200",
            "collapse": "digest",     # drop consecutive identical captures
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
            path = urlparse(original).path
            if not may_be_post(path):
                continue
            u = canonical_url(f"{p.scheme}://{p.netloc}{path}")
            captures.setdefault(u, []).append(ts)
        if not resume:
            break
        time.sleep(1)
    for ts_list in captures.values():
        ts_list.sort(reverse=True)
    return captures


def url_captures(session, url: str) -> list:
    """Capture timestamps for one URL, newest first (for --urls seeds)."""
    query = urlencode({"url": url, "fl": "timestamp",
                       "filter": "statuscode:200", "collapse": "digest",
                       "limit": 100})
    lines = fetch(session, f"{WAYBACK_CDX}?{query}").text.splitlines()
    return sorted((l.strip() for l in lines if l.strip()), reverse=True)


def is_ghost_post(soup) -> bool:
    """A Ghost-generated page that is a post (not the front page or a tag/
    author index): Ghost emits og:type article only on post pages."""
    return is_ghost_page(soup) and meta(soup, property="og:type") == "article"


def fetch_snapshot(session, url: str, timestamps: list):
    """The newest capture of `url` that is a Ghost post page, as
    (timestamp, html, soup); (None, None, None) if none of the tried
    captures qualifies (e.g. only Medium-era captures of the path exist)."""
    for ts in timestamps[:MAX_SNAPSHOT_TRIES]:
        try:
            html = fetch(session, SNAPSHOT.format(ts=ts, url=url)).text
        except Exception as e:
            print(f"  snapshot {ts} failed: {e}", file=sys.stderr)
            continue
        soup = BeautifulSoup(html, "html.parser")
        if is_ghost_post(soup):
            return ts, html, soup
    return None, None, None


def fetch_images(session, body, base_url: str, ts: str, dest, delay: float,
                 prefix: str = "") -> dict:
    """Download the body's images from the Wayback Machine into dest/images/.
    Returns {src_as_in_page: filename} (absolute URLs added as aliases).
    `prefix` keeps attached Ghost images from colliding with the post's
    Medium images, which are numbered from 001- too."""
    img_map = {}
    img_dir = dest / "images"
    for i, img in enumerate(body.find_all("img"), start=1):
        src = image_source(img)
        if not src or src in img_map:
            continue
        absolute = urljoin(base_url, src)
        fname = prefix + safe_filename(absolute, i)
        if (img_dir / fname).exists():       # picked up on a --force re-run
            img_map[src] = img_map[absolute] = fname
            continue
        try:
            resp = fetch(session, IMAGE_SNAPSHOT.format(ts=ts, url=absolute), stream=True)
            img_dir.mkdir(parents=True, exist_ok=True)
            with open(img_dir / fname, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)
            img_map[src] = img_map[absolute] = fname
            time.sleep(delay / 4)
        except Exception as e:
            print(f"  image failed {absolute}: {e}", file=sys.stderr)
    return img_map


def medium_twin(url: str, index: dict) -> str | None:
    """The archived Medium URL this Ghost URL was migrated as, if the slugs
    match: the Medium slug is the Ghost slug plus the hex post id."""
    k = norm_key(url)
    return next((u for u in index
                 if norm_key(u) != k and norm_key(u).startswith(k)
                 and 8 <= len(norm_key(u)) - len(k) <= 12), None)


def ghost_pid(url: str, index: dict) -> str:
    """Directory name under raw/ (Ghost posts have no Medium id)."""
    pid = "ghost-" + slug_of(url)
    taken = {e.get("medium_id") for u, e in index.items() if u != url}
    if pid in taken:
        pid += "-" + md5(url.encode()).hexdigest()[:6]
    return pid


def ghost_provenance(url: str, ts: str, soup, info: dict) -> dict:
    """The ghost.json contents: where the capture came from, plus the Ghost
    page's own title and timestamp -- Medium migrations sometimes retitle
    posts and shift their publish dates."""
    return {
        "original_url": url,
        "snapshot_timestamp": ts,
        "wayback_url": f"https://web.archive.org/web/{ts}/{url}",
        "generator": meta(soup, name="generator"),
        "title": info["title"],
        "published": info["date"],
    }


def attach_ghost(session, raw_dir, index, twin: str, url: str, ts: str,
                 html: str, soup, info: dict, args):
    """Save the Ghost capture into the archived twin's directory, alongside
    the Medium page, and mark the index entry -- mirroring how
    import-export attaches export.html."""
    dest = raw_dir / index[twin]["medium_id"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "ghost.html").write_text(html, encoding="utf-8")
    (dest / "ghost.json").write_text(json.dumps(ghost_provenance(url, ts, soup, info),
                                                indent=2, ensure_ascii=False))
    if not args.no_images:
        body = ghost_body(BeautifulSoup(html, "html.parser"))
        img_map = fetch_images(session, body, url, ts, dest, args.delay, prefix="g")
        if img_map:
            merged = {}
            if (dest / "images.json").exists():
                merged = json.loads((dest / "images.json").read_text())
            merged.update(img_map)
            (dest / "images.json").write_text(json.dumps(merged, indent=2))
    index[twin].update({
        "in_ghost": True,
        "ghost_url": url,
        "ghost_imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    write_index(raw_dir, index)


def import_standalone(session, raw_dir, index, url: str, ts: str, html: str,
                      soup, info: dict, args):
    """Save the Ghost capture as a post of its own under raw/ghost-<slug>/."""
    pid = ghost_pid(url, index)
    dest = raw_dir / pid
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "page.html").write_text(html, encoding="utf-8")
    (dest / "ghost.json").write_text(json.dumps(ghost_provenance(url, ts, soup, info),
                                                indent=2, ensure_ascii=False))
    img_map = {}
    if not args.no_images:
        body = ghost_body(BeautifulSoup(html, "html.parser"))
        img_map = fetch_images(session, body, url, ts, dest, args.delay)
        (dest / "images.json").write_text(json.dumps(img_map, indent=2))
    index[url] = {
        "medium_id": pid,
        "title": info["title"],
        "published": info["date"],
        "sitemap_date": None,
        "found_via": "ghost-wayback",
        "wayback_url": f"https://web.archive.org/web/{ts}/{url}",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "images": len(set(img_map.values())),
        "in_feed": False,
    }
    write_index(raw_dir, index)


def cmd_import_ghost(args):
    raw_dir = args.out / "raw"
    session = make_session()
    index = read_index(raw_dir)

    if args.urls:
        lines = [l.strip() for l in args.urls.read_text().splitlines()]
        seeds = [canonical_url(l) for l in lines if l and not l.startswith("#")]
        captures = {}
        for u in seeds:
            captures[u] = url_captures(session, u)
            time.sleep(args.delay)
    else:
        captures = ghost_captures(session, args.base)
    print(f"wayback: {len(captures)} candidate URLs on "
          f"{urlparse(args.base).netloc}", file=sys.stderr)

    titles = {(e.get("title") or "").casefold(): u
              for u, e in index.items() if e.get("title")}
    attached_urls = {e["ghost_url"] for e in index.values() if e.get("ghost_url")}
    imported = attached = 0
    for n, (url, timestamps) in enumerate(sorted(captures.items()), 1):
        if args.limit and imported + attached >= args.limit:
            print(f"reached --limit {args.limit}", file=sys.stderr)
            break
        if (url in index or url in attached_urls) and not args.force:
            continue
        twin = medium_twin(url, index)
        if twin and index[twin].get("in_ghost") and not args.force:
            continue
        print(f"[{n}/{len(captures)}] {url}", file=sys.stderr)
        ts, html, soup = fetch_snapshot(session, url, timestamps)
        if ts is None:
            print("  no Ghost post capture; skipping", file=sys.stderr)
            time.sleep(args.delay)
            continue
        info = ghost_metadata(soup, url)
        if twin is None:
            twin = titles.get(info["title"].casefold())
            if twin and index[twin].get("found_via") == "ghost-wayback":
                # another URL of a Ghost post already imported (a repost,
                # or a URL variant) -- a duplicate, not a migration twin
                print(f"  duplicate of ghost post {twin} (title match); "
                      f"skipping", file=sys.stderr)
                time.sleep(args.delay)
                continue
            if twin and index[twin].get("in_ghost") and not args.force:
                time.sleep(args.delay)
                continue
        if twin:
            attach_ghost(session, raw_dir, index, twin, url, ts, html, soup, info, args)
            attached_urls.add(url)
            attached += 1
            print(f"  attached as ghost.html to {twin}", file=sys.stderr)
        else:
            import_standalone(session, raw_dir, index, url, ts, html, soup, info, args)
            titles[info["title"].casefold()] = url
            imported += 1
        time.sleep(args.delay)

    write_readme(args.out, args.base)
    print(f"import-ghost done: {imported} new posts, {attached} attached to "
          f"archived posts, {len(index)} total in {raw_dir}", file=sys.stderr)
