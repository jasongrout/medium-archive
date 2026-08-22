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
from .pages import extract_metadata, ghost_body, page_body
from .urls import canonical_url


def comparable_lines(markdown: str) -> list:
    """Lines that matter for agreement: blank-line layout is noise, and
    the page and export sometimes encode the same URL differently
    (%20 vs + vs a literal space)."""
    return [unquote_plus(l.rstrip()) for l in markdown.splitlines() if l.strip()]


def compare_ghost(args):
    """Review mode (--ghost): for every post with an attached Ghost capture,
    diff the Ghost conversion against the post's best Medium conversion.
    Differences are expected -- Medium's importer mangles code blocks and
    formatting -- so nothing is gated; the diffs show which posts are worth
    converting with --prefer-ghost (or where Medium carries later edits)."""
    raw_dir = args.out / "raw"
    index = read_index(raw_dir)
    if not index:
        sys.exit(f"nothing to compare: {raw_dir}/index.json missing or empty")
    targets = [canonical_url(u) for u in args.only] if args.only else list(index)

    identical, differing, skipped = 0, 0, 0
    for url in targets:
        entry = index.get(url) or {}
        raw = raw_dir / entry.get("medium_id", "")
        if not (raw / "ghost.html").exists():
            skipped += 1
            continue
        img_map = {}
        if (raw / "images.json").exists():
            img_map = json.loads((raw / "images.json").read_text())

        gsoup = BeautifulSoup((raw / "ghost.html").read_text(encoding="utf-8"),
                              "html.parser")
        ghost_md, _ = to_markdown(ghost_body(gsoup), url, img_map, raw)
        if (raw / "export.html").exists():
            exp = parse_export((raw / "export.html").read_text(encoding="utf-8"))
            medium_md, medium_src = to_markdown(export_body(exp["soup"]), url,
                                                img_map, raw)[0], "export"
        elif (raw / "page.html").exists():
            soup = BeautifulSoup((raw / "page.html").read_text(encoding="utf-8"),
                                 "html.parser")
            info = extract_metadata(soup, url)
            medium_md, medium_src = to_markdown(page_body(soup, info["tags"]),
                                                info["url"], img_map, raw)[0], "page"
        else:
            skipped += 1
            continue

        ghost_lines = comparable_lines(ghost_md)
        medium_lines = comparable_lines(medium_md)
        if ghost_lines == medium_lines:
            identical += 1
            continue
        differing += 1
        print(f"DIFFERS {url}")
        for line in difflib.unified_diff(medium_lines, ghost_lines,
                                         medium_src, "ghost", lineterm="", n=1):
            print(f"  {line}")
        print()

    print(f"compare --ghost done: {identical} identical, {differing} differ, "
          f"{skipped} without an attached Ghost capture (informational only; "
          f"differences are expected)", file=sys.stderr)


def cmd_compare(args):
    if getattr(args, "ghost", False):
        return compare_ghost(args)
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
