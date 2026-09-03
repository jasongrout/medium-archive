"""The fetch step: pull raw material from Medium into <out>/raw/.

Incremental and resumable; the raw archive is the source of truth that
convert works from.
"""

import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .dates import in_window, parse_date
from .discovery import discover, fetch_feed
from .images import (collect_image_urls, giphy_media, safe_filename,
                     same_medium_asset)
from .state import (state_embed_targets, state_image_urls,
                    state_media_resources)
from .net import fetch, make_session
from .pages import extract_metadata
from .readme import write_readme
from .urls import (canonical_url, carbon_id, medium_id, norm_key, slug_of,
                   tweet_id)


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


def archive_base(out: Path) -> str | None:
    """The publication root derived from archived post URLs, for the
    offline steps, which do not take the URL argument."""
    hosts = Counter()
    for url in read_index(out / "raw"):
        p = urlsplit(url)
        if p.scheme and p.netloc:
            hosts[f"{p.scheme}://{p.netloc}"] += 1
    return hosts.most_common(1)[0][0] if hosts else None


def write_index(raw_dir: Path, index: dict):
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))


def read_missing(raw_dir: Path) -> dict:
    p = raw_dir / "missing.json"
    return json.loads(p.read_text()) if p.exists() else {}


def write_missing(raw_dir: Path, missing: dict):
    """raw/missing.json: posts discovery found but Medium no longer serves."""
    p = raw_dir / "missing.json"
    if missing:
        raw_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(missing, indent=2, ensure_ascii=False))
    elif p.exists():
        p.unlink()


class PostGone(Exception):
    """The URL no longer resolves to a post on Medium."""
    def __init__(self, status):
        super().__init__(str(status))
        self.status = status


def looks_gone(html: str) -> bool:
    """Medium serves its PAGE NOT FOUND page with HTTP 200 (behind
    Cloudflare, to a browser user-agent), so a status check alone misses
    deleted posts. Real post pages always carry an ld+json metadata block;
    the not-found page has none."""
    return "ld+json" not in html and "PAGE NOT FOUND" in html


MEDIA_URL = "https://medium.com/media/{id}?format=json"
GIST_API_URL = "https://api.github.com/gists/{id}"
# X's public oEmbed endpoint (publish.twitter.com redirects here since
# the rename): the tweet's text, author and date as HTML, no
# credentials needed, checked live 2026-09. omit_script drops the
# widgets.js tag; dnt asks for no tracking of the archive's readers.
TWEET_OEMBED_URL = ("https://publish.x.com/oembed?url={url}"
                    "&omit_script=true&dnt=true")
