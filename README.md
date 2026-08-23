# medium-archive

Archive a Medium publication as raw HTML plus a Markdown conversion, to
support migrating a blog off Medium.

It works in independent steps:

* **`fetch`** pulls raw material from Medium — each post's page HTML, its RSS
  feed item, and full-resolution images, unmodified — into `<out>/raw/`.
  Fetching is incremental and resumable, so it can be interrupted and re-run,
  and re-running later picks up only new posts.
* **`import-export`** (optional) merges a Medium account export — the zip
  from medium.com → Settings → Download your information — into `<out>/raw/`,
  matched to fetched posts by Medium id. An export holds everything its
  author ever wrote, so by default only files matching a post already in
  the archive are merged (`--all` imports the rest, `--drafts` includes
  drafts); run it once per author for a multi-author publication. Export
  post files are the editor's own clean HTML with the exact publish
  timestamp, so they become the preferred body source; the scraped page
  still contributes tags, the updated date, the publication canonical URL,
  and the images.
* **`import-ghost`** (optional) recovers a Ghost blog's posts from the
  Wayback Machine — a separate import path from `fetch`: fetch handles
  Medium URLs from the live site, import-ghost handles Ghost URLs that
  survive only as web.archive.org captures (a common case: the publication
  lived on Ghost, often on the same domain, before its Medium era, and only
  some posts were migrated). Every page ever captured on the host is
  considered, and pages whose HTML declares a Ghost generator are kept, so
  it works for any Ghost version or permalink style. A post that was
  migrated to Medium — recognized by slug or title — gets its Ghost capture
  attached to the archived post as `ghost.html`, alongside the Medium page
  (like `import-export` attaches `export.html`): the Ghost original often
  has cleaner code blocks, the exact original timestamp, and the old URL
  for redirects. `compare --ghost` diffs the two conversions per post, and
  `convert --prefer-ghost` uses the Ghost body. Posts with no archived
  counterpart are imported as posts of their own. Images are recovered
  from Wayback captures too.
* **`compare`** (optional) verifies the page conversion offline: for every
  post with both sources, it converts the body from the scraped page and
  from the export independently and reports any disagreement. The two
  should be identical, so a difference means new page chrome or a
  conversion bug. It exits non-zero when posts differ, so it can gate
  scripts.
* **`convert`** turns the raw archive into Markdown files with front matter
  and local images in `<out>/posts/`, plus a `posts.json` manifest and a
  `redirects.csv` mapping old Medium URLs to the new post directories.
  It never touches the network, so it can be re-run freely while tuning the
  conversion (selectors, Markdown style, output layout) without hitting
  Medium again.
* **`lint`** scans the converted posts for conversion-defect signatures —
  leftover Medium chrome, unclosed code fences, images referenced but
  missing on disk, remote Medium CDN images. It exits non-zero when a
  defect is found, so regressions surface on every convert instead of
  waiting for a reader.
* **`stats`** summarizes the converted archive: posts per year, provenance
  (how each post was discovered — feed, sitemap, Wayback, Ghost era — which
  sources were recovered for it, and which one each body was converted
  from), authors, article length quartiles, tag frequencies, image counts.

The `raw/` layer is the source of truth — the only part that cannot be
regenerated once the Medium site is gone — and everything else is derived
from it. A `README.md` written into the archive documents the full layout,
the front matter fields, and the caveats.

## Installation

With [uv](https://docs.astral.sh/uv/), run it straight from a checkout:

```sh
uv run medium-archive --help
```

Or install it with pip:

```sh
pip install .
medium-archive --help
```

## Usage

```sh
medium-archive fetch https://blog.example.com/              # everything, newest first
medium-archive fetch https://blog.example.com/ --limit 5    # smoke test
medium-archive fetch https://blog.example.com/ --start 2024-12-31 --end 2024-01-01
medium-archive import-export medium-export.zip
medium-archive import-ghost https://blog.example.com/       # Ghost-era captures
medium-archive compare                                      # page vs export check
medium-archive convert                                      # raw -> posts/
medium-archive lint                                         # check for conversion defects
medium-archive stats                                        # summarize the archive
medium-archive all https://blog.example.com/ --limit 5      # fetch then convert
```

Only `fetch` and `all` need the publication root URL; `/sitemap/sitemap.xml`
and `/feed` must resolve under it. The other steps work offline from the
archive alone. `--out DIR` (default: `medium_export`) sets the archive root
on every step. See `medium-archive fetch --help` and
`medium-archive convert --help` for the per-step options: date windows,
limits, fetch delays, skipping posts already in earlier archives, converting
a single post, and more.

## Recommended workflow

To archive a publication comprehensively — including posts Medium itself no
longer lists — work through the steps in order:

1. **Smoke-test** the whole pipeline on a handful of posts and eyeball the
   result before committing to a long run:

   ```sh
   medium-archive all https://blog.example.com/ --limit 5 --out myblog
   ```

2. **Fetch everything.** Discovery merges the sitemap, the RSS feed, and the
   Wayback Machine's index, so old posts missing from Medium's truncated
   sitemap are found automatically. Fetching is incremental: interrupt and
   re-run freely, raise `--delay` if Medium answers 429, and repeat until a
   run reports `0 new`:

   ```sh
   medium-archive fetch https://blog.example.com/ --out myblog
   ```

3. **Review `raw/missing.json`** if the fetch summary mentions it: those
   posts survive only as web.archive.org captures. Open each entry's
   `wayback_url`, decide whether the post matters, and save what does by
   hand — `fetch` cannot recover them. (Mangled URL variants the crawler
   once saw — a truncated id, a stray hyphen — are matched to archived
   posts and unflagged automatically; for anything left, the `wayback_url`
   shows quickly whether there is a real post behind it.)

4. **Merge account exports** (medium.com → Settings → Download your
   information), once per author for a multi-author publication, then let
   `compare` verify the scraped pages against the export's clean HTML:

   ```sh
   medium-archive import-export alice-export.zip --out myblog
   medium-archive compare --out myblog
   ```

   This step is optional but worthwhile: export bodies convert most
   faithfully and carry exact publish timestamps.

5. **Recover the blog's Ghost history**, if it has one (the earliest posts
   in the Wayback Machine reveal it — a `generator` meta tag names the
   platform). Ghost posts that were never migrated to Medium exist nowhere
   else; migrated ones get their Ghost original attached to the archived
   post, and `compare --ghost` shows where that original converts better
   than Medium's copy (then cherry-pick with
   `convert --prefer-ghost --only URL`):

   ```sh
   medium-archive import-ghost https://blog.example.com/ --out myblog
   medium-archive compare --ghost --out myblog
   ```

