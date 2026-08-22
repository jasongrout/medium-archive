"""Archive a Medium publication in independent steps:

    fetch          pull raw material from Medium: page HTML, RSS feed item,
                   and full-resolution images, unmodified, into <out>/raw/
    import-export  merge a Medium account export into <out>/raw/
    compare        verify the page conversion against the account export
    convert        turn the raw archive into Markdown + front matter + local
                   images in <out>/posts/, plus posts.json and redirects.csv
    stats          summarize the converted archive

Only `fetch` (and `all`) touches the network; the other steps can be re-run
freely while tuning the conversion (selectors, Markdown style, output
layout) without hitting Medium again. `fetch` is incremental and resumable.

A Medium account export (medium.com -> Settings -> Download your
information) can be merged into the raw archive with `import-export`; its
posts/*.html files are the editor's own clean HTML and become the preferred
body source on the next `convert`.

Only fetch and all need the publication URL; the other steps work offline
from the archive alone.

Examples:
    medium-archive fetch https://blog.example.com/              # everything, newest first
    medium-archive fetch https://blog.example.com/ --limit 5    # smoke test
    medium-archive fetch https://blog.example.com/ --start 2024-12-31 --end 2024-01-01
    medium-archive import-export medium-export.zip
    medium-archive compare                                      # page vs export check
    medium-archive convert                                      # raw -> posts/
    medium-archive stats                                        # summarize the archive
    medium-archive all https://blog.example.com/ --limit 5      # fetch then convert

Notes:
  * Discovery: sitemap merged with the RSS feed (~10 most recent posts, with
    full bodies). Medium's sitemap only lists the last few years; --wayback
    adds the Wayback Machine's index of past captures to find older posts,
    and --urls FILE can seed URLs collected elsewhere. Sitemap <lastmod> and
    first-capture dates are approximations that order and pre-filter; the
    real publish date from each page is re-checked against --start/--end
    after fetching.
  * Redirects: front matter carries original_url, original_path (the path an
    old inbound link carries), medium_id (Medium also resolves /p/<id>) and
    slug; redirects.csv collects these for every converted post.
  * Medium's "was originally published in ... on Medium" footer and stat
    tracking pixels are removed. Embedded gists/iframes become links.
  * Medium rate-limits and may serve a bot wall; fetch is resumable.
  * The archive layout is documented in the README.md written into <out>/.
Progress is written to stderr.
"""

import argparse
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .compare import cmd_compare
from .convert import cmd_convert
from .stats import cmd_stats
from .dates import parse_date
from .export import cmd_import_export
from .fetch import cmd_fetch

def publication_url(text: str) -> str:
    p = urlparse(text)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise argparse.ArgumentTypeError(f"not an http(s) URL: {text!r}")
    return text


def parse_cli_date(text: str, end_of_day: bool) -> datetime:
    dt = parse_date(text)
    if dt is None:
        raise argparse.ArgumentTypeError(f"unrecognised date: {text!r}")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def add_fetch_args(p):
    p.add_argument("base", type=publication_url, metavar="URL",
                   help="publication root, e.g. https://blog.example.com/; "
                        "/sitemap/sitemap.xml and /feed must resolve under it")
    p.add_argument("--urls", type=Path, metavar="FILE",
                   help="read post URLs from FILE (one per line, '#' comments) "
                        "instead of discovering them from sitemap + feed")
    p.add_argument("--wayback", action="store_true",
                   help="also discover post URLs from the Wayback Machine's index of "
                        "past captures (web.archive.org); Medium's sitemap only lists "
                        "the last few years, so older posts -- still live on Medium -- "
                        "need this to be found. Posts are still fetched from the live "
                        "site")
    p.add_argument("--start", type=lambda t: parse_cli_date(t, True), default=None, metavar="DATE",
                   help="most recent publish date to include (YYYY-MM-DD or ISO timestamp; "
                        "a bare date includes the whole day); fetching proceeds backward "
                        "in time from here (default: now)")
    p.add_argument("--end", type=lambda t: parse_cli_date(t, False), default=None, metavar="DATE",
                   help="oldest publish date to include (default: no lower bound)")
    p.add_argument("--oldest-first", action="store_true",
                   help="process from --end forward instead of --start backward")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="stop after fetching N new posts (already-fetched posts do not "
                        "count); 0 = no limit (default: 0)")
    p.add_argument("--existing", action="append", metavar="DIR",
                   help="earlier archive whose posts should be skipped (raw/index.json, "
                        "posts.json, or *.md with original_url); repeatable; the --out "
                        "archive itself is always checked")
    p.add_argument("--force", action="store_true",
                   help="re-fetch posts already in the raw archive")
    p.add_argument("--delay", type=float, default=1.5, metavar="SECONDS",
                   help="sleep between post requests; images sleep delay/4; raise to "
                        "2-3 s on 429s (default: 1.5)")
    p.add_argument("--no-images", action="store_true",
                   help="skip image downloads (convert will keep remote URLs)")


def add_convert_args(p):
    p.add_argument("--prefer-page", action="store_true",
                   help="always convert the page body; by default the RSS "
                        "<content:encoded> body is used when feed_item.json is present, "
                        "since it is cleaner HTML with proper code blocks and "
                        "full-resolution images")
    p.add_argument("--only", action="append", metavar="URL",
                   help="convert just this post (repeatable; default: all)")
    p.add_argument("--clean", action="store_true",
                   help="delete <out>/posts/ before converting")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default="medium_export", type=Path, metavar="DIR",
                        help="archive root (default: medium_export)")
    ap.set_defaults(base=None)   # only fetch and all take the URL
    sub = ap.add_subparsers(dest="command", required=True)

    def parser(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    add_fetch_args(parser("fetch", help="download raw material into <out>/raw/"))
    imp = parser("import-export",
                 help="merge a Medium account export into <out>/raw/")
    imp.add_argument("export_path", type=Path, metavar="ZIP_OR_DIR",
                     help="the export zip from medium.com Settings -> Download your "
                          "information, or an unzipped copy / its posts/ directory")
    imp.add_argument("--all", action="store_true",
                     help="also import export posts that do not match a post already "
                          "in the archive, e.g. unlisted posts or posts from other "
                          "publications (default: only merge into fetched posts)")
    imp.add_argument("--drafts", action="store_true",
                     help="also import draft_*.html files (default: skip drafts)")
    add_convert_args(parser("convert", help="convert <out>/raw/ into <out>/posts/"))
    cmp_p = parser("compare",
                   help="verify the page conversion against the account export, "
                        "offline; exits non-zero if any post differs")
    cmp_p.add_argument("--only", action="append", metavar="URL",
                       help="compare just this post (repeatable; default: every post "
                            "that has both page.html and export.html)")
    stats_p = parser("stats", help="summarize the converted archive "
                                   "(posts, authors, lengths, tags)")
    stats_p.add_argument("--top", type=int, default=15, metavar="N",
                         help="how many authors/tags to list (default: 15)")
    both = parser("all", help="fetch then convert")
    add_fetch_args(both)
    add_convert_args(both)
    args = ap.parse_args()

    if args.command in ("fetch", "all"):
        cmd_fetch(args)
    if args.command == "import-export":
        cmd_import_export(args)
    if args.command in ("convert", "all"):
        cmd_convert(args)
    if args.command == "compare":
        cmd_compare(args)
    if args.command == "stats":
        cmd_stats(args)
