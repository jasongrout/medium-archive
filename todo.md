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
- **Readability** — captioned figures keep their
  `<figure>`/`<figcaption>` shell (the sites render it as Medium did:
  caption under its picture, styled by CSS, programmatically
  associated for assistive tech); a caption whose figure lost its
  image renders in italics instead; a leading heading repeating the post title
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

- **`myst` subcommand** — builds a MyST (mystmd) site in `<out>/site-myst/`
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
  `site-myst/listing-covers.mjs`, that turns the gallery's CSS cover
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
- **`hugo`, `pelican` subcommands** — the same site for those
  generators (`site-hugo/`, `site-pelican/`), sharing
  page URLs, link rewriting, `site.json`, and per-site redirect maps
  through `src/medium_archive/sites.py`, so generators can be compared
  on identical content. Hugo gets tag+author taxonomy pages
  with per-term feeds, old inbound paths as alias redirect stubs, and
  a minimal self-contained theme; Pelican
  relies on its built-in theme, with colocated images rewritten to
  `{attach}` links. Each validated with a real generator build over
  the full archive (hugo 0.152.2, pelican 4.12.0). A third exporter,
  `zola`, shipped alongside these and was dropped later (see below).
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
  headers (no image library needed for that path); only png/jpeg/webp
  names qualify, since the baked cover is served as cover.jpg and
  Hugo's card template rasterizes it, aborting the build on an svg
  badge it cannot decode. Relatedly,
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
- **Click-to-zoom body images (hugo + pelican)** — clicking an
  article image (or pressing Enter on it, since zoomable images take
  keyboard focus and a button role) opens it full size in a `<dialog>`
  modal captioned with its alt text, restoring the one Medium reading
  affordance the conversion drops: Medium's own "Press enter or click
  to view image in full size" hint is stripped as chrome by
  `pages.py`. Another plain HTML+JS snippet shared verbatim between
  the two generators, spliced into the post templates rather than the
  base ones. Only images worth zooming are marked, so the cursor never
  promises a no-op: the test is the `width` attribute both exporters
  already emit against the rendered width, not `naturalWidth`, which
  the browser density-corrects to the layout size once a srcset
  variant is in play. The modal loads the `src` — the full-size
  original the responsive markup keeps there, never a variant — and
  images inside a link are left alone, so a linked image still follows
  its link. Closes on a click anywhere, Esc, or a page scroll.
  Verified in headless Chromium against real hugo (0.140.2 extended)
  and pelican (4.12.0) builds of a fixture archive: 26 assertions per
  generator over marking, the affordances, open/close by mouse,
  keyboard and scroll, the zoomed source being the original, and
  re-measurement when the window resizes under an image.
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
  (`ImagePlacer` in `sites.py`, used by every site exporter) now
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

