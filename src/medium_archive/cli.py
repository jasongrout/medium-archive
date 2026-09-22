"""Archive a Medium publication and build static sites from it.

Steps:
    fetch          download page HTML, RSS items, full-size images and
                   embed content (gists, tweets, Carbon, Giphy) into
                   archive/raw/, unmodified; incremental and resumable
    import-export  merge a Medium account export into archive/raw/
    import-ghost   recover a Ghost-era blog's posts from the Wayback Machine
    compare        diff page and export conversions of the same posts
    convert        archive/raw/ -> Markdown in archive/posts/, plus
                   posts.json and redirects.csv
    hugo, pelican, myst
                   build a site from the converted posts
    lint           report conversion defects
    stats          summarize the converted archive
    all            fetch, then convert

Only fetch, all and import-ghost use the network.

Examples:
    medium-archive all https://blog.example.com/ --limit 5      # smoke test
    medium-archive fetch https://blog.example.com/              # re-run until "0 new"
    medium-archive fetch https://blog.example.com/ --start 2024-12-31 --end 2024-01-01
    medium-archive import-export medium-export.zip              # once per author
    medium-archive import-ghost https://blog.example.com/
    medium-archive compare
    medium-archive convert
    medium-archive lint
    medium-archive stats
    medium-archive pelican --out ../blog-pelican --clean        # into a site repo

Directories: --archive DIR (default archive/) for every step; the site
exporters add --site-inputs DIR (default site/), --out DIR (default
site-<generator>/) and --image-cache DIR (default .image-cache/).

The archive layout is documented in archive/README.md, and each
generated site in its own README.md. Progress is written to stderr.
"""

import argparse
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .compare import cmd_compare
from .convert import cmd_convert
from .lint import cmd_lint
from .hugo import cmd_hugo
from .myst import cmd_myst
from .pelican import cmd_pelican
from .stats import cmd_stats
from .dates import parse_date
from .paths import (DEFAULT_ARCHIVE, DEFAULT_IMAGE_CACHE, DEFAULT_SITE_INPUTS,
                    default_out)
from .export import cmd_import_export
from .fetch import cmd_fetch
from .ghost import cmd_import_ghost

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
                        "instead of discovering them from sitemap + feed; a "
                        "line may also name an archived post by its Medium id "
                        "or its posts/ directory name (as lint prints it), "
                        "e.g. to backfill one post's embed media")
    p.add_argument("--no-wayback", action="store_true",
                   help="skip the Wayback Machine's index of past captures "
                        "(web.archive.org) during discovery; Medium's sitemap only "
                        "lists the last few years, so without it older posts -- "
                        "still live on Medium -- go unfound. Posts are always "
                        "fetched from the live site")
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
                        "posts.json, or *.md with original_url); repeatable; this "
                        "project's own archive is always checked")
    p.add_argument("--force", action="store_true",
                   help="re-fetch posts already in the raw archive")
    p.add_argument("--delay", type=float, default=1.5, metavar="SECONDS",
                   help="sleep between post requests; images sleep delay/4; raise to "
                        "2-3 s on 429s (default: 1.5)")
    p.add_argument("--no-images", action="store_true",
                   help="skip image downloads (convert will keep remote URLs)")
    p.add_argument("--cookies", type=Path, metavar="FILE",
                   help="cookies to send with every request, from a browser "
                        "logged into Medium: a Netscape cookie jar (a "
                        "'cookies.txt' browser-extension export) or a file "
                        "holding one 'name=value; name=value' Cookie header "
                        "line copied from devtools. Use this when Medium's "
                        "edge answers 403 to a plain fetch (fetch reports "
                        "this and stops after repeated refusals) -- pair "
                        "with --user-agent set to that same browser's string, "
                        "since the cookies are bound to it")
    p.add_argument("--user-agent", metavar="STRING",
                   help="override the User-Agent sent with every request "
                        "(default: a current desktop Chrome string); match "
                        "this to the browser --cookies came from")
    p.add_argument("--solve-walls", action="store_true",
                   help="when a post is refused by Medium's bot wall and "
                        "isn't in the RSS feed, open it in a real, visible "
                        "browser and wait for you to clear the challenge by "
                        "hand (it may also clear on its own), then archive "
                        "the page it renders -- one browser for the whole "
                        "run, so solving it once usually covers every wall "
                        "after it. Requires Playwright (pip install "
                        "playwright && playwright install chromium). Off by "
                        "default: it blocks on input() and can't run "
                        "unattended")