# A Carbon snippet's embed page is a Next.js page whose server-rendered
# data carries the snippet itself: its code and language, which the
# screenshot the iframe would show is drawn from.
CARBON_EMBED_URL = "https://carbon.now.sh/embed/{id}"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def fetch_media(session, page_text: str, mid: str, dest: Path,
                delay: float) -> int:
    """Archive the media resources the page's embedded state leaves
    unresolved (an empty iframeSrc -- gist embeds, mostly; their content
    exists nowhere in the page itself): the medium.com/media payload
    that names the embed's target into dest/media/<id>.json, and for a
    gist also its files, from the GitHub API, into <id>.gist.json. And
    for each tweet embed, whose text is likewise nowhere in the page,
    the tweet's oEmbed payload into tweet-<tweet id>.json. Incremental
    -- files already on disk are not re-fetched, so a re-run of fetch
    backfills posts archived before this existed. Returns the number of
    files written."""
    n = fetch_tweets(session, page_text, mid, dest, delay)
    n += fetch_carbon(session, page_text, mid, dest, delay)
    for res_id in state_media_resources(page_text, mid):
        media_path = dest / "media" / f"{res_id}.json"
        payload = None
        if media_path.exists():
            try:
                payload = json.loads(media_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass                     # unreadable: re-fetch it
        if payload is None:
            try:
                r = fetch(session, MEDIA_URL.format(id=res_id))
                # the JSON sits behind Medium's anti-hijacking prefix
                # (`])}while(1);</x>`)
                payload = json.loads(r.text[r.text.index("{"):])
            except Exception as e:
                print(f"  media resource failed {res_id}: {e}", file=sys.stderr)
                continue
            media_path.parent.mkdir(parents=True, exist_ok=True)
            media_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
            n += 1
            time.sleep(delay / 4)
        gist = ((payload.get("payload") or {}).get("value") or {}).get("gist") or {}
        gist_path = dest / "media" / f"{res_id}.gist.json"
        if gist.get("gistId") and not gist_path.exists():
            try:
                r = fetch(session, GIST_API_URL.format(id=gist["gistId"]))
                gist_path.write_text(r.text, encoding="utf-8")
                n += 1
                time.sleep(delay / 4)
            except Exception as e:
                print(f"  gist failed {gist['gistId']}: {e}", file=sys.stderr)
    return n


def fetch_tweets(session, page_text: str, mid: str, dest: Path,
                 delay: float) -> int:
    """The oEmbed payload of every tweet the page's embeds target, into
    dest/media/tweet-<id>.json; a deleted tweet (the endpoint answers
    404) is reported and stays a link. Incremental."""
    n = 0
    for target, _ in state_embed_targets(page_text, mid):
        tweet = tweet_id(target)
        if not tweet:
            continue
        path = dest / "media" / f"tweet-{tweet[0]}.json"
        if path.exists():
            continue
        try:
            r = fetch(session, TWEET_OEMBED_URL.format(url=target))
            payload = json.loads(r.text)
        except Exception as e:
            print(f"  tweet failed {target}: {e}", file=sys.stderr)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        n += 1
        time.sleep(delay / 4)
    return n


def carbon_snippet(page_html: str) -> dict | None:
    """The snippet (id, code, language, ...) from a Carbon embed page's
    __NEXT_DATA__, else None."""
    m = NEXT_DATA_RE.search(page_html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    snippet = ((data.get("props") or {}).get("pageProps") or {}).get("snippet")
    return snippet if snippet and snippet.get("code") is not None else None


def fetch_carbon(session, page_text: str, mid: str, dest: Path,
                 delay: float) -> int:
    """The snippet behind every Carbon embed the page targets, into
    dest/media/carbon-<id>.json, so convert can write the code itself
    instead of an iframe of its screenshot. Incremental."""
    n = 0
    for target, _ in state_embed_targets(page_text, mid):
        cid = carbon_id(target)
        if not cid:
            continue
        path = dest / "media" / f"carbon-{cid}.json"
        if path.exists():
            continue
        try:
            r = fetch(session, CARBON_EMBED_URL.format(id=cid))
            snippet = carbon_snippet(r.text)
            if snippet is None:
                raise ValueError("no snippet in the embed page's __NEXT_DATA__")
        except Exception as e:
            print(f"  carbon snippet failed {target}: {e}", file=sys.stderr)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snippet, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        n += 1
        time.sleep(delay / 4)
    return n


def embed_asset_urls(page_text: str, mid: str) -> list:
    """Media files behind the page's embeds that the archive can hold
    itself -- Giphy gifs and mp4s -- so convert can serve them as local
    images and videos instead of a link to a third party."""
    urls = []
    for target, _ in state_embed_targets(page_text, mid):
        media = giphy_media(target)
        if media and media not in urls:
            urls.append(media)
    return urls


def fetch_images(session, srcs: list, img_dir: Path, img_map: dict,
                 delay: float, start: int = 1) -> int:
    """Download srcs into img_dir, recording url -> filename in img_map
    (files already on disk are mapped, not re-fetched); returns the
    number fetched. Filenames are numbered from start."""
    n = 0
    by_basename = {}   # the same asset appears as miro.medium.com/v2/<id> and cdn-images-1.medium.com/<id>
    for i, src in enumerate(srcs, start=start):
        # only Medium's own assets share a file across hosts; anything
        # else (a Giphy clip, always giphy.mp4) is keyed by its full URL
        base = Path(urlsplit(src).path).name if same_medium_asset(src) else src
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
            n += 1
            time.sleep(delay / 4)
        except Exception as e:
            print(f"  image failed {src}: {e}", file=sys.stderr)
    return n


def backfill_embed_assets(session, page_text: str, mid: str, dest: Path,
                          delay: float) -> int:
    """For a post archived before embed assets were fetched: download
    the Giphy files its embeds name into dest/images/ and add them to
    images.json, without touching anything already there. Returns the
    number fetched."""
    map_path = dest / "images.json"
    img_map = {}
    if map_path.exists():
        try:
            img_map = json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
    missing = [u for u in embed_asset_urls(page_text, mid) if u not in img_map]
    if not missing:
        return 0
    n = fetch_images(session, missing, dest / "images", img_map, delay,
                     start=len(img_map) + 1)
    map_path.write_text(json.dumps(img_map, indent=2))
    return n


def fetch_post(session, url: str, dest: Path, feed_item: dict | None,
               delay: float, images: bool) -> dict:
    """Save page.html, feed_item.json, media/, images/ and images.json
    into dest."""
    r = fetch(session, url)
    if looks_gone(r.text):
        raise PostGone("soft-404")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "page.html").write_text(r.text, encoding="utf-8")
    if feed_item:
        (dest / "feed_item.json").write_text(json.dumps(feed_item, indent=2, ensure_ascii=False))
    media_count = fetch_media(session, r.text, medium_id(url) or "", dest, delay)

    img_map = {}
    if images:
        img_dir = dest / "images"
        srcs = collect_image_urls(r.text, feed_item)
        # a shell capture renders no <img> tags; its editor state still names the images
        srcs += [u for u in state_image_urls(r.text, medium_id(url) or "")
                 if u not in srcs]
        # the media files behind embeds (Giphy), served locally by convert
        srcs += [u for u in embed_asset_urls(r.text, medium_id(url) or "")
                 if u not in srcs]
        fetch_images(session, srcs, img_dir, img_map, delay)
        (dest / "images.json").write_text(json.dumps(img_map, indent=2))

    info = extract_metadata(BeautifulSoup(r.text, "html.parser"), url)
    return {"published": info["date"], "title": info["title"],
            "image_count": len(img_map), "media_count": media_count}


MEDIUM_ID_RE = re.compile(r"^[0-9a-f]{8,12}$")


def resolve_post_ref(line: str, out: Path, index: dict) -> str:
    """The archived URL a --urls line refers to, when it names an
    archived post rather than a URL: a Medium id, or a converted post's
    directory name as lint and stats print it (with or without a
    posts/ prefix). Anything else is a URL and comes back as it is. A
    name that resolves nowhere comes back unchanged too, so the
    soft-404 it then earns says what happened."""
    ref = line.strip().rstrip("/")
    if "://" in ref:
        return ref
    if MEDIUM_ID_RE.match(ref):
        for url, entry in index.items():
            if entry.get("medium_id") == ref:
                return url
        return ref
    name = ref.split("/")[-1]
    md = out / "posts" / name / "index.md"
    if md.is_file():
        text = md.read_text(encoding="utf-8")
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        try:
            front = json.loads(m.group(1)) if m else {}
        except json.JSONDecodeError:
            front = {}
        if front.get("original_url"):
            return front["original_url"]
        for url, entry in index.items():
            if entry.get("medium_id") == front.get("medium_id"):
                return url
    return ref


def cmd_fetch(args):
    raw_dir = args.out / "raw"
    start = args.start or datetime.now(timezone.utc)
    end = args.end
    if end is not None and end > start:
        sys.exit("--end must not be later than --start")

    session = make_session()
    feed = {}
    if args.urls:
        lines = [l.strip() for l in args.urls.read_text().splitlines()]
        # a line may name an archived post instead of a URL (its Medium
        # id, or the posts/ directory name lint prints)
        known = read_index(raw_dir)
        entries = [(canonical_url(resolve_post_ref(l, args.out, known)), None, "file")
                   for l in lines if l and not l.startswith("#")]
        try:
            feed = fetch_feed(session, args.base, raw_dir)
        except Exception:
            pass
    else:
        entries, feed = discover(session, args.base, raw_dir, wayback=not args.no_wayback)

    entries = [e for e in entries if in_window(e[1], start, end)]
    dated = sorted((e for e in entries if e[1] is not None), key=lambda e: e[1],
                   reverse=not args.oldest_first)
    entries = dated + [e for e in entries if e[1] is None]
    direction = "oldest -> newest" if args.oldest_first else "newest -> oldest"
    print(f"{len(entries)} candidate posts, {direction}, start={start:%Y-%m-%d}"
          f"{'' if end is None else f', end={end:%Y-%m-%d}'}", file=sys.stderr)

    index = read_index(raw_dir)
    missing = read_missing(raw_dir)
    skip = set(index) | load_existing(args.existing or [])
    by_id = {e.get("medium_id"): u for u, e in index.items()}

    # The Wayback crawl index holds mangled variants of real post URLs
    # (the id truncated by a character or two, a hyphen inserted mid-id);
    # match those to archived posts so they are neither fetched nor
    # flagged missing. A variant's key equals the real key, or is a
    # near-complete prefix of it (truncation loses trailing characters).
    keys = {norm_key(u): u for u in index}

    def mangled_alias(url: str) -> str | None:
        k = norm_key(url)
        return next((u for ck, u in keys.items() if u != url
                     and ck.startswith(k) and len(ck) - len(k) <= 4), None)

    for url in [u for u in missing if mangled_alias(u)]:
        print(f"unflagged from missing.json: {url}\n"
              f"  is a mangled variant of the archived {mangled_alias(url)}",
              file=sys.stderr)
        del missing[url]
        write_missing(raw_dir, missing)

    fetched = media_files = 0
    for n, (url, approx, source) in enumerate(entries, 1):
        if args.limit and fetched >= args.limit:
            print(f"reached --limit {args.limit}", file=sys.stderr)
            break
        pid = medium_id(url) or re.sub(r"[^A-Za-z0-9]", "_", url)[-40:]
        # The same post may be indexed under another URL: import-export keys
        # by the export's canonical URL. Skip only if its page was fetched.
        alias = by_id.get(pid)
        already = url in skip or (alias is not None and (raw_dir / pid / "page.html").exists())
        if already and not args.force:
            # posts archived before embed media was fetched: backfill
            # raw/<id>/media/ without re-fetching the post itself
            page = raw_dir / pid / "page.html"
            if page.exists():
                text = page.read_text(encoding="utf-8")
                got = fetch_media(session, text, pid, raw_dir / pid, args.delay)
                if not args.no_images:
                    got += backfill_embed_assets(session, text, pid,
                                                 raw_dir / pid, args.delay)
                if got:
                    media_files += got
                    print(f"[{n}/{len(entries)}] {url}\n"
                          f"  archived {got} embed media file(s) for the "
                          f"already-fetched post", file=sys.stderr)
            continue
        variant_of = None if source == "file" else mangled_alias(url)
        if variant_of:
            print(f"[{n}/{len(entries)}] {url}\n"
                  f"  assuming this is a mangled variant of the archived "
                  f"{variant_of}; skipping", file=sys.stderr)
            continue
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
            media_files += info.get("media_count", 0)
            if dest.exists():
                if (dest / "export.html").exists():   # not fetch's to lose
                    shutil.copy2(dest / "export.html", tmp / "export.html")
                shutil.rmtree(dest)
            tmp.rename(dest)
            entry = {
                "medium_id": pid,
                "title": info["title"],
                "published": info["published"],
                "sitemap_date": approx.isoformat() if approx else None,
                "found_via": source,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "images": info["image_count"],
                "in_feed": url in feed,
            }
            if alias is not None and alias != url:    # re-key under the fetched URL
                old = index.pop(alias)
                entry.update({k: old[k] for k in ("in_export", "imported_at", "draft") if k in old})
            index[url] = entry
            by_id[pid] = url
            keys[norm_key(url)] = url
            write_index(raw_dir, index)
            if url in missing:                   # it came back; unflag it
                del missing[url]
                write_missing(raw_dir, missing)
            fetched += 1
        except Exception as e:
            status = e.status if isinstance(e, PostGone) else \
                getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410, "soft-404"):
                # Discovery (usually the Wayback Machine) knows the post, but
                # Medium no longer serves it: deleted, unpublished, or the
                # account is gone. Flag it; its content only survives as
                # web.archive.org captures.
                ts = f"{approx:%Y%m%d%H%M%S}" if approx else "*"
                missing[url] = {
                    "status": status,
                    "medium_id": medium_id(url),
                    "found_via": source,
                    "approx_date": approx.isoformat() if approx else None,
                    "wayback_url": f"https://web.archive.org/web/{ts}/{url}",
                    "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                # A deleted post republished under a new id keeps its slug;
                # point at the archived double so review is quick.
                same = [u for u in index if u != url and slug_of(u) == slug_of(url)]
                if same:
                    missing[url]["same_slug_archived"] = same
                write_missing(raw_dir, missing)
                print(f"  GONE from Medium ({status}); flagged in raw/missing.json", file=sys.stderr)
                if same:
                    print(f"  (same slug is archived as {same[0]} -- likely "
                          f"deleted and republished under a new id)", file=sys.stderr)
            else:
                print(f"  FAILED {url}: {e}", file=sys.stderr)
            shutil.rmtree(tmp, ignore_errors=True)
        time.sleep(args.delay)
    write_readme(args.out, args.base)
    summary = f"fetch done: {fetched} new, {len(index)} total in {raw_dir}"
    if media_files:
        summary += f"; {media_files} embed media file(s) archived"
    if missing:
        summary += f"; {len(missing)} posts gone from Medium -> {raw_dir / 'missing.json'}"
    print(summary, file=sys.stderr)
