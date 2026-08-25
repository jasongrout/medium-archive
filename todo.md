# Status: conversion-quality follow-ups

Tool work completed across the 2026-08 audit sessions (each change
validated by a full `convert --clean` over a large real archive, a
clean `lint` run, and the offline test suite):

- **Chrome-only shell guard** — a `page.html` that is Medium's empty app
  shell (no `<article>`, no JSON-LD, no title) is never converted into a
  post of nav links (`page_shell` in `src/medium_archive/convert.py`).
- **Embedded editor state as the preferred Medium body source** — every
  Medium page carries its post twice (rendered HTML + the editor state
  in `window.__APOLLO_STATE__`); `convert` now prefers the state
  (`export` > `feed` > `state` > `page`, `--prefer-page` overrides).
  The state has no chrome to strip and keeps what the renderer
  destroys: full link spans over code fragments, bold on code, iframe
  embeds that un-hydrated captures drop entirely, and clean one-line
  links for link-preview cards (`src/medium_archive/state.py`). It is
  also how shell-only captures convert at all — with real dates and
  titles, though a shell's images stay remote until re-fetched. A shell
  with no usable state still fails loudly. `compare --state` verifies
  the state conversion against account exports the same way plain
  `compare` verifies the page conversion.
- **Byline avatars stripped** — authors with a custom subdomain
  (`name.medium.com`) have no `/@` in the byline href, so their avatar
  block leaked into page-converted bodies as a remote image;
  `page_body` now also strips on `source=post_page---byline`.
- **Medium link telemetry stripped** — the renderer appends a
  `source=post_page---…`-style query parameter to links on any host;
  `to_markdown` drops it (the dash-run value pattern marks it as
  Medium's, so a site's own `source` parameter survives).
- **Ghost-migration line breaks** — Medium's importer turns every
  wrapped source line of a migrated Ghost post into a `<br><br>` pair
  mid-paragraph; for posts with a Ghost origin these collapse to the
  space the wrap stood for (`collapse_br_pairs`). Posts authored in
  Medium's own editor keep `<br><br>` as an intentional paragraph
  break.
- **Readability** — figure captions render in italics, matching
  Medium's caption styling; a leading heading repeating the post title
  is dropped; a body never opens with the divider left by the removed
  subtitle block; whitespace-only hard-break lines normalize to blank
  lines outside code fences; iframes render as `[embed: url](url)`;
  `slug_of` percent-decodes so directory names cannot mix encoded and
  decoded forms of one slug (and `resolve_canonical` compares decoded).
- **`lint` subcommand** — defect signatures (leftover Medium chrome,
  unclosed fences, missing image files, remote Medium CDN images) exit
  non-zero so regressions surface on every convert.
- **Substitution fixups** — raw HTML is often one enormous line, so a
  unified diff of a one-character fix embeds the whole line twice and
  cannot be reviewed. `fixups/*.sub` files hold single-line
  `old:`/`new:` substitutions (optional exact `count:`, `old-regex:`
  for regexes) that fail loudly like patch hunks; `*.patch` remains for
  structural edits. Fixups should not patch a page's embedded
  editor-state copy: its markup offsets index into the stored text, so
  editing it would skew them.