def add_convert_args(p):
    p.add_argument("--prefer-page", action="store_true",
                   help="always convert the rendered page body; by default the "
                        "account export, the page's embedded editor state, or "
                        "the RSS <content:encoded> body (in that order) is "
                        "preferred -- all three are cleaner sources than the "
                        "rendered HTML")
    p.add_argument("--prefer-ghost", action="store_true",
                   help="when a post has an attached Ghost capture (ghost.html "
                        "from import-ghost), convert its body from that instead "
                        "of the Medium sources; the Ghost original often has "
                        "cleaner code blocks, but misses any edits made on "
                        "Medium after the migration. `compare --ghost` shows "
                        "the differences per post; combine with --only to "
                        "cherry-pick")
    p.add_argument("--only", action="append", metavar="URL",
                   help="convert just this post (repeatable; default: all)")
    p.add_argument("--clean", action="store_true",
                   help="delete archive/posts/ before converting")


def add_site_args(p, generator: str):
    """What the three exporters take on top of --archive: where the
    site goes, what it says about itself, and where the display copies
    of its images are built.

    --out is written in place rather than emptied first, so it can be a
    checkout of the published site kept in git: the exporter overwrites
    the files it generates, touches nothing else, and a run shows up
    there as a working-tree diff to read and commit. What that leaves
    behind is a page whose post has since left the archive, which
    --clean sweeps up (and every run reports either way)."""
    p.add_argument("--out", type=Path, default=None, metavar="DIR",
                   help="where to build the site; the files this step "
                        "generates are overwritten in place and nothing "
                        "else in DIR is touched, so DIR can be a checkout "
                        "of the published site (default: "
                        f"{default_out(generator)}/)")
    p.add_argument("--clean", action="store_true",
                   help="empty --out first, keeping .git/ and every file "
                        "git ignores there -- the site's own .gitignore "
                        "covers this generator's build output and caches. "
                        "This is what removes a page the archive no longer "
                        "has. Outside a git working tree, the build "
                        "directories are kept and the rest is deleted")
    p.add_argument("--site-inputs", type=Path, default=DEFAULT_SITE_INPUTS,
                   metavar="DIR",
                   help="the hand-written site inputs: site.toml and the "
                        "images it names (avatar, logo, favicon, share "
                        f"image) (default: {DEFAULT_SITE_INPUTS}/)")
    p.add_argument("--image-cache", type=Path, default=DEFAULT_IMAGE_CACHE,
                   metavar="DIR",
                   help="where display copies of oversized images are built "
                        "and kept, content-addressed, for re-runs and the "
                        "other exporters to reuse; they are hard-linked "
                        "into the site when DIR shares its filesystem, "
                        f"copied when it does not (default: "
                        f"{DEFAULT_IMAGE_CACHE}/)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--archive", default=DEFAULT_ARCHIVE, type=Path,
                        metavar="DIR",
                        help="the archive directory: raw/ and the "
                             "hand-written files beside it, and what convert "
                             "derives from them (posts/, posts.json, "
                             f"redirects.csv) (default: {DEFAULT_ARCHIVE}/)")
    ap.set_defaults(base=None)   # only fetch and all take the URL
    sub = ap.add_subparsers(dest="command", required=True)

    def parser(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    add_fetch_args(parser("fetch", help="download raw material into archive/raw/"))
    imp = parser("import-export",
                 help="merge a Medium account export into archive/raw/")
    imp.add_argument("export_path", type=Path, metavar="ZIP_OR_DIR",
                     help="the export zip from medium.com Settings -> Download your "
                          "information, a zip of just its posts/ folder, or an "
                          "unzipped copy / its posts/ directory")
    imp.add_argument("--all", action="store_true",
                     help="also import export posts that do not match a post already "
                          "in the archive, e.g. unlisted posts or posts from other "
                          "publications (default: only merge into fetched posts)")
    imp.add_argument("--drafts", action="store_true",
                     help="also import draft_*.html files (default: skip drafts)")
    ghost = parser("import-ghost",
                   help="recover a Ghost blog's posts from the Wayback "
                        "Machine into archive/raw/")
    ghost.add_argument("base", type=publication_url, metavar="URL",
                       help="the Ghost blog's root URL (often the publication's "
                            "own domain); every page the Wayback Machine ever "
                            "captured on this host is considered, and pages "
                            "whose HTML declares a Ghost generator are kept")
    ghost.add_argument("--urls", type=Path, metavar="FILE",
                       help="check only these original post URLs (one per line, "
                            "'#' comments) instead of scanning the whole host")
    ghost.add_argument("--limit", type=int, default=0, metavar="N",
                       help="stop after importing N new posts; 0 = no limit")
    ghost.add_argument("--force", action="store_true",
                       help="re-fetch posts already in the raw archive")
    ghost.add_argument("--delay", type=float, default=1.5, metavar="SECONDS",
                       help="sleep between Wayback requests; images sleep "
                            "delay/4 (default: 1.5)")
    ghost.add_argument("--no-images", action="store_true",
                       help="skip image downloads (convert will keep the "
                            "original, likely dead, URLs)")
    add_convert_args(parser("convert", help="convert archive/raw/ into archive/posts/"))
    add_site_args(parser("myst", help="build a MyST (mystmd) site in "
                        "site-myst/ from the converted posts; render with "
                        "`myst start` or `myst build --html`"), "myst")
    add_site_args(parser("hugo", help="build a Hugo site in site-hugo/ "
                        "from the converted posts; render with `hugo` "
                        "and `pagefind --site public`, or `hugo server`"),
                  "hugo")
    add_site_args(parser("pelican", help="build a Pelican site in "
                           "site-pelican/ from the converted posts; render "
                           "with `pelican` and `pagefind --site output`, or "
                           "`pelican -l` (needs `pip install pelican "
                           "markdown-it-py mdit-py-plugins pyyaml pillow`)"),
                  "pelican")
    cmp_p = parser("compare",
                   help="verify the page conversion against the account export, "
                        "offline; differences print as a unified patch on stdout "
                        "(redirect to a .patch file for a diff viewer); exits "
                        "non-zero if any post differs")
    cmp_p.add_argument("--only", action="append", metavar="URL",
                       help="compare just this post (repeatable; default: every post "
                            "that has both page.html and export.html)")
    cmp_p.add_argument("--state", action="store_true",
                       help="instead: verify the embedded-editor-state conversion "
                            "(the default body source for Medium pages) against "
                            "the account export, for every post that has both")
    cmp_p.add_argument("--ghost", action="store_true",
                       help="instead: diff each attached Ghost capture against the "
                            "post's Medium conversion, with Medium's mechanical "
                            "migration differences (typography, heading levels, "
                            "image renames, line wrapping) normalized away. "
                            "Informational (exit 0) -- what it reports is dropped "
                            "or edited content, to guide convert --prefer-ghost")
    lint_p = parser("lint", help="scan archive/posts/ for conversion-defect "
                                 "signatures (leftover Medium chrome, unclosed "
                                 "code fences, missing image files, remote CDN "
                                 "images); exits non-zero if any are found")
    lint_p.add_argument("--embeds", action="store_true",
                        help="also report, as problems, every embed whose "
                             "content is not in the archive: one that "
                             "converted to a bare [embed: url] link (the "
                             "sites show the link, not the video, tweet or "
                             "gist), and one the post's body source dropped "
                             "that the page's editor state carries")
    lint_p.add_argument("--seo", action="store_true",
                        help="also warn about what an SEO plugin's page "
                             "analysis would: a missing or overlong "
                             "description, an overlong title, images without "
                             "alt text, a post with no cover image, two "
                             "posts with one title")
    stats_p = parser("stats", help="summarize the converted archive "
                                   "(posts, provenance, authors, lengths, tags)")
    stats_p.add_argument("--top", type=int, default=15, metavar="N",
                         help="how many authors/tags to list (default: 15)")
    stats_p.add_argument("--tags", action="store_true",
                         help="list every tag with its post count instead of "
                              "the top N -- the worklist for curating "
                              "archive/tags.json (see convert)")
    both = parser("all", help="fetch then convert")
    add_fetch_args(both)
    add_convert_args(both)
    args = ap.parse_args()

    if args.command in ("fetch", "all"):
        cmd_fetch(args)
    if args.command == "import-export":
        cmd_import_export(args)
    if args.command == "import-ghost":
        cmd_import_ghost(args)
    if args.command in ("convert", "all"):
        cmd_convert(args)
    if args.command == "myst":
        cmd_myst(args)
    if args.command == "hugo":
        cmd_hugo(args)
    if args.command == "pelican":
        cmd_pelican(args)
    if args.command == "compare":
        cmd_compare(args)
    if args.command == "lint":
        cmd_lint(args)
    if args.command == "stats":
        cmd_stats(args)
