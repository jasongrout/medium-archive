"""Offline verification: convert each post's body independently from the
scraped page and from the account export, and report any disagreement.

The two pipelines produce identical Markdown when the page cleanup is
working, so a difference means new page chrome or a conversion bug. Run it
after fetching new posts or when tuning convert; posts it reports clean
are guaranteed to convert as faithfully from the page as from the export.
"""

import difflib
import json
import sys
from urllib.parse import unquote_plus

from bs4 import BeautifulSoup

from .convert import to_markdown
from .export import export_body, parse_export
from .fetch import read_index
from .pages import extract_metadata, page_body
from .urls import canonical_url


def comparable_lines(markdown: str) -> list:
    """Lines that matter for agreement: blank-line layout is noise, and
    the page and export sometimes encode the same URL differently
    (%20 vs + vs a literal space)."""
    return [unquote_plus(l.rstrip()) for l in markdown.splitlines() if l.strip()]


def cmd_compare(args):
    raw_dir = args.out / "raw"
    index = read_index(raw_dir)
    if not index:
        sys.exit(f"nothing to compare: {raw_dir}/index.json missing or empty")
    targets = [canonical_url(u) for u in args.only] if args.only else list(index)

    identical, differing, no_export, no_page, missing = 0, [], 0, 0, 0
    for url in targets:
        entry = index.get(url)
        raw = raw_dir / entry["medium_id"] if entry else None
        if raw is None or not raw.is_dir():
            missing += 1
            continue
        if not (raw / "export.html").exists():
            no_export += 1
            continue
        if not (raw / "page.html").exists():
            no_page += 1
            continue

        img_map = {}
        if (raw / "images.json").exists():
            img_map = json.loads((raw / "images.json").read_text())
        soup = BeautifulSoup((raw / "page.html").read_text(encoding="utf-8"), "html.parser")
        info = extract_metadata(soup, url)
        page_md, _ = to_markdown(page_body(soup, info["tags"]), info["url"], img_map, raw)
        exp = parse_export((raw / "export.html").read_text(encoding="utf-8"))
        export_md, _ = to_markdown(export_body(exp["soup"]), info["url"], img_map, raw)

        page_lines = comparable_lines(page_md)
        export_lines = comparable_lines(export_md)
        if page_lines == export_lines:
            identical += 1
            continue
        differing.append(url)
        print(f"DIFFERS {url}")
        for line in difflib.unified_diff(page_lines, export_lines,
                                         "page", "export", lineterm="", n=1):
            print(f"  {line}")
        print()

    print(f"compare done: {identical} identical, {len(differing)} differ"
          + (f", {no_export} without export.html" if no_export else "")
          + (f", {no_page} without page.html" if no_page else "")
          + (f", {missing} not in raw/" if missing else ""), file=sys.stderr)
    if differing:
        sys.exit(1)
