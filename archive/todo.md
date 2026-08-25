# Archive notes and remaining work

## 0. Site builds (MyST, Hugo, Zola, Pelican)

**The hugo and pelican sites are the preferred targets** — they carry
the full feature set (card theme, Pagefind search with highlighted
in-context results and shareable ?q= links, optimized images, redirect
stubs at every old inbound path, archives timeline, capped
full-content feeds). The myst and zola sites remain as simpler
alternates.

`medium-archive myst|hugo|zola|pelican --out .` builds a browsable site
in `site/`, `site-hugo/`, `site-zola/`, or `site-pelican/` (all
gitignored, like `posts/` — everything regenerates from `raw/` +
`fixups/`); `site.json` holds the hand-written site title, description,
landing-page intro, and (for hugo/zola) the base_url baked into
absolute links and redirect stubs. The four exporters share page URLs
and link rewriting, so the generators can be compared on identical
content, then the keepers kept and the rest ignored.

**Previews:** the `.github/workflows/preview.yml` workflow rebuilds all
four sites from `raw/` on every push to main (or on demand) and
publishes them to GitHub Pages under `/hugo/`, `/pelican/`, `/zola/`
and `/myst/`, behind a landing page (`.github/preview-index.html`)
linking the four. Each exporter runs with `site.json`'s `base_url`
pointed at its subpath (patched only in the runner's workspace), so
baked-in absolute links land in the right place. Caveat: with
full-resolution images copied into every site, the four previews total
~3.3 GB — above GitHub Pages' documented 1 GB site limit (the deploy
may still go through; the 10 GB artifact limit is the hard one).
The fix is capping image sizes in the generated sites at export time —
a planned medium-archive change, tracked in that repo's `todo.md` —
after which the deployment drops to a fraction of the limit.

Last full validation, all four against all 333 posts:

- **myst** (`myst build --html`, mystmd 1.10.1): all pages render, with
  built-in full-text search and a cover-image gallery landing page (all
  334 posts as cards, 255 with 640×360 cover thumbnails, via the
  myst-listing plugin plus a generated companion transform that makes
  local covers work; the chronological list moved to `/archive`).
  `site/redirects.csv` now targets the URLs mystmd actually serves
  (slugs capped at 50 chars, unicode folded, collisions numbered) —
  previously 84 of 334 targets pointed at over-long slugs mystmd
  truncates. The only warnings are ~57 links to
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
- The pelican build writes 676 redirect stubs (matching the hugo
  count) via a plugin embedded in its generated config — Pelican has
  no aliases feature of its own, so the plugin renders
  `site-pelican/redirects.csv` into meta-refresh stub pages after each
  build. The build's only warnings are cosmetic empty-image-alt ones
  (Medium images rarely carry alt text).

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

## 3. Tag cleanup (tags.json)

`tags.json` drops the tags that only made sense on Medium (the
publication's own subject — `jupyter`, the `open-source` family — and
one-post SEO reach tags like `technology`, `programming`) and
consolidates variant spellings onto one tag each (`notebook`/`notebooks`
→ `jupyter-notebook`, `cplusplus`/`c-plus-plus-language` → `cpp`,
`dashboard`/`dashboarding` → `dashboards`, `voilà` → `voila`, …).
`convert` applies it to front matter, so posts.json and all four sites
inherit the cleaned tags; `raw/` keeps the originals, and a stale entry
aborts a full convert. Curate with `medium-archive stats --tags`.

A second, aggressive pass then consolidated the long tail. Every tag
that isn't the name of a specific Jupyter-ecosystem tool now has at
least three posts: one-post variants fold into broader categories
(`astronomy`/`physics`/`scientific-computing` → `science`,
`cve`/`mfa`/`bug-bounty` → `security`, `grafana`/`bots`/`outage` →
`devops`, `octave`/`r`/`sql`/`lua`/`debugger` → `kernels`, places →
`events`/`workshops`, …), post-specific descriptors are dropped
outright (`box2d`, `kubespray`, `moore`, `oreilly`, …), and tool tags
stay separate under the tool's name even with one or two posts
(`anywidget`, `elyra`, `ipycytoscape`, `jupytercad` — renamed from
`cad` — `tljh`, `repo2docker`, …). The same pass added the `"add"`
section: posts whose title plainly names an existing tag's topic but
never carried the tag (release announcements without `releases`,
JupyterCon posts without `jupytercon`, workshop reports without
`workshops`, the untagged early Ghost-era posts) now get it during
convert. Result: 287 distinct tags → 226 → 64, no untagged posts, and
the only sub-3-post tags left are eleven tool tags plus `robotics`.

`data-science` was then dropped too: of its 58 posts only three or four
were about data science as a subject — the rest were releases, workshop
logistics and JupyterCon posts carrying it for medium.com feed reach,
concentrated in the 2018–2019 SEO era. Dropping it left every post with
the right remaining tags (one, the NumFOCUS DISC sprint announcement,
got real tags via `"add"` instead). 63 tags.

`geoscience` then became its own category — the ten geospatial posts
(the JupyterGIS line, QGIS, ipyleaflet, ipyopenlayers, the "Jupyter
meets the Earth" project) are a coherent cluster, so `gis` and the raw
`geoscience`/`geospatial-data` tags all consolidate onto `geoscience`,
and each of those posts also carries the broader `science` tag (added
via `"add"`, since a rename can only produce one tag). `jupytergis`
stays separate as the tool tag.

Remaining judgement calls, all optional:

- `announcements`/`releases` overlap and could merge if the distinction
  isn't wanted.
- `jupyter-notebook` (108 posts, a third of the archive) mixes "about
  the Notebook application" with "uses notebooks"; splitting would be
  hand-work in `"add"`.