- **Line art is kept whole, not resized** — the cap above treated a
  survey chart like a photograph, and the srcset ladder below it
  finished the job: measured on one of the 2026 survey charts, ink
  contrast fell from 3.4:1 at the source's 1430 px to 2.3:1 at the
  736 px variant a phone picks, well under the 3:1 small text needs,
  and its 9 px axis labels came out ~4.6 px. Downscaling was not even
  buying much: flat color compresses by run length, not pixel count,
  so a lossless encode of most of this archive's line art comes out
  *larger* downscaled (18 of 25 sampled), as antialiasing invents
  intermediate colors. `ImagePlacer` now classifies each PNG —
  `<= 8192` colors and `>= 0.55` horizontally flat pixel pairs, ~8 ms
  an image, which separates this archive's line art (200-8000 colors,
  0.55-0.98 flat) from its photographs (14000+ colors, under 0.5
  flat) — and re-encodes line art to lossless webp at its own
  resolution, exempt from the still cap: pixel-exact text for ~60%
  fewer bytes than the source PNG (the 2026 survey post: 557 KB of
  PNG -> 201 KB, against 264 KB for a ladder that could not render
  the captions). A photograph that arrived as PNG takes the photo
  path instead (capped, JPEG q85, or webp when it carries alpha),
  which is where the archive's 63 photo-in-PNG files, ~70 MB, were
  hiding. Intricate line art is bounded rather than resized: past
  500 KB lossless it retries at webp q90, and only a panorama past
  4000 px is finally scaled. `place()` returns the path it wrote and
  the exporters retarget their pages' `images/<name>` references, so
  a changed format follows through to the markdown; the hugo render
  hook and pelican plugin skip the variant ladder for png and webp,
  which also hands click-to-zoom (#26) a full-resolution `src` to open
  rather than a 1600 px resample. The cache directory carries a scheme
  tag, so copies written by the old scheme are ignored rather than
  misread.
- **`zola` exporter dropped** — the Zola site fell far enough behind the
  hugo and pelican ones to stop being worth carrying: those two share
  the card-grid theme, Pagefind search, cover thumbnails and responsive
  body images, while the zola site kept the older list theme none of
  that work reached. Its module, Tera templates, config template,
  stylesheet and tests are gone, along with the `zola` subcommand; the
  shared machinery in `sites.py` is unchanged, so `hugo`, `pelican` and
  `myst` build exactly as before. The archive's `site-zola/` directory,
  if one was built, is now stale output and can be deleted.

- **tags.json: `imply` and per-post `remove`** — curating an archive's
  tags needs both directions, and the file only had one. `"imply"`
  states that one tag entails another everywhere it appears (every
  `jupytercon` or `workshops` post is also an `events` post) instead of
  repeating the pairing per post; `"remove"` subtracts a tag from the
  posts it does not describe, keyed by slug like `"add"`, which is the
  cheaper half of splitting an over-applied tag when most of its uses
  are right (drop-then-re-add stays the right move when most are
  wrong). The passes run drop, rename, add, imply, remove — so an added
  tag entails as much as an inherited one, and a remove has the last
  word even over an implication — and both new sections fail as loudly
  as the old ones: chained or dropped implications, a tag both added
  and removed on one post, and stale entries (an implication no post
  triggers, a remove of a tag no matching post carries) abort
  (`src/medium_archive/tags.py`).

- **tags.json: `display`, the name a tag is shown under** — Medium tags
  are slugs, so an archive's tags render as `jupyter-notebook` and
  `ipython` where a reader expects "Jupyter Notebook" and "IPython".
  Spelling them correctly is a display concern, not an identity one, so
  the new `"display"` section maps a tag to its name and nothing else
  moves: a tag stays one slug through `posts.json`, through the rest of
  `tags.json`, and through every `/tags/<tag>/` URL and per-tag feed. A
  tag with no entry shows as itself with its hyphens as spaces
  (`open-science` → "open science"), which is why the section only holds
  the tags that need a proper name; an entry repeating that default, a
  name two tags would share, and a name for a tag no post carries all
  abort, like every other section's stale or contradictory entry.

  Each exporter carries the name the way its generator wants it. Hugo
  gets a term page per tag, `content/tags/<tag>/_index.md` with that
  title, so cards, the tag page and its `<title>`, the chip index and
  the per-tag RSS feed all pick it up — under a real theme as much as
  the built-in one — while front matter keeps the slug. Pelican gets a
  `TAG_DISPLAY` map in `pelicanconf.py`, which the site plugin sets on
  the `Tag` objects once the tags are collected, with tags still
  reaching Pelican as slugs so `tag.slug` is exact rather than whatever
  its slugify makes of a name like "C++". Naming the objects rather than
  filtering in the theme is what reaches the per-tag feed's title, which
  Pelican builds in Python; and since Pelican makes a `Tag` object per
  article while `generator.tags` is keyed on the slug — one object per
  tag, every other article holding its own — each article's list is
  pointed at the one named object, or a tag would be named on its own
  page and on a single card and stay a slug everywhere else.
  MyST has no tag pages, so its front matter simply carries the names
  (`src/medium_archive/tags.py`, `sites.py`, `hugo.py`, `pelican.py`,
  `myst.py`).

- **The RSS mark, and a feed link per term** — the header's feed link
  was the word "RSS" among the nav's other words, and the per-term feeds
  both generators emit were reachable only through `<link
  rel="alternate">`, which is to say through a browser that still
  surfaces one. Both now use `shared/feed-icon.html`, the RSS mark as an
  inline SVG in the same stroked style as the theme picker's icons: in
  the header, and beside a tag's or an author's heading, linking that
  term's own feed. Hugo draws the link from `.OutputFormats.Get "rss"`,
  so it appears exactly where a feed exists and its `<link
  rel="alternate">` was already per-page; pelican's comes from
  `TAG_FEED_ATOM`/`AUTHOR_FEED_ATOM`. Both heads now declare the same
  pair — the site-wide feed on every page, plus this page's own where it
  has one — each `<link>` titled the way that feed titles itself, since
  a reader files a subscription under the name the link gives it. Hugo
  had been advertising a term's feed under the bare site title (so
  subscribing from /tags/jupyterlab/ filed "Jupyter Blog", not
  "JupyterLab · Jupyter Blog") and advertising nothing at all on a post
  page (`templates/shared/feed-icon.html`, `card.css`, both themes).

- **Share links on every post** — the archive's pages were read-only in
  the other direction too: nothing on a post offered to pass it on. Both
  card themes now close an article with five links — LinkedIn, Facebook,
  Bluesky, Mastodon and email — under the networks' own logomarks, drawn
  from one hidden `<symbol>` sprite (`shared/share-icons.html`) so the
  marks are shared even though only each engine knows a post's URL. The
  URLs are built at render time from the post's absolute permalink,
  percent-encoded by Go's contextual escaping on hugo and by an explicit
  `|urlencode` on pelican's Jinja, which does none of its own; they are
  only as real as `site.json`'s `base_url`, like the feed URLs and
  redirect stubs. Mastodon is the one network with no single address to
  send a share to, so that link is the one piece of script
  (`shared/share-mastodon.html`): it asks for the reader's server,
  normalizes a pasted server URL or `@you@server` handle down to the
  domain, remembers it per browser, and falls back without JS to the
  server directory. The bar sits inside the post card under a rule, and
  carries `data-pagefind-ignore` so "Share" never lands in the search
  index (`templates/shared/share-icons.html`,
  `templates/shared/share-mastodon.html`, `card.css`, both post
  templates).

