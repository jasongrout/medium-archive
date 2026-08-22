"""Medium account export (medium.com -> Settings -> Download your
information) support: parse the export's posts/*.html files and file them
into <out>/raw/ so convert can use them.

Export files are the editor's own HTML wrapped in an h-entry microformat --
far cleaner than the rendered page -- with the exact publish timestamp and
canonical URL in the footer. They are the preferred body source, but carry
no tags, no updated date and no publication canonical domain, so the
scraped page still contributes metadata (and the downloaded images).
"""

import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from .urls import canonical_url, medium_id


def parse_export(text: str) -> dict:
    """Metadata carried by one export post file, plus its parsed soup."""
    soup = BeautifulSoup(text, "html.parser")
    canon = soup.select_one("footer a.p-canonical")
    time_el = soup.select_one("footer time.dt-published")
    author = soup.select_one("footer a.p-author")
    subtitle = soup.select_one('section[data-field="subtitle"]')
    title = soup.select_one("h1.p-name") or soup.title
    return {
        "title": title.get_text(strip=True) if title else "",
        "subtitle": subtitle.get_text(" ", strip=True) if subtitle else "",
        "author": author.get_text(strip=True) if author else "",
        "author_url": author.get("href") if author else None,
        "date": time_el.get("datetime") if time_el else "",
        "canonical_url": canonical_url(canon["href"]) if canon and canon.get("href") else None,
        "soup": soup,
    }


def export_body(soup):
    """The export body cleaned for conversion: the repeated title/subtitle
    grafs and the leading section divider go (they live in front matter);
    later section dividers stay and become thematic breaks."""
    body = soup.select_one('section[data-field="body"]') or soup
    divider = body.find("div", class_="section-divider")
    if divider:
        divider.decompose()
    for t in body.select(".graf--title, .graf--subtitle, .graf--kicker"):
        t.decompose()
    # The editor's h3/h4 render as h2/h3 on the page; shift to match, so
    # converted output is identical whichever body source is used.
    for h in body.find_all(["h3", "h4"]):
        h.name = f"h{int(h.name[1]) - 1}"
    return body


def iter_export_files(path: Path):
    """Yield (name, text) for post HTML files in an export zip, an unzipped
    export directory, or a directory of post files."""
    if path.is_dir():
        posts = path / "posts" if (path / "posts").is_dir() else path
        for p in sorted(posts.glob("*.html")):
            yield p.name, p.read_text(encoding="utf-8", errors="replace")
    else:
        with zipfile.ZipFile(path) as zf:
            for n in sorted(zf.namelist()):
                p = Path(n)
                if p.suffix == ".html" and p.parent.name == "posts":
                    yield p.name, zf.read(n).decode("utf-8", errors="replace")


def post_id(meta: dict, filename: str) -> str | None:
    """Medium's hex id, from the canonical URL or the export filename
    (…-Title-slug--<id>.html)."""
    pid = medium_id(meta["canonical_url"] or "")
    if not pid:
        pid = medium_id("/" + Path(filename).stem)
    return pid


def cmd_import_export(args):
    from .fetch import read_index, write_index   # avoid import cycle

    raw_dir = args.out / "raw"
    index = read_index(raw_dir)
    by_id = {e.get("medium_id"): url for url, e in index.items()}
    imported = drafts = unmatched = skipped = 0
    for name, text in iter_export_files(args.export_path):
        draft = name.startswith("draft_")
        if draft and not args.drafts:
            drafts += 1
            continue
        meta = parse_export(text)
        pid = post_id(meta, name)
        if not pid:
            print(f"  skipped {name}: no Medium id in footer or filename", file=sys.stderr)
            skipped += 1
            continue
        # An account export holds everything its author ever wrote -- posts
        # in other publications, responses. Only merge files matching a post
        # this archive already knows unless --all asks for the rest.
        if not draft and pid not in by_id and not args.all:
            unmatched += 1
            continue
        dest = raw_dir / pid
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "export.html").write_text(text, encoding="utf-8")
        url = by_id.get(pid) or meta["canonical_url"] or f"https://medium.com/p/{pid}"
        entry = index.setdefault(url, {"medium_id": pid})
        entry.setdefault("title", meta["title"])
        entry.setdefault("published", meta["date"])
        entry["in_export"] = True
        if name.startswith("draft_"):
            entry["draft"] = True
        entry["imported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        by_id[pid] = url
        imported += 1
    write_index(raw_dir, index)
    print(f"import-export done: {imported} posts into {raw_dir}"
          + (f", {unmatched} not in this archive skipped"
             " (fetch first, or use --all to import them)" if unmatched else "")
          + (f", {drafts} drafts skipped (use --drafts to include)" if drafts else "")
          + (f", {skipped} unidentifiable skipped" if skipped else ""), file=sys.stderr)