6. **Convert and check the totals.** `stats` shows posts per year, authors,
   and tags — compare the year counts against the publication's own archive
   pages or your memory of its history; a gap year means undiscovered
   posts, which can be seeded from any URL list via `fetch --urls FILE`:

   ```sh
   medium-archive convert --out myblog
   medium-archive lint --out myblog
   medium-archive stats --out myblog
   ```

7. **Back up `raw/`** — it is the only part that cannot be regenerated once
   the Medium site is gone — and re-run `fetch` periodically until the day
   the blog actually moves, to pick up posts published in the meantime.

## Notes

* Discovery merges the sitemap with the RSS feed (roughly the ten most
  recent posts, with full, cleaner bodies) and the Wayback Machine's index
  of past captures (web.archive.org). Medium's sitemap only lists the last
  few years of posts; older posts are still live on Medium but invisible to
  sitemap+feed discovery, so the Wayback index recovers their URLs — the
  posts themselves are still fetched from the live site (`--no-wayback`
  skips this source, and `--urls FILE` can seed URLs collected any other
  way). The real publish date from each page is checked against
  `--start`/`--end` after fetching, since sitemap dates are modification
  dates and Wayback dates are first-capture dates.
* Posts that discovery finds but Medium no longer serves — deleted or
  unpublished — are flagged in `raw/missing.json`, with a `wayback_url`
  pointing at their web.archive.org captures for manual recovery.
  Medium serves its not-found page with HTTP 200, so gone posts are
  detected from the page content, not just the status code. A gone post
  whose slug is archived under another id — likely deleted and republished
  — is annotated with `same_slug_archived`. Re-running `fetch` re-checks
  flagged posts and unflags any that reappear.
* Medium boilerplate — the "was originally published on Medium" footer,
  stat tracking pixels, clap/share UI — is stripped during `convert`; it is
  still present in the raw pages. Embedded gists and other iframes become
  links and need manual replacement.
* Medium sometimes serves a post page as its bare application shell — no
  server-rendered article, no JSON-LD, page title just "Medium". `convert`
  recovers such posts from the page's embedded editor state
  (`window.__APOLLO_STATE__`), which still carries the full paragraph
  list, markups, title, timestamps, author and tags (`body_source:
  state`). Only the images are lost to the shell: they were never
  fetched, so the body keeps remote URLs until the post is re-fetched.
* Medium rate-limits and may serve a bot wall. A 429 is not retried —
  fetch reports it (with the server's `Retry-After` hint, when sent) and
  moves on; raise `--delay` and re-run to resume.

## Layout

```
src/medium_archive/
  cli.py         argument parsing and the entry point
  fetch.py       the fetch step: download posts into <out>/raw/
  export.py      Medium account exports: parsing and the import-export step
  ghost.py       the import-ghost step: recover Ghost posts from the Wayback Machine
  convert.py     the convert step: <out>/raw/ -> Markdown in <out>/posts/
  compare.py     the compare step: verify page vs export conversion agreement
  lint.py        the lint step: scan converted posts for defect signatures
  stats.py       the stats step: summarize the converted archive
  discovery.py   find post URLs via the sitemap tree, RSS feed, and Wayback Machine
  pages.py       post page parsing: metadata extraction, body cleanup
  images.py      image source extraction and filenames
  net.py         HTTP session and retrying GET
  dates.py       date parsing and the --start/--end window check
  urls.py        Medium URL and post-identifier helpers
  readme.py      the README.md written into each archive
tests/           offline tests (canned HTTP responses, no network);
                 run with `uv run pytest`
```
