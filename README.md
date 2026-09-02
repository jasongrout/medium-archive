# medium-archive

Archive a Medium publication as raw HTML plus a Markdown conversion, to
support migrating a blog off Medium.

The tool runs as independent steps. Only `fetch` (and `all`) touches the
network. Every other step works offline from the archive, so the
conversion can be tuned and re-run without hitting Medium again.

## Steps

**`fetch`** pulls raw material from Medium into `<out>/raw/`: each post's
page HTML, its RSS feed item, full-resolution images, and the media
behind gist embeds (the gist's files, via medium.com/media and the
GitHub gists API). Nothing is modified. Fetching is incremental and
resumable, so it can be interrupted and re-run. A later run picks up
only new posts, and backfills embed media for posts archived before it
was collected.

**`import-export`** (optional) merges a Medium account export into
`<out>/raw/`. The export is the zip from medium.com → Settings →
Download your information, or a zip of just its `posts/` folder. Files
are matched to fetched posts by Medium id. An export holds everything
its author ever wrote, so by default only posts already in the archive
are merged; `--all` imports the rest and `--drafts` includes drafts.
Run it once per author for a multi-author publication. Export files are
the editor's own clean HTML with the exact publish timestamp, so they
become the preferred body source. The scraped page still contributes
tags, the updated date, the publication canonical URL, and the images.

**`import-ghost`** (optional) recovers a Ghost blog's posts from the
Wayback Machine. This is a separate path from `fetch`: fetch handles
Medium URLs on the live site, import-ghost handles Ghost URLs that
survive only as web.archive.org captures. The common case is a
publication that lived on Ghost, often on the same domain, before its
Medium era, with only some posts migrated. Every page ever captured on
the host is considered, and pages whose HTML declares a Ghost generator
are kept, so any Ghost version or permalink style works. A post that
was migrated to Medium, recognized by slug or title, gets its Ghost
capture attached to the archived post as `ghost.html`, the way
`import-export` attaches `export.html`. The Ghost original often has
cleaner code blocks, the exact original timestamp, and the old URL for
redirects. `compare --ghost` diffs the two conversions per post, and
`convert --prefer-ghost` uses the Ghost body. Posts with no Medium
counterpart are imported as posts of their own. Images are recovered
from Wayback captures too.

**`compare`** (optional) verifies the page conversion offline. For every
post with both sources it converts the body from the scraped page and
from the export independently and reports any disagreement. The two
should be identical, so a difference means new page chrome or a
conversion bug. It exits non-zero when posts differ, so it can gate
scripts.

