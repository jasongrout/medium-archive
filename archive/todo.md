# Archive notes and remaining work

## 0. Site builds (MyST, Hugo, Zola, Pelican)

`medium-archive myst|hugo|zola|pelican --out .` builds a browsable site
in `site/`, `site-hugo/`, `site-zola/`, or `site-pelican/` (all
gitignored, like `posts/` — everything regenerates from `raw/` +
`fixups/`); `site.json` holds the hand-written site title, description,
landing-page intro, and (for hugo/zola) the base_url baked into
absolute links and redirect stubs. The four exporters share page URLs
and link rewriting, so the generators can be compared on identical
content, then the keepers kept and the rest ignored.

Last full validation, all four against all 333 posts:

- **myst** (`myst build --html`, mystmd 1.10.1): all pages render, with
  built-in full-text search. The only warnings are ~57 links to
  in-page anchors that never survived the original Medium conversion
  (old footnote anchors, also dead in `posts/`) and one h3→h5 heading
  jump published that way in 2015.
- **hugo** (hugo 0.158.0, built-in card theme): a PyTorch-blog-style
  card grid — cover-image cards with tag links, excerpt and byline,
  paginated at 24 — plus tag/author card listings, per-term RSS, alias
  redirect stubs for old Medium slug+id, `/p/<id>` and Ghost-era
  paths, and the Jupyter avatar in the header. Images optimized
  natively: 640×360 cover thumbnails and responsive lazily-loaded webp
  variants for body images (~2100 processed images, ~2 min build).
  `pagefind --site public` after `hugo` gives /search/ — a results
  page with highlighted in-context excerpts and per-section
  sub-results. All verified in headless Chromium. (site.json can
  instead target the Dream theme; that support remains.)
- **pelican, card theme** (pelican 4.12.0): the same card-grid look
  from the exporter's own Pelican theme — cover cards (640×360 JPEG
  thumbnails generated at export when Pillow is installed, ~16 KB
  each), tag/author card listings, chip indexes, archives timeline,
  site and per-tag/author Atom feeds, lazily-loaded body images
  (Markdown extension in the generated config), heading ids for search
  anchors, and the same Pagefind /search/ page (`pagefind --site
  output`). Verified in headless Chromium.
- **zola** (zola 0.21.0): 333 pages in ~2 s, taxonomy pages and
  per-term Atom feeds, aliases, and a working search box (built-in
  elasticlunr index). The 53 dead in-page anchors are reported as
  warnings (`link_checker.internal_level = "warn"` in the generated
  config).
- Pelican has no alias mechanism, so its old-URL redirects live only
  in `site-pelican/redirects.csv`; the build's only warnings are
  cosmetic empty-image-alt ones (Medium images rarely carry alt text).

Status after the 2026-08-23 sessions: all 333 posts convert
(`medium-archive convert --clean`), `lint` reports 0 problems, and
`compare` / `compare --state` / `compare --ghost` results are explained
below. No required work remains.

## 1. Expected compare results

- `compare`: 44/50 identical; the 6 that differ are exactly the posts
  whose export.html is enriched by the ghost-image fixups.
- `compare --state`: 39/50 identical; the 11 that differ are the 7
  fixup-enriched exports plus 4 posts where the state carries more than
  the export — links on code fragments the export generator dropped
  (the-big-split, a-visual-debugger-for-jupyter), a tweet embed the
  export lacks (jupyter-receives-the-acm-software-system-award), and a
  mailto-span nuance (jupyter-community-workshops).
- `compare --ghost`: 8 posts differ (informational); dropped images are
  already restored by fixups, the rest is hard-wrap normalization and
  Medium-era edits.

## 2. Smaller observations (optional)

- The grant-narrative post (2b5fb94c3c58) and a few other 2015-era
  posts have list items split mid-sentence and some wrong link targets
  (footnote hrefs attached to the wrong anchors). The damage is
  identical in the Ghost capture and the Medium sources — it was
  published that way in 2015 — so the archive is faithful; fixups could
  hand-correct the worst of it if desired.
