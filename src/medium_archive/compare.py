"""Offline verification: convert each post's body independently from the
scraped page and from the account export, and report any disagreement.

The two pipelines produce identical Markdown when the page cleanup is
working, so a difference means new page chrome or a conversion bug. Run it
after fetching new posts or when tuning convert; posts it reports clean
are guaranteed to convert as faithfully from the page as from the export.
"""

import difflib
import json
import re
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


# The differences Medium's importer introduces mechanically when a Ghost
# post is migrated: straightened quotes become curly, hyphens become
# en/em-dashes, ellipses are combined. Both sides are folded to the plain
# form so only authored changes remain.
TYPOGRAPHY = str.maketrans({
    "‘": "'", "’": "'",           # curly single quotes
    "“": '"', "”": '"',           # curly double quotes
    "–": "-", "—": "-",           # en/em-dash
    "…": "...",
    "︎": None, "️": None,   # emoji variation selectors (↩︎ vs ↩)
})
LINK_TITLE_RE = re.compile(r'\(([^()\s]+) "[^"]*"\)')    # (url "title") -> (url)
HEADING_RE = re.compile(r"^#{1,6} ")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
HARD_BREAK_RE = re.compile(r"  +\n")     # <br> renders as two trailing spaces
ORDERED_ITEM_RE = re.compile(r"^\d+[.)] ")
SELF_LINK_RE = re.compile(r"\[([^\]]+)\]\(\1\)")     # [url](url) -> url
DASH_RE = re.compile(r"(?<=\S) ?--? ?(?=\S)")        # a -- b / a - b -> a-b


def ghost_comparable_blocks(markdown: str) -> list:
    """Comparison units for --ghost mode: paragraphs rather than lines,
    with Medium's mechanical migration differences normalized away --
    curly typography, dash spelling and spacing, headings flattened or
    demoted (the marker is dropped, the text kept), list marker style,
    emphasis re-nesting, footnote anchor syntax, rehosted/renamed image
    files, reflowed line wrapping (a plain newline is wrapping and
    merges; a <br> hard break is a paragraph boundary and splits), and
    the hero image Medium prepends. What survives is authored content:
    text edits, and images or paragraphs present on only one side."""
    blocks = []
    for raw_block in re.split(r"\n\s*\n", markdown):
        for block in HARD_BREAK_RE.split(raw_block):
            block = unquote_plus(" ".join(block.split()))
            if not block:
                continue
            block = block.translate(TYPOGRAPHY)
            block = HEADING_RE.sub("", block)
            block = ORDERED_ITEM_RE.sub("", block)
            block = IMAGE_RE.sub("![image]", block)
            block = block.replace("**", "").replace("*", "")
            block = block.replace("#fn:", "#fn").replace("#fnref:", "#fnref")
            block = re.sub(r"\[\[(\d+)\]\]", r"[\1]", block)   # [[1]] -> [1]
            block = LINK_TITLE_RE.sub(r"(\1)", block)
            block = SELF_LINK_RE.sub(r"\1", block)
            block = DASH_RE.sub("-", block)
            blocks.append(block)
    if blocks and blocks[0] == "![image]":
        blocks = blocks[1:]
    return blocks


def compare_ghost(args):
    """Review mode (--ghost): for every post with an attached Ghost capture,
    diff the Ghost conversion against the post's best Medium conversion.
    Medium's mechanical migration differences (typography, heading levels,
    image renames, line wrapping) are normalized away first, so a reported
    difference is authored content: an image or paragraph Medium dropped
    (worth converting with --prefer-ghost) or an edit made after the
    migration (worth keeping on the Medium side). Nothing is gated."""
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

        ghost_lines = ghost_comparable_blocks(ghost_md)
        medium_lines = ghost_comparable_blocks(medium_md)
        # a block-boundary shift alone (a heading merged into its
        # paragraph, a <p> split moved) is not a content difference
        if " ".join(ghost_lines) == " ".join(medium_lines):
            identical += 1
            continue
        differing += 1
        print(f"DIFFERS {url}")
        for line in difflib.unified_diff(medium_lines, ghost_lines,
                                         medium_src, "ghost", lineterm="", n=1):
            print(f"  {line}")
        print()

    print(f"compare --ghost done: {identical} identical, {differing} differ, "
          f"{skipped} without an attached Ghost capture (informational only)",
          file=sys.stderr)


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