**`convert`** turns the raw archive into Markdown files with front matter
and local images in `<out>/posts/`, plus a `posts.json` manifest and a
`redirects.csv` mapping old Medium URLs to the new post directories. It
never touches the network. An optional hand-written `<out>/tags.json`
cleans up the Medium tags on the way into front matter; see
[Tag cleanup](#tag-cleanup-tagsjson).

**`myst`**, **`hugo`** and **`pelican`** (optional) each build a
ready-to-render site from the converted posts, in `<out>/site-myst/`,
`<out>/site-hugo/` and `<out>/site-pelican/`. All three give the posts
the same page URLs, rewrite links between posts of the publication to
those pages, read the same `site.json`, and write a `redirects.csv`
into the site, so the generators can be compared on identical content.
The hugo and pelican sites are the preferred targets and carry the full
feature set. The myst site is a simpler alternate. See
[Generated sites](#generated-sites).

**`lint`** scans the converted posts for conversion-defect signatures:
leftover Medium chrome, unclosed code fences, images referenced but
missing on disk, remote Medium CDN images, embeds whose media was never
archived. It exits non-zero when a defect is found, so regressions
surface on every convert instead of waiting for a reader.

**`stats`** summarizes the converted archive: posts per year, provenance
(how each post was discovered, which sources were recovered for it, and
which one each body was converted from), authors, article length
quartiles, tag frequencies, image counts. `stats --tags` lists every
tag with its post count, the worklist for curating `tags.json`.

## The archive

`raw/` is the source of truth and the only part that cannot be
regenerated once the Medium site is gone. Everything else is derived
from it. A `README.md` written into the archive documents the full
layout, the front matter fields, and the caveats.

If the archive lives in version control, commit the small derived files
`posts.json` and `redirects.csv` anyway. Their diffs show what a
`fixups/` or `tags.json` change did to every post. The bulky derived
trees (`posts/` and the site directories) are better gitignored and
regenerated.

The archive's own README describes the archive. What the generated
sites contain is documented here, so that a theme change does not
oblige every archive downstream to regenerate its README.

## Tag cleanup (`tags.json`)

Medium tags arrive as slugs, and many only made sense on medium.com. An
optional hand-written `<out>/tags.json` cleans them up as `convert`
writes each post's front matter, reproducibly, while `raw/` keeps the
originals. Its sections:

- `"drop"` removes tags everywhere.
- `"rename"` maps variants onto a common tag.
- `"imply"` states that one tag entails another everywhere it appears:
  every `jupytercon` post is an `events` post.
- `"add"` puts tags on specific posts by slug, for the plain topic a
  post's Medium tags never named.
- `"remove"` takes a tag off specific posts by slug, for a tag that
  does not describe the post it landed on.
- `"display"` gives a tag the name a site shows it under
  (`"ipython": "IPython"`, `"jupyter-notebook": "Jupyter Notebook"`).
  It changes nothing about the tag itself: the tag stays one slug
  through `posts.json`, the rest of `tags.json` and every
  `/tags/<tag>/` URL. A tag without an entry shows as itself with its
  hyphens as spaces (`open-science` → "open science").

An over-applied tag can be split either way: drop it everywhere and
re-add it where deserved, or keep it and remove it from the handful of
posts that only mention the topic. A stale entry that changes no post
aborts a full run, like a fixup that no longer applies. `posts.json`
and every derived site inherit the cleaned tags.

## Generated sites

### The card theme (hugo and pelican)

`hugo` and `pelican` ship the same self-contained card-grid blog theme,
in the vein of pytorch.org/blog, in light and dark palettes. A
light/dark/system picker in the header persists the choice per browser;
with none stored, the system scheme decides. The theme provides:

- A paginated home of cover-image cards. Each card shows the post's
  first still image of sane size (chosen by header-sniffing
  dimensions), tag links, excerpt and byline.
- Article pages, tag and author card listings, and chip indexes
  sortable by name or by post count.
- An optional header logo and browser-tab icon: `site.json`'s
  `"avatar"` and `"favicon"`, archive-relative image paths copied into
  the site so it stays self-contained.
- An optional site-wide announcement banner above the header, from
  `site.json`'s `"announcement"`: either an http(s) URL fetched
  client-side or literal HTML. The URL form is the mechanism behind
  Sphinx's `announcement` theme option, so one file such as
  `https://jupyter.org/assets/banner.html` can drive a blog and its
  project's documentation sites alike, and empty content hides the
  banner. Dismissal persists per browser, and a changed announcement
  clears it.
- Click-to-zoom body images. Clicking an image (or pressing Enter on
  it) whose original holds more detail than the article column shows
  opens it full size in a modal. This is the one Medium reading
  affordance the archive would otherwise lose, since Medium's own
  "click to view image in full size" hint is stripped as chrome on
  conversion.
- Share links under every article's byline and again at its foot:
  LinkedIn, Facebook, Bluesky, Mastodon and email, under each network's
  own logomark. A hover deepens the mark rather than recoloring it,
  since tinting a logo to the site accent is against most brand
  guidelines. The links are built from the post's absolute URL, so
  `base_url` has to be set for them to point anywhere real; the
  exporters say so on stderr when it is not. A toot has no single
  address to be sent to, so the Mastodon link asks the reader for their
  server and remembers it per browser, accepting a pasted server URL or
  an `@you@server` handle as readily as a bare domain.
- Open Graph metadata on every page: `og:title`, `og:description`,
  `og:url`, the baked 640×360 cover as `og:image`, `article:` dates and
  authors, and a canonical link. LinkedIn's and Facebook's share URLs
  carry only the page address and build their whole share box from
  these tags, so they are the difference between a share link that
  works and one that posts a bare URL.
- A `/search/` page wired to [Pagefind](https://pagefind.app). Run
  `pagefind --site public` (hugo) or `pagefind --site output` (pelican)
  after building for full-text search served as a results page with
  highlighted, in-context excerpts and per-section sub-results.

Render with `hugo server` or `pelican -l`.

### Images

All three sites carry display copies of the images, not the archival
originals. `raw/` and `posts/` keep full resolution. Copies are built
once into `<out>/.image-cache/` and hard-linked into every site.

- Card covers are 640×360 thumbnails baked at export time through
  Pillow (`pip install pillow`, or the `covers` extra). A source near
  16:9 is center-cropped. A source far from it, such as a wide wordmark
  or a square logo, is letterboxed instead so its content survives:
  padded with the image's own border color when the border is uniform,
  over a blurred fill of the image otherwise, and never upscaled past
  2×.
- Photographic body images get responsive, lazily-loaded webp variants
  (480/736/1104 px `srcset`, never upscaled, with real width/height).
  Hugo does this natively through its image pipeline and a render hook.
  Pelican does it through a plugin embedded in the generated config
  that runs after each build, mtime-cached so rebuilds only touch
  changed images. Line art and animated gifs are left out of the ladder
  but carry real width/height so click-to-zoom can measure them.
- Line art, meaning the charts, screenshots and diagrams most of an
  archive's PNGs are, keeps every pixel at its own resolution as
  lossless webp. That is about 60% smaller than the source PNG and
  pixel-exact. Downscaling is what makes 9 px axis labels unreadable,
  and it barely saves bytes on flat color anyway.
- Photographs are resized past a size cap as they are placed, to a
  1600 px longest edge through Pillow, and lossily re-encoded. Animated
  gifs get no srcset variants and dominate the built sites byte-wise,
  so they are resized to 1104 px through gifsicle when it is installed.
- `site.json` tunes or disables the caps:
  `"images": {"still_max_edge": N, "animated_max_edge": N}`, with 0
  meaning off.

### Redirects and feeds

Both card-theme sites render every old inbound path (Medium slug+id,
`/p/<id>`, Ghost-era) as a redirect stub that works on any static host.
Hugo does it through `aliases` front matter. Pelican has no aliases
feature, so a small plugin embedded in the generated config turns the
exported `redirects.csv` into the same stub pages after each build.

Tag and author pages come with per-term RSS/Atom feeds on both,
pelican's from its own tag/author machinery. Each feed is linked from
its own page by the RSS mark that also serves as the header's feed
link. Every feed carries the 20 most recent posts with their full
content, like the publication's original Medium feed. Feed URLs are
absolutized against `base_url` and responsive `srcset` markup is
stripped: a feed announces new posts, while the site itself is the
archive.

### The MyST site

`myst` builds a [MyST](https://mystmd.org) site: one page per post, a
cover-image gallery landing page, a chronological `archive` page, a
year-grouped table of contents, and a `site-myst/redirects.csv`.

The gallery shows every post as a card, newest first, through the
[myst-listing](https://contrib.mystmd.org/myst-listing/) plugin. Each
post's first still image of sane size is baked to the same 640×360
thumbnail as the card theme's and doubles as the page's social-card
image. A small generated companion plugin,
`site-myst/listing-covers.mjs`, turns the gallery's cover backgrounds
into real image nodes so mystmd's image pipeline serves the local
thumbnails.

`redirects.csv` maps every old inbound path to the URL mystmd actually
serves. mystmd caps slugs at 50 characters and strips them to
`[a-z0-9-]`, so the exporter replicates its slug rules, collision
numbering included, rather than assuming filename equals URL. Links
between posts of the publication are rewritten to site pages, front
matter is reshaped to MyST's schema, and prose MyST would misparse is
escaped: `@handle` mentions read as citations, paired `$` signs as
math.

Like `convert`, the step never touches the network, so the whole site
reproduces from `raw/` plus `fixups/`. mystmd downloads the pinned
listing plugin at build time, like the site theme itself. Render with
`myst start` or `myst build --html` inside `<out>/site-myst/`
(`npm install -g mystmd`).

## `site.json`

Hand-written, versioned with the archive, and read by all three
exporters. It holds everything about a built site that belongs to the
publication rather than the tool. Every key is optional.

| key | what it does |
|-----|--------------|
| `title` | site title: the header, `<title>`, and every feed's name |
| `description` | tagline under the title, and the feeds' description |
| `intro` | landing-page blurb (Markdown), rendered by the myst and hugo landing pages |
| `base_url` | **the domain the site is served from**, e.g. `"https://blog.example.com"`. Everything absolute is built from it: feed URLs, redirect stubs, the Open Graph tags, the per-post share links. Set it before deploying and re-run the exporter. Unset, the exporters warn and fall back to a placeholder, so share links and social previews point at a domain you do not own |
| `avatar` | archive-relative image path for the header logo |
| `favicon` | archive-relative image path for the browser-tab icon |
| `announcement` | site-wide banner: an http(s) URL fetched client-side, or literal HTML |
| `images` | display-copy size caps: `{"still_max_edge": N, "animated_max_edge": N}`, `0` to disable |
| `hugo` | hugo-specific settings: `locale`, per-exporter `avatar`/`favicon`, and extra `params` for the generated config |

The `hugo` section in full:

```json
"hugo": {"locale": "en",                    // defaultContentLanguage
         "avatar": "avatar.png",            // overrides the top-level key
         "favicon": "favicon.ico",          // overrides the top-level key
         "params": {"motto": "..."}}        // extra/override [params]
```

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
medium-archive myst                                         # posts/ -> site-myst/
medium-archive hugo                                         # posts/ -> site-hugo/
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

To archive a publication comprehensively, including posts Medium itself
no longer lists, work through the steps in order:

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

3. **Review `raw/missing.json`** if the fetch summary mentions it. Those
   posts survive only as web.archive.org captures. Open each entry's
   `wayback_url`, decide whether the post matters, and save what does by
   hand; `fetch` cannot recover them. Mangled URL variants the crawler
   once saw, such as a truncated id or a stray hyphen, are matched to
   archived posts and unflagged automatically. For anything left, the
   `wayback_url` shows quickly whether there is a real post behind it.

4. **Merge account exports** (medium.com → Settings → Download your
   information), once per author for a multi-author publication, then let
   `compare` verify the scraped pages against the export's clean HTML:

   ```sh
   medium-archive import-export alice-export.zip --out myblog
   medium-archive compare --out myblog
   ```

   This step is optional but worthwhile: export bodies convert most
   faithfully and carry exact publish timestamps.

5. **Recover the blog's Ghost history**, if it has one. The earliest
   posts in the Wayback Machine reveal it: a `generator` meta tag names
   the platform. Ghost posts that were never migrated to Medium exist
   nowhere else. Migrated ones get their Ghost original attached to the
   archived post, and `compare --ghost` shows where that original
   converts better than Medium's copy. Cherry-pick those with
   `convert --prefer-ghost --only URL`.

   ```sh
   medium-archive import-ghost https://blog.example.com/ --out myblog
   medium-archive compare --ghost --out myblog
   ```

6. **Convert and check the totals.** `stats` shows posts per year, authors,
   and tags. Compare the year counts against the publication's own archive
   pages or your memory of its history. A gap year means undiscovered
   posts, which can be seeded from any URL list via `fetch --urls FILE`:

   ```sh
   medium-archive convert --out myblog
   medium-archive lint --out myblog
   medium-archive stats --out myblog
   ```

7. **Back up `raw/`.** It is the only part that cannot be regenerated once
   the Medium site is gone. Re-run `fetch` periodically until the day the
   blog actually moves, to pick up posts published in the meantime.

## Notes

* Discovery merges three sources: the sitemap, the RSS feed (roughly the
  ten most recent posts, with full, cleaner bodies), and the Wayback
  Machine's index of past captures. Medium's sitemap only lists the last
  few years of posts. Older posts are still live on Medium but invisible
  to sitemap and feed discovery, so the Wayback index recovers their
  URLs; the posts themselves are still fetched from the live site.
  `--no-wayback` skips that source, and `--urls FILE` can seed URLs
  collected any other way. The real publish date from each page is
  checked against `--start`/`--end` after fetching, since sitemap dates
  are modification dates and Wayback dates are first-capture dates.
* Posts that discovery finds but Medium no longer serves, deleted or
  unpublished, are flagged in `raw/missing.json` with a `wayback_url`
  pointing at their web.archive.org captures for manual recovery. Medium
  serves its not-found page with HTTP 200, so gone posts are detected
  from the page content, not just the status code. A gone post whose
  slug is archived under another id was likely deleted and republished,
  and is annotated with `same_slug_archived`. Re-running `fetch`
  re-checks flagged posts and unflags any that reappear.
* Medium boilerplate is stripped during `convert` and still present in
  the raw pages: the "was originally published on Medium" footer, stat
  tracking pixels, clap/share UI. Embedded iframes become links and need
  manual replacement. Gist embeds are the exception. A gist's content
  exists nowhere in the page itself, since Medium's state names only an
  opaque media resource id, so `fetch` archives the gist's files into
  `raw/<id>/media/` and `convert` inlines them as code fences. A gist
  embed whose media is not yet archived converts to a link to the gist
  (from export and Ghost bodies, which name it) or a
  `[missing embed: <name>]` placeholder (from the state, which does
  not). `lint` flags the placeholders until a `fetch` re-run backfills
  the media. Code fences carry the language Medium recorded for the
  block (`codeBlockMetadata`), and user mentions resolve to the author's
  Medium profile.
* A post's `description` is its summary and nothing else. Medium writes
  the summary it puts in JSON-LD and `<meta name="description">` as
  `<title> <excerpt>` and caps the result, so the title arrives twice
  and the excerpt is cut short. `og:description` carries the excerpt by
  itself and is preferred. Posts that open with their own title in the
  body (Medium's early years, and Ghost-era posts migrated into it) lead
  even that excerpt with the title, so `convert` drops a repeated title
  from whichever summary it uses. An account export's subtitle already
  arrives clean. A title that is itself ellipsis-truncated is left
  alone: there is no telling where it ended, so cutting it would strand
  its tail at the front of the description.
* Every Medium page carries its post twice: rendered into the visible
  HTML, and as data in its embedded editor state
  (`window.__APOLLO_STATE__`), the ordered paragraph list with markup
  spans, image ids, code blocks, plus title, timestamps, author and
  tags. `convert` prefers the state (`body_source: state`) over the
  rendered HTML. It has no chrome to strip and keeps what the renderer
  destroys: the full text span of a link containing a code fragment,
  bold on code, and iframe embeds that an un-hydrated capture drops
  entirely. It also survives when Medium serves the bare application
  shell (no server-rendered article, page title just "Medium"), which is
  how shell-only captures convert at all. A shell's images were never
  fetched, though, so its body keeps remote URLs until re-fetched.
  `compare --state` verifies the state conversion against account
  exports, as plain `compare` does for the page conversion. The rendered
  page remains the fallback and is available with
  `convert --prefer-page`.
* Medium rate-limits and may serve a bot wall. A 429 is not retried:
  fetch reports it, with the server's `Retry-After` hint when sent, and
  moves on. Raise `--delay` and re-run to resume.

## Layout

```
src/medium_archive/
  cli.py         argument parsing and the entry point
  fetch.py       the fetch step: download posts into <out>/raw/
  export.py      Medium account exports: parsing and the import-export step
  ghost.py       the import-ghost step: recover Ghost posts from the Wayback Machine
  convert.py     the convert step: <out>/raw/ -> Markdown in <out>/posts/
  myst.py        the myst step: <out>/posts/ -> a MyST site in <out>/site-myst/
  hugo.py        the hugo step: <out>/posts/ -> a Hugo site in <out>/site-hugo/
  pelican.py     the pelican step: <out>/posts/ -> a Pelican site in <out>/site-pelican/
  sites.py       machinery shared by the site exporters: page slugs, the
                 in-publication link map, image placement, covers,
                 redirect maps, site.json
  templates/     the site scaffolding the exporters copy into each site:
                 generator configs, themes, CSS, shared JS snippets
                 (see templates/README.md)
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
