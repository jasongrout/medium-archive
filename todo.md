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
  slug), year-grouped TOC, chronological landing page, in-publication
  links rewritten to site pages, MyST-hostile prose escaped (`@handle`
  would parse as a citation, paired `$` as math), and a site-level
  `redirects.csv` from every old inbound path (slug+id, `/p/<id>`,
  Ghost-era) to its page URL. Site-wide text comes from a hand-written
  `<out>/site.json`. Validated with a full `myst build --html` over the
  real archive: 333/333 pages, no warnings beyond pre-existing dead
  in-page anchors from the Medium era (`src/medium_archive/myst.py`).
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
  sections. Covers are chosen by sniffing dimensions from image
  headers (no image library needed for that path). Relatedly,
  `convert` now renames images fetched from extensionless URLs
  (stored as `.bin` in raw/) to the extension their bytes call for, so
  every derived layer gets typed image names — 103 such files in the
  reference archive. Both sites validated end-to-end in headless
  Chromium, including search-with-highlights.
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

## Remaining

Nothing pending in the tool itself. Archive-specific follow-ups (posts
whose images still need fetching, hand-correction candidates) live in
each archive's own notes, alongside its `fixups/`.
