"""The stats step: summarize the converted archive.

Works from posts.json and the converted bodies in <out>/posts/, so run
convert first; raw/index.json and raw/missing.json, when present, add
provenance detail (how each post was discovered, which sources were
recovered). Everything is offline.
"""

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from .fetch import archive_base, read_index, read_missing

FRONT_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
MD_NOISE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)|[#>*`|-]")


def word_count(md_path: Path) -> int:
    text = FRONT_RE.sub("", md_path.read_text(encoding="utf-8", errors="replace"))
    text = MD_NOISE_RE.sub(lambda m: m.group(1) or " ", text)
    return len(text.split())


def fmt_quartiles(values: list) -> str:
    if len(values) < 2:
        return str(values[0]) if values else "n/a"
    q1, q2, q3 = (round(q) for q in statistics.quantiles(values, n=4))
    return (f"min {min(values)}, q1 {q1}, median {q2}, q3 {q3}, "
            f"max {max(values)} (mean {round(statistics.mean(values))})")


def top(counter: Counter, n: int, total: int) -> str:
    return "\n".join(f"  {count:4d}  ({count / total:4.0%})  {name}"
                     for name, count in counter.most_common(n))


def print_provenance(out: Path, manifest: dict, sources: Counter):
    """Where the archive's material came from: how each post was discovered
    (raw/index.json's found_via), which extra sources were recovered for it
    (account export, Ghost capture, RSS feed item), which source each body
    was converted from, and how many discovered posts Medium no longer
    serves at all (raw/missing.json)."""
    index = read_index(out / "raw")
    missing = read_missing(out / "raw")

    print("\nProvenance:")
    entries = [index.get(url) or {} for url in manifest]
    if index:
        found = Counter(e.get("found_via") or "?" for e in entries)
        print("  discovered via: " + ", ".join(f"{s}: {c}" for s, c in found.most_common()))
        if found.get("wayback"):
            print("    (wayback: Medium itself no longer lists these; "
                  "found in the web.archive.org index)")
        if found.get("ghost-wayback"):
            print("    (ghost-wayback: recovered from the blog's pre-Medium "
                  "Ghost site via the Wayback Machine)")
        n_feed = sum(1 for e in entries if e.get("in_feed"))
        n_export = sum(1 for e in entries if e.get("in_export"))
        n_drafts = sum(1 for e in entries if e.get("draft"))
        extra = [f"{n_feed} in the RSS feed",
                 f"{n_export} in an account export"
                 + (f" (drafts: {n_drafts})" if n_drafts else "")]
        n_ghost = sum(1 for e in entries if e.get("in_ghost"))
        if n_ghost:
            extra.append(f"{n_ghost} with a Ghost capture attached")
        print("  also sourced: " + ", ".join(extra))
    print("  body converted from: " + ", ".join(f"{s}: {c}" for s, c in sources.most_common()))
    if missing:
        print(f"  gone from Medium: {len(missing)} discovered but no longer "
              f"served; only Wayback captures remain (raw/missing.json)")


def cmd_stats(args):
    manifest_path = args.out / "posts.json"
    if not manifest_path.exists():
        sys.exit(f"no stats to report: {manifest_path} missing (run convert first)")
    manifest = json.loads(manifest_path.read_text())
    posts = list(manifest.values())
    if not posts:
        sys.exit("no stats to report: posts.json is empty")
    n = len(posts)

    dates = sorted(p["date"] for p in posts if p.get("date"))
    words, missing_bodies = [], 0
    by_words = []
    for p in posts:
        md = args.out / p["dir"] / "index.md"   # dir is relative to <out>
        if md.exists():
            w = word_count(md)
            words.append(w)
            by_words.append((w, p.get("title") or p.get("slug")))
        else:
            missing_bodies += 1

    authors = Counter((p.get("author") or "(unknown)") for p in posts)
    tags = Counter(t for p in posts for t in p.get("tags") or [])
    untagged = sum(1 for p in posts if not p.get("tags"))
    years = Counter(d[:4] for d in dates)
    sources = Counter(p.get("body_source") or "?" for p in posts)
    image_counts = [len(p.get("images") or []) for p in posts]

    print(f"Archive: {args.base or archive_base(args.out) or args.out}")
    print(f"\nPosts: {n}")
    if dates:
        print(f"  first {dates[0][:10]}, latest {dates[-1][:10]}")
        print("  per year: " + ", ".join(f"{y}: {c}" for y, c in sorted(years.items())))

    print_provenance(args.out, manifest, sources)

    print(f"\nAuthors: {len(authors)}")
    print(top(authors, args.top, n))

    if words:
        print(f"\nLength (words):")
        print(f"  {fmt_quartiles(words)}")
        longest = max(by_words)
        shortest = min(by_words)
        print(f"  longest: {longest[1]} ({longest[0]} words)")
        print(f"  shortest: {shortest[1]} ({shortest[0]} words)")
    if missing_bodies:
        print(f"  ({missing_bodies} posts missing index.md, not counted)")

    print(f"\nImages: {sum(image_counts)} total, "
          f"{sum(1 for c in image_counts if c)} posts with images, "
          f"max {max(image_counts)} in one post")

    print(f"\nTags: {len(tags)} distinct"
          + (f", {untagged} untagged posts" if untagged else ""))
    print(top(tags, args.top, n))
