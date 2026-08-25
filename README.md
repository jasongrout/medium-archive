# medium-archive

Archive a Medium publication as raw HTML plus a Markdown conversion, to
support migrating a blog off Medium.

It works in independent steps:

* **`fetch`** pulls raw material from Medium — each post's page HTML, its RSS
  feed item, full-resolution images, and the media behind gist embeds (the
  gist's files, via medium.com/media and the GitHub gists API), unmodified —
  into `<out>/raw/`. Fetching is incremental and resumable, so it can be
  interrupted and re-run; re-running later picks up only new posts, and
  backfills embed media for posts archived before it was collected.
* **`import-export`** (optional) merges a Medium account export — the zip
  from medium.com → Settings → Download your information, or a zip of just
  its `posts/` folder — into `<out>/raw/`, matched to fetched posts by
  Medium id. An export holds everything its
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
  Medium again. An optional hand-written `<out>/tags.json` cleans up the
  Medium tags on the way into front matter — `"drop"` removes tags that
  only made sense on medium.com, `"rename"` consolidates variants onto a
  common tag — reproducibly, with `raw/` keeping the originals; a stale
  entry that matches no post aborts a full run, like a fixup that no
  longer applies.
* **`myst`** (optional) builds a [MyST](https://mystmd.org) site in
  `<out>/site/` from the converted posts: one page per post (its filename
  is the page's URL slug), a chronological landing page, a year-grouped
  table of contents, and a `site/redirects.csv` mapping every old inbound
  path — Medium slug+id, `/p/<id>`, Ghost-era — to its page URL. Links
  between posts of the publication are rewritten from Medium URLs to site
  pages, front matter is reshaped to MyST's schema, and prose MyST would
  misparse (`@handle` mentions as citations, paired `$` signs as math) is
  escaped. Like `convert` it never touches the network, so the whole site
  reproduces from `raw/` + `fixups/`: `convert` then `myst`. Site-wide
  text (title, description, landing-page intro) comes from an optional
  hand-written `<out>/site.json`. Render the result with `myst start` or
  `myst build --html` inside `<out>/site/` (`npm install -g mystmd`).
* **`hugo`**, **`zola`** and **`pelican`** (optional) do the same for
  those generators, into `<out>/site-hugo/`, `<out>/site-zola/` and
  `<out>/site-pelican/` — same page URLs (`/posts/<slug>/`), same link
  rewriting, same `site.json`, and a `redirects.csv` in each site — so
  the generators can be compared on identical content. The **hugo and
  pelican sites are the preferred targets**: they carry the full
  feature set described below (the card theme, Pagefind search, image
  optimization, redirect stubs, capped full-content feeds); the myst
  and zola sites are maintained as simpler alternates. `hugo` and
  `pelican` ship the same self-contained card-grid blog theme (in the
  vein of pytorch.org/blog), in light and dark palettes with a
  light/dark/system picker in the header — the choice persists per
  browser, and with none stored the system scheme decides: a
  paginated home of cover-image cards —
  each post's first still image of sane size, chosen by header-sniffing
  dimensions — tag links, excerpt and byline per card; article pages;
  tag/author card listings with chip indexes; and a `/search/` page
  wired to [Pagefind](https://pagefind.app) — run `pagefind --site
  public|output` after building for full-text search served as a results
  page with highlighted, in-context excerpts and per-section
  sub-results. Images are optimized the same way on both: 640×360
  cover thumbnails baked at export time through Pillow (`pip install
  pillow`, or the `covers` extra) — center-cropped when the source is
  near 16:9, letterboxed when far from it, so a wide wordmark or a
  square logo keeps its content instead of losing it to the crop
  (padded with the image's own border color when the border is
  uniform, over a blurred fill of the image otherwise, and never
  upscaled past 2×) — and responsive, lazily-loaded webp variants
  (480/736/1104 px `srcset`, never upscaled, with real width/height)
  for still body images: Hugo natively through its image pipeline
  and a render hook, Pelican by a plugin embedded in the generated
  config after each build, mtime-cached so rebuilds only touch
  changed images. All four sites
  carry display copies of the images, not the archival originals:
  anything past a size cap is resized down as it is placed — stills to
  a 1600 px longest edge through Pillow, animated gifs (which get no
  srcset variants and dominate the built sites byte-wise) to 1104 px
  through gifsicle when it is installed — built once into
  `<out>/.image-cache/` and hard-linked into every site. `raw/` and
  `posts/` keep full resolution; `site.json` tunes or disables the
  caps (`"images": {"still_max_edge": N, "animated_max_edge": N}`,
  0 = off). All three render
  every old inbound path (Medium slug+id, `/p/<id>`, Ghost-era) as a
  redirect stub that works on any static host — `hugo` and `zola`
  through their `aliases` front matter, `pelican` through a small
  plugin embedded in the generated config that turns the exported
  `redirects.csv` into the same stub pages after each build. Tag *and*
  author pages come with per-term RSS/Atom feeds on all three
  (`pelican`'s from Pelican's own tag/author machinery); every feed
  carries the 20 most recent posts with their full content — like the
  publication's original Medium feed — with feed URLs absolutized
  against `base_url` and responsive `srcset` markup stripped, since a
  feed announces new posts while the site itself is the archive.
  `zola` keeps a
  smaller
  list-style theme with its generator's built-in search index wired to
  a search box. Any of the generated themes can be replaced by a real
  one without touching `content/`. Render with `hugo server`,
  `zola serve`, or `pelican -l` respectively.

  The `hugo` step can also target a real theme, named in `site.json`:

  ```json
  "hugo": {"theme": "dream",
           "theme_repo": "https://github.com/g1eny0ung/hugo-theme-dream",
           "avatar": "avatar.png",            // archive-relative, optional
           "params": {"motto": "..."}}        // extra/override params
  ```

  The exporter then emits the theme's config instead of its own layouts;
  clone the theme once into `<out>/site-hugo/themes/<name>` (regeneration
  preserves `themes/`, and the exporter prints the clone command while it
  is missing). The [Dream theme](https://hugo-theme-dream.g1en.site)
  (Hugo ≥ 0.158) gets first-class support: each post's first still image
  of sane size (animated gifs and 25-megapixel screenshots are passed
  over) becomes its summary-card cover and og:image, baked to the same
  640×360 crop-or-letterbox thumbnail as the built-in theme's, authors
  get per-post bylines with profile links, Dream's built-in search page
  and archives timeline are enabled, an Authors nav item points at the
  author taxonomy, `siteStartYear` is derived from the oldest post, and
  the `avatar` image is copied into the site for the header.
* **`lint`** scans the converted posts for conversion-defect signatures —
  leftover Medium chrome, unclosed code fences, images referenced but
  missing on disk, remote Medium CDN images, embeds whose media was never
  archived. It exits non-zero when a defect is found, so regressions
  surface on every convert instead of waiting for a reader.
* **`stats`** summarizes the converted archive: posts per year, provenance
  (how each post was discovered — feed, sitemap, Wayback, Ghost era — which
  sources were recovered for it, and which one each body was converted
  from), authors, article length quartiles, tag frequencies, image counts.
  `stats --tags` lists every tag with its post count — the worklist for
  curating `tags.json`.

The `raw/` layer is the source of truth — the only part that cannot be
regenerated once the Medium site is gone — and everything else is derived
from it. A `README.md` written into the archive documents the full layout,
the front matter fields, and the caveats. If the archive lives in version
control, the small derived files `posts.json` and `redirects.csv` are
worth committing anyway: their diffs show what a `fixups/` or `tags.json`
change did to every post, while the bulky derived trees (`posts/`, the
site directories) are better gitignored and regenerated.

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
medium-archive myst                                         # posts/ -> site/
medium-archive hugo                                         # posts/ -> site-hugo/
medium-archive zola                                         # posts/ -> site-zola/
medium-archive pelican                                      # posts/ -> site-pelican/
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
  still present in the raw pages. Embedded iframes become links and need
  manual replacement — except gist embeds, whose files `fetch` archives
  into `raw/<id>/media/` and `convert` inlines as code fences (a gist's
  content exists nowhere in the page itself; Medium's state names only an
  opaque media resource id). A gist embed whose media is not yet archived
  converts to a link to the gist (export and Ghost bodies, which name it)
  or a `[missing embed: <name>]` placeholder (the state, which doesn't);
  `lint` flags the placeholders until a `fetch` re-run backfills the media.
  Code fences carry the language Medium recorded for the block
  (`codeBlockMetadata`), and user mentions resolve to the author's Medium
  profile.
* Every Medium page carries its post twice: rendered into the visible
  HTML, and as data in its embedded editor state
  (`window.__APOLLO_STATE__`) — the ordered paragraph list with markup
  spans, image ids, code blocks, plus title, timestamps, author and
  tags. `convert` prefers the state (`body_source: state`) over the
  rendered HTML: it has no chrome to strip and keeps what the renderer
  destroys — the full text span of a link containing a code fragment,
  bold on code, and iframe embeds that an un-hydrated capture drops
  entirely. It also survives when Medium serves the bare application
  shell (no server-rendered article, page title just "Medium"), which is
  how shell-only captures convert at all — though a shell's images were
  never fetched, so its body keeps remote URLs until re-fetched.
  `compare --state` verifies the state conversion against account
  exports, like plain `compare` does for the page conversion; the
  rendered page remains the fallback and is available with
  `convert --prefer-page`.
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
  myst.py        the myst step: <out>/posts/ -> a MyST site in <out>/site/
  hugo.py        the hugo step: <out>/posts/ -> a Hugo site in <out>/site-hugo/
  zola.py        the zola step: <out>/posts/ -> a Zola site in <out>/site-zola/
  pelican.py     the pelican step: <out>/posts/ -> a Pelican site in <out>/site-pelican/
  sites.py       machinery shared by the site exporters: page slugs, the
                 in-publication link map, redirect maps, site.json
  compare.py     the compare step: verify page vs export conversion agreement
  lint.py        the lint step: scan converted posts for defect signatures
  stats.py       the stats step: summarize the converted archive
  discovery.py   find post URLs via the sitemap tree, RSS feed, and Wayback Machine
  pages.py       post page parsing: metadata extraction, body cleanup
  state.py       convert a post from the page's embedded editor state
  images.py      image source extraction and filenames
  net.py         HTTP session and retrying GET
  dates.py       date parsing and the --start/--end window check
  urls.py        Medium URL and post-identifier helpers
  tags.py        hand-curated tag cleanup (<out>/tags.json), applied by convert
  readme.py      the README.md written into each archive
tests/           offline tests (canned HTTP responses, no network);
                 run with `uv run pytest`
```
