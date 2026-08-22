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
from .images import collect_image_urls, safe_filename
from .net import fetch, make_session
from .pages import extract_metadata
from .readme import write_readme
from .urls import canonical_url, medium_id


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
    feed = {}
    if args.urls:
        lines = [l.strip() for l in args.urls.read_text().splitlines()]
        entries = [(canonical_url(l), None) for l in lines if l and not l.startswith("#")]
        try:
            feed = fetch_feed(session, args.base, raw_dir)
        except Exception:
            pass
    else:
        entries, feed = discover(session, args.base, raw_dir, wayback=args.wayback)

    entries = [e for e in entries if in_window(e[1], start, end)]
    dated = sorted((e for e in entries if e[1] is not None), key=lambda e: e[1],
                   reverse=not args.oldest_first)
    entries = dated + [e for e in entries if e[1] is None]
    direction = "oldest -> newest" if args.oldest_first else "newest -> oldest"
    print(f"{len(entries)} candidate posts, {direction}, start={start:%Y-%m-%d}"
          f"{'' if end is None else f', end={end:%Y-%m-%d}'}", file=sys.stderr)

    index = read_index(raw_dir)
    skip = set(index) | load_existing(args.existing or [])
    by_id = {e.get("medium_id"): u for u, e in index.items()}
    fetched = 0
    for n, (url, approx) in enumerate(entries, 1):
        if args.limit and fetched >= args.limit:
            print(f"reached --limit {args.limit}", file=sys.stderr)
            break
        pid = medium_id(url) or re.sub(r"[^A-Za-z0-9]", "_", url)[-40:]
        # The same post may be indexed under another URL: import-export keys
        # by the export's canonical URL. Skip only if its page was fetched.
        alias = by_id.get(pid)
        already = url in skip or (alias is not None and (raw_dir / pid / "page.html").exists())
        if already and not args.force:
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
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "images": info["image_count"],
                "in_feed": url in feed,
            }
            if alias is not None and alias != url:    # re-key under the fetched URL
                old = index.pop(alias)
                entry.update({k: old[k] for k in ("in_export", "imported_at", "draft") if k in old})
            index[url] = entry
            by_id[pid] = url
            write_index(raw_dir, index)
            fetched += 1
        except Exception as e:
            print(f"  FAILED {url}: {e}", file=sys.stderr)
            shutil.rmtree(tmp, ignore_errors=True)
        time.sleep(args.delay)
    write_readme(args.out, args.base)
    print(f"fetch done: {fetched} new, {len(index)} total in {raw_dir}", file=sys.stderr)