- **Open Graph metadata, without which half the share links do
  nothing** — the first share links shipped against pages carrying no
  `og:` tags at all, and LinkedIn's and Facebook's share URLs pass only
  the page address: everything their share box shows is read back off
  the page, so a share of a post came up blank. Both card themes' heads
  now carry `og:site_name`/`type`/`title`/`url`/`description`, the
  post's baked 640x360 cover as `og:image` (with `twitter:card`
  following whether there is one), `article:published_time`, its
  authors and tags, and a canonical link. The other half of that same
  failure was `base_url`: unset, hugo falls back to `example.org` and
  pelican to an empty `SITEURL`, so every share link pointed at a
  domain the archive does not own or at a relative path LinkedIn
  rejects — and the build said nothing. `load_site_inputs` now warns
  once, where both exporters already meet. Share links are the first
  feature where a URL leaves the site, so a wrong one fails outright
  instead of degrading (`sites.py`, both base templates).

- **The share bar under the byline too, and monochrome marks** — a
  reader who decides to pass a post on usually decides at the top,
  where the byline tells them whose it is, not after scrolling to the
  foot. The bar now renders in both places, which meant giving each
  engine one definition of it rather than four copies: hugo gets
  `partials/share.html`, the pelican theme a `share()` macro beside
  `card()`, each called twice, with the `<symbol>` sprite still spliced
  in once and the Mastodon script binding every anchor rather than the
  first. The byline copy takes no rule above it — one there cuts the
  head off the article — and `.post-meta` carries the tighter margin
  that pairs with it. Hover no longer tints the marks with the site
  accent: these are the networks' logos, and most of their brand
  guidelines allow a one-color rendering but not a recoloring, so a
  hover deepens the mark toward the ink instead (`partials/share.html`,
  `macros.html`, `card.css`, `shared/share-mastodon.html`).

- **The pelican theme escapes what it renders** — pelican's own default
  `JINJA_ENVIRONMENT` sets no `autoescape` and jinja's default is off,
  so a theme emits every `{{ }}` raw; the burden of escaping is the
  theme author's, because `article.content` has to pass through as the
  HTML it is. This theme had not been carrying it. A post titled
  `<script>...` therefore ran as a script on its own page, its cards,
  and its `<title>`, as did a tag's display name and an author's — none
  of which the person building the archive writes, since they come from
  the archived publication. Demonstrated in a browser before and after:
  stock defaults executed all three payloads, and the fix executes
  none. The generated config now turns `autoescape` on (restating
  pelican's other three defaults, which the setting replaces) and the
  theme marks the one genuinely-HTML value, `article.content`, `|safe`.
  Hugo was never affected: Go's html/template escapes contextually,
  which is also why the two engines had been rendering such a title
  differently (`pelicanconf.py.tmpl`, `article.html`).

## Remaining

- Take the share bar's marks and share URLs from each network's own
  brand and developer material, rather than the reproductions and
  community knowledge it runs on now. The logomarks come from Simple
  Icons, which is a faithful reproduction but not the source -- and
  which dropped LinkedIn's over that company's branding policy, so
  that one is lifted from an old release. Per network, the two things
  worth confirming at the source are the official logo file with its
  usage rules (clear space, minimum size, which one-color renderings
  are permitted -- the bar assumes a monochrome mark tinted by
  `currentColor`, which is why hovering deepens it instead of coloring
  it), and the current documented share URL with its parameters:
  LinkedIn's `shareArticle` is already deprecated in favor of
  `sharing/share-offsite/`, Facebook's `sharer.php` is long-lived but
  undocumented, and the Bluesky and Mastodon intents are conventions
  rather than specifications. Each network's guidelines may also
  constrain the wording beside the mark.

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
  links; a deliberate choice, revisited and kept in the 2026-08
  restyle — dark-mode links pass AA at 6.6:1). The text grays are
  held to AAA: `--muted` was raised in that restyle (#6a6a6a→#525252
  light, #9b9791→#aeaaa4 dark) so every text token clears 7:1 on both
  the page background and the cards. If AA (or AAA) links ever
  matter, reintroduce a link shade token per palette, picked to clear
  the chosen threshold (#b45110 clears AA in light; #f58d47 clears
  AAA in dark), rather than darkening `--accent` itself, which also
  paints the banner and other fills.

Archive-specific follow-ups (posts whose images still need fetching,
hand-correction candidates) live in each archive's own notes, alongside
its `fixups/`.