- **`myst` subcommand** — builds a MyST (mystmd) site in `<out>/site/`
  from the converted posts, so a browsable blog reproduces offline from
  `raw/` + `fixups/` (`convert` then `myst`). One page per post with its
  filename as the URL slug (date-prefixed only when several posts share a
  slug; mystmd caps served slugs at 50 chars, and `redirects.csv` targets
  replicate its slug rules — truncation, `[a-z0-9-]` folding, collision
  numbering — rather than assuming filename == URL), year-grouped TOC,
  a cover-image gallery landing page (every post as a card, newest
  first, via the pinned myst-listing plugin; covers are the same
  640×360 crop-or-letterbox thumbnails as the hugo/pelican card
  themes', double as each page's social-card image, and are made to
  work for local files by a small generated companion plugin,
  `site/listing-covers.mjs`, that turns the gallery's CSS cover
  backgrounds into real image nodes mystmd's image pipeline serves), a
  chronological `archive` page, in-publication links rewritten to site
  pages, MyST-hostile prose escaped (`@handle` would parse as a
  citation, paired `$` as math), and a site-level `redirects.csv` from
  every old inbound path (slug+id, `/p/<id>`, Ghost-era) to its served
  page URL. Site-wide text comes from a hand-written `<out>/site.json`.
  Validated with a full `myst build --html` over the real archive:
  336/336 pages (334 posts + landing + archive), 334 gallery cards (255
  with covers), every redirect target resolving to a built page, no
  warnings beyond pre-existing dead in-page anchors from the Medium era
  (`src/medium_archive/myst.py`).
- **`hugo`, `zola`, `pelican` subcommands** — the same site for those
  generators (`site-hugo/`, `site-zola/`, `site-pelican/`), sharing
  page URLs, link rewriting, `site.json`, and per-site redirect maps
  through `src/medium_archive/sites.py`, so generators can be compared
  on identical content. Hugo and Zola get tag+author taxonomy pages
  with per-term feeds, old inbound paths as alias redirect stubs, and
  a minimal self-contained theme; Zola's templates wire its built-in
  search index to a working search box (and its link checker is set to
  warn, not fail, on the Medium-era dead in-page anchors); Pelican
  relies on its built-in theme, with colocated images rewritten to
  `{attach}` links. Each validated with a real generator build over
  the full archive (hugo 0.152.2, zola 0.21.0, pelican 4.12.0).
- **Card-grid blog theme for hugo and pelican, with Pagefind search
  and image optimization** — both exporters now ship the same
  self-contained card theme (in the vein of pytorch.org/blog):
  paginated cover-card home, tag/author card listings, chip indexes,
  and a /search/ page wired to Pagefind, which serves full-text search
  as a results page with highlighted in-context excerpts and
  per-section sub-results (`pagefind --site public|output` after
  building). Hugo optimizes images natively — 640×360 cover thumbnails
  via `.Fill`, responsive lazily-loaded webp variants for body images
  via a render hook (gif/svg/non-image resources pass through) —
  while pelican generates 640×360 JPEG cover thumbnails at export time
  when Pillow is installed (the `covers` extra) and lazy-loads body
  images through a Markdown extension embedded in its generated
  config, with heading ids enabled so search results anchor to
  sections. Pelican gets redirect-stub parity too: a plugin embedded
  in its generated config renders the exported redirects.csv into
  meta-refresh stub pages after each build (matching Hugo's alias
  count row-for-row), since Pelican has no aliases feature of its own.
  The same embedded plugin brings body-image parity with Hugo's render
  hook: after each build it rewrites every still body image to
  lazily-loaded webp srcset variants (480/736/1104, never upscaled,
  real width/height, same sizes hint), encoding from and mtime-caching
  against the content-side originals — Pelican freshens output copies
  every build, which would defeat a cache keyed on them. On the
  reference archive: 1854 variants on the first build (~2.5 min, the
  same codec cost as Hugo's first build), 0 re-encoded and ~20 s on
  rebuilds. Chosen over the pelican-image-process plugin after reading
  its source: that plugin only processes class-annotated images (the
  annotation would have to come from this exporter anyway), flattens
  animated gifs, emits fixed-name srcset descriptors regardless of
  actual image size, and adds bs4+lxml (AGPL) to the site's build
  requirements. Covers are chosen by sniffing dimensions from image
  headers (no image library needed for that path). Relatedly,
  `convert` now renames images fetched from extensionless URLs
  (stored as `.bin` in raw/) to the extension their bytes call for, so
  every derived layer gets typed image names — 103 such files in the
  reference archive. Both sites validated end-to-end in headless
  Chromium, including search-with-highlights.
- **Sortable tag/author chip indexes (hugo + pelican)** — the card
  theme's /tags/ and /authors/ pages get a "Sort by name/count"
  control, a plain HTML+JS snippet shared verbatim between the two
  generators like the theme picker: name is the A–Z order the
  generators emit (so the no-JS page reads the same), count sorts most
  posts first with alphabetical ties, and the choice persists per
  browser via localStorage. Verified in headless Chromium against the
  reference archive on all four pages (both generators × tags/authors),
  including persistence across reloads and identical counts across
  generators.
- **Hugo theme support (Dream)** — site.json's `hugo` section can name
  a real theme (`theme`, `theme_repo`, optional `avatar` and `params`);
  the exporter then emits that theme's config instead of its own
  layouts and keeps `site-hugo/themes/` across regenerations. Dream
  (hugo-theme-dream, Hugo ≥ 0.158) gets first-class treatment: covers
  for the masonry cards from each post's first still image of sane
  size (animated gifs and >12 MP stills are passed over — Dream
  webp-encodes covers at original size), per-post bylines with
  profile links, the built-in search page and /posts archives
  timeline, an Authors nav item, siteStartYear from the oldest post,
  and an avatar copied into the site. Validated against the full
  archive with Hugo 0.158: all pages, covers, search, tag/author
  pages and feeds render (screenshots checked via headless Chromium).

From the 2026-08 review of other Medium-to-Markdown tools (medium-2-md,
mediumexporter — the latter's media-resource handling exposed a silent
data loss here):

- **Gist embeds recovered instead of silently dropped** — a gist embed's
  media resource has an empty `iframeSrc` (gists are the one embed type
  not routed through embedly), so its content exists nowhere in the
  page: the state conversion emitted nothing at all, and export/Ghost
  bodies carry it as a `<script src="…gist.github.com/….js">` tag that
  also converted to nothing. Now `fetch` archives the media payload
  (`medium.com/media/<id>?format=json`, mediumexporter's trick) and the
  gist's files (GitHub gists API) into `raw/<id>/media/`, incrementally
  — a re-run backfills posts archived before this existed — and
  `convert` inlines the files as language-tagged fences from any body
  source. Without archived media the embed becomes an
  `[embed: <gist url>]` link (export/Ghost, which name the gist) or a
  `[missing embed: <name>]` placeholder (the state, which doesn't),
  and `lint` flags the placeholders.
- **Code fences carry languages** — the state's `codeBlockMetadata`
  records the language Medium highlighted (author-set or auto-detected;
  DISABLED stays bare), and gist files and Ghost `language-*` classes
  provide it too; `to_markdown` now emits it on the opening fence.
  `compare` drops fence info strings, since only some sources know them.
- **User mentions resolve** — mention markups carry a `userId` and no
  href and rendered as empty links; the state's own `User:` entry names
  the profile (`https://medium.com/@username`). Unresolvable mentions
  stay plain text.

- **Sites carry display copies of images, capped at export time** —
  the exporters used to hard-link every full-resolution original from
  `posts/` into each site, so sources dominated the built output
  (~800 MB of a ~850 MB site on the reference archive, duplicated per
  generator, animated gifs alone ~600 MB) while the themes' srcset
  ladders top out at 1104 px. The shared image-placement path
  (`ImagePlacer` in `sites.py`, used by all four exporters) now
  resizes anything past a cap as it is placed: stills to a 1600 px
  longest edge via Pillow (format preserved, ICC kept, palette images
  de-paletted, and the original kept whenever the resize doesn't
  actually shrink the file), animated gifs to 1104 px via gifsicle
  (`-O2 --resize-fit --no-conserve-memory`; `-O2` re-optimizes frames
  to 2/3 the bytes of a bare resize, `--lossy` measured slower for no
  further gain, and without `--no-conserve-memory` huge gifs trip a
  low-memory mode that turned a 60 s resize into 5+ minutes — peak
  RSS measured ~1.1 GB on an 851-frame 22.6 MB gif). Display copies
  are built once into `<out>/.image-cache/<caps>/` — warmed in
  parallel up front, since encodes hold no GIL — and hard-linked into
  every site; `raw/` and `posts/` stay at full resolution, unreadable
  or exotic files pass through unchanged, and a missing tool degrades
  to full-size placement with a note. `site.json` tunes or disables
  the caps (`"images": {"still_max_edge": N, "animated_max_edge": N}`,
  0 = off). Validated by the offline suite (real-image tests, with a
  gifsicle test that skips where it is not installed) and a full
  four-site rebuild of the reference archive.

## Remaining

- Re-run `fetch` on real archives to backfill `raw/<id>/media/` for
  gist embeds, then `convert` + `lint` (the placeholders the 2026-08
  audit archive currently flags: 26 embeds across 7 posts). The
  medium.com/media endpoint and the anti-hijacking-prefix parsing were
  implemented against mediumexporter's usage and canned tests only —
  the development sandbox could not reach medium.com — so verify the
  first live run's output.

- Link contrast in the card theme: links use `--accent` (#f37626,
  Jupyter Orange) directly, which is 2.8:1 against the light palette's
  white cards — below WCAG AA's 4.5:1 for normal-size text, let alone
  AAA's 7:1 (jupyter.org makes the same trade-off with its orange
  links). The theme previously carried a darker link shade
  (`--accent-dark`, dropped in the 2026-08 restyle), though even that
  fell just short of AA: #c85a11 is 4.3:1 on white, while dark mode's
  #f08b4b managed 6.8:1 on the dark cards. If AA (or AAA) matters,
  reintroduce a link shade token per palette, picked to clear the
  chosen threshold, rather than darkening `--accent` itself, which
  also paints the banner and other fills.

Archive-specific follow-ups (posts whose images still need fetching,
hand-correction candidates) live in each archive's own notes, alongside
its `fixups/`.
