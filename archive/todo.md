# Archive notes and remaining work

## 0. Site builds (MyST, Hugo, Pelican)

**The hugo and pelican sites are the preferred targets.** They carry the
full feature set: card theme, Pagefind search with highlighted in-context
results and shareable ?q= links, optimized images, redirect stubs at
every old inbound path, archives timeline, capped full-content feeds.
The myst site remains as a simpler alternate.

A fourth exporter, `zola`, was dropped in 2026-08. Its site kept the
older list theme that none of the card-theme, search and image work
reached, so it was a fourth build to keep green for a target nobody
would ship. `site-zola/`, if one was ever built here, is stale output
and can be deleted.

`medium-archive myst|hugo|pelican --out .` builds a browsable site in
`site-myst/`, `site-hugo/` or `site-pelican/`. All three are gitignored,
like `posts/`; everything regenerates from `raw/` plus `fixups/`.
`site.json` holds the hand-written site title, description,
landing-page intro, and the `base_url` baked into absolute links and
redirect stubs. The three exporters share page URLs and link rewriting,
so the generators can be compared on identical content.

**Previews.** The `.github/workflows/preview.yml` workflow rebuilds all
three sites from `raw/` on every push to main, or on demand, and
publishes them to GitHub Pages under `/hugo/`, `/pelican/` and `/myst/`,
behind a landing page (`.github/preview-index.html`) linking the three.
Each exporter runs with `site.json`'s `base_url` pointed at its subpath
and `noindex` set, patched only in the runner's workspace, so baked-in
absolute links land in the right place and search engines do not index
the previews as copies of the eventual site. The sites carry capped display copies of the images
rather than the full-resolution originals, which is what keeps the
three previews within GitHub Pages' documented 1 GB site limit.

Last full validation, all three against all 333 posts:

- **myst** (`myst build --html`, mystmd 1.10.1): all pages render, with
  built-in full-text search and a cover-image gallery landing page. All
  334 posts appear as cards, 255 with 640×360 cover thumbnails, via the
  myst-listing plugin plus a generated companion transform that makes
  local covers work; the chronological list moved to `/archive`.
  `site-myst/redirects.csv` targets the URLs mystmd actually serves
  (slugs capped at 50 chars, unicode folded, collisions numbered);
  previously 84 of 334 targets pointed at over-long slugs mystmd
  truncates. The only warnings are about 57 links to in-page anchors
  that never survived the original Medium conversion (old footnote
  anchors, also dead in `posts/`) and one h3→h5 heading jump published
  that way in 2015.
- **hugo** (hugo 0.158.0, built-in card theme): a PyTorch-blog-style
  card grid of cover-image cards with tag links, excerpt and byline,
  paginated at 24, plus tag/author card listings, per-term RSS, alias
  redirect stubs for old Medium slug+id, `/p/<id>` and Ghost-era paths,
  and the Jupyter avatar in the header. Images are optimized natively:
  640×360 cover thumbnails and responsive lazily-loaded webp variants
  for body images (about 2100 processed images, about 2 min build).
  `pagefind --site public` after `hugo` gives /search/, a results page
  with highlighted in-context excerpts and per-section sub-results. All
  verified in headless Chromium.
- **pelican, card theme** (pelican 4.12.0): the same card-grid look
  from the exporter's own Pelican theme. Cover cards (640×360 JPEG
  thumbnails generated at export when Pillow is installed, about 16 KB
  each), tag/author card listings, chip indexes, archives timeline, site
  and per-tag/author Atom feeds, lazily-loaded body images (a Markdown
  extension in the generated config), heading ids for search anchors,
  and the same Pagefind /search/ page (`pagefind --site output`).
  Verified in headless Chromium.
- The pelican build writes 676 redirect stubs, matching the hugo count,
  via a plugin embedded in its generated config. Pelican has no aliases
  feature of its own, so the plugin renders `site-pelican/redirects.csv`
  into meta-refresh stub pages after each build. The build's only
  warnings are cosmetic empty-image-alt ones; Medium images rarely
  carry alt text.

Status after the 2026-08-23 sessions: all 333 posts convert
(`medium-archive convert --clean`), `lint` reports 0 problems, and the
`compare`, `compare --state` and `compare --ghost` results are explained
below. No required work remains.

## 1. Expected compare results

- `compare`: 44/50 identical. The 6 that differ are exactly the posts
  whose export.html is enriched by the ghost-image fixups.
- `compare --state`: 39/50 identical. The 11 that differ are the 7
  fixup-enriched exports plus 4 posts where the state carries more than
  the export: links on code fragments the export generator dropped
  (the-big-split, a-visual-debugger-for-jupyter), a tweet embed the
  export lacks (jupyter-receives-the-acm-software-system-award), and a
  mailto-span nuance (jupyter-community-workshops).
- `compare --ghost`: 8 posts differ, informationally. Dropped images
  are already restored by fixups; the rest is hard-wrap normalization
  and Medium-era edits.

## 2. Smaller observations (optional)

- The grant-narrative post (2b5fb94c3c58) and a few other 2015-era
  posts have list items split mid-sentence and some wrong link targets
  (footnote hrefs attached to the wrong anchors). The damage is
  identical in the Ghost capture and the Medium sources, so it was
  published that way in 2015 and the archive is faithful. Fixups could
  hand-correct the worst of it if desired.

## 3. Tag cleanup (tags.json)

`tags.json` drops the tags that only made sense on Medium and
consolidates variant spellings onto one tag each. Dropped: the
publication's own subject (`jupyter`, the `open-source` family) and
one-post SEO reach tags like `technology` and `programming`.
Consolidated: `notebook`/`notebooks` → `jupyter-notebook`,
`cplusplus`/`c-plus-plus-language` → `cpp`, `dashboard`/`dashboarding`
→ `dashboards`, `voilà` → `voila`, and so on. `convert` applies it to
front matter, so posts.json and all three sites inherit the cleaned
tags; `raw/` keeps the originals, and a stale entry aborts a full
convert. Curate with `medium-archive stats --tags`.

A second, aggressive pass then consolidated the long tail. Every tag
that is not the name of a specific Jupyter-ecosystem tool now has at
least three posts. One-post variants fold into broader categories
(`astronomy`/`physics`/`scientific-computing` → `science`,
`cve`/`mfa`/`bug-bounty` → `security`, `grafana`/`bots`/`outage` →
`devops`, `octave`/`r`/`sql`/`lua`/`debugger` → `kernels`, places →
`events`/`workshops`). Post-specific descriptors are dropped outright
(`box2d`, `kubespray`, `moore`, `oreilly`). Tool tags stay separate
under the tool's name even with one or two posts (`anywidget`, `elyra`,
`ipycytoscape`, `jupytercad` renamed from `cad`, `tljh`,
`repo2docker`). The same pass added the `"add"` section: posts whose
title plainly names an existing tag's topic but never carried the tag
now get it during convert. That covers release announcements without
`releases`, JupyterCon posts without `jupytercon`, workshop reports
without `workshops`, and the untagged early Ghost-era posts. Result:
287 distinct tags → 226 → 64, no untagged posts, and the only
sub-3-post tags left are eleven tool tags plus `robotics`.

`data-science` was then dropped too. Of its 58 posts only three or four
were about data science as a subject; the rest were releases, workshop
logistics and JupyterCon posts carrying it for medium.com feed reach,
concentrated in the 2018–2019 SEO era. Dropping it left every post with
the right remaining tags. One, the NumFOCUS DISC sprint announcement,
got real tags via `"add"` instead. `python` followed for the same
reason: it was inconsistently applied (43 of 334 posts, while nearly
every post involves Python) and overly broad on a Jupyter blog. Nothing
was left untagged, and dropping it surfaced two monthly Community Call
posts missing `community` and gave "Learn Python with Jupyter"
`education` instead. 62 tags.

Two more from the same review. `announcements` (nine posts, six of them
release posts already tagged `releases`, on a blog where every post
announces something) is dropped. `jupyter-notebook`, a third of the
archive and mostly meaning "Jupyter, the project", which is the dropped
`jupyter` tag under another name, is split rather than dropped.
medium-archive now allows re-adding a dropped tag via `"add"`, so the
tag is dropped everywhere and re-asserted on the 29 posts genuinely
about the Notebook application: its releases and security advisories,
the UX survey, the notebook-format workshops, and notebook clients
(EIN, nbterm, RetroLab). 61 tags.

`geoscience` then became its own category. The ten geospatial posts
(the JupyterGIS line, QGIS, ipyleaflet, ipyopenlayers, the "Jupyter
meets the Earth" project) are a coherent cluster, so `gis` and the raw
`geoscience`/`geospatial-data` tags all consolidate onto `geoscience`,
and each of those posts also carries the broader `science` tag, added
via `"add"` since a rename can only produce one tag. `jupytergis` stays
separate as the tool tag. `jupytercon` nests under `events` the same
way: every JupyterCon post also carries `events`.

A per-tag audit of everything used more than ten times then found the
inherited-tag problem in the other direction: tags that are right on
most of their posts but wrong on a handful, which `"drop"` cannot fix
and `"rename"` cannot either. medium-archive grew a per-post `"remove"`
for exactly that, and `tags.json` now uses it:

- `jupyterlab` (64 posts) was the worst case. Twenty-one of its posts
  were not about JupyterLab at all. Monthly community calls,
  distinguished-contributor announcements, the LF Charities move, the
  media-strategy post, a security sprint, and the workshop and
  governance posts all carried it from medium.com discovery, while
  JupyterLite releases, JupyterGIS, xeus-python and Jupyter Server
  posts carried it for the framework they build on or mention in
  passing. It keeps the 43 posts about the application: releases,
  Desktop, extensions, debugger, accessibility and UI work. The posts
  that were left with nothing real got the tag that does apply
  (`community` for the news posts, `extensions` for the 2022 packaging
  post).
- `jupyterhub` lost seven (the same community calls, the mybinder
  federation and OVHcloud posts, and an nbgrader hackathon where
  JupyterHub appears in a PR link), `science` eight, `education` two,
  `ipython` one, `jupyterlite` one.
- `science` also shed `scientific-computing`, which was Medium
  boilerplate on the JupyterLab Desktop line and one release post
  rather than a subject; it is dropped rather than renamed now, as is
  `tutorial`, whose single use sat on a widget how-to. Everything else
  reviewed at that size held up post by post and is unchanged:
  `community`, `events`, `releases`, `workshops`, `jupyter-notebook`,
  `kernels`, `jupytercon`, `binder`, `security`, `visualization`,
  `kubernetes`, `dashboards`, `widgets`, `webassembly`, `geoscience`.

`numfocus` and `linux-foundation` are dropped. Partner and host
organizations are metadata about a post's origin, not what it is about,
and they only ever landed on JupyterCon and funding posts that say so
themselves. The JupyterCon 2020 keynote announcement for Jeremy Howard
carried `numfocus` alone, so it gets `jupytercon` via `"add"`.

The `jupytercon` → `events` nesting is now a rule rather than 20
repeated `"add"` entries. tags.json's `"imply"` section states that
`jupytercon` and `workshops` both entail `events`, so every conference
and workshop post carries it (events: 42 → 67) and future posts inherit
the pairing without another edit. 60 tags, still no untagged post. The
2026 user-experience survey results post, which came off Medium with no
tags at all, gets `community` like the other survey posts.

`jupyter-foundation` is the one tag this pass added rather than
removed. The Foundation is new, announced in the October 2024 LF
Charities post, and the blog has covered it steadily since, but no post
carries a Medium tag for it. All eight uses come from `"add"`: its
founding, the 2025 Executive Council election that explains its
governing board, the three community-funding posts (both calls for
proposals and the first round of awards), its community-manager hire,
and the 2026 user survey it ran plus the results. The line drawn is
"the Foundation is the actor", not "the Foundation is thanked". A dozen
more posts credit it for sponsoring or funding the work they describe
(the Plugin Playground and jupyter-builder proposals, the eslint
plugin, JupyterLab 4.6, the workshop reports, and the Positron guest
post from a member company), and those keep the tags for what they are
about. The two workshop-program posts (`Workshops Are Back`, `Early
2026`) are the closest call: the program runs on Foundation money and
LF Events logistics, but the posts are about the workshops.

Remaining judgement calls, all optional:

- The nested pairs (`geoscience` under `science`, `jupytercon` under
  `events`) work today by each post carrying both tags. Every
  generator's taxonomy is flat, so the parent's tag page naturally
  includes the children's posts, but the tag index pages still list
  parent and child as siblings. Displaying the relationship (children
  indented under their parent on the tag index, a "part of: science"
  line on the child's page) would be a medium-archive theme change: a
  parent map in the site config that the hugo/pelican/myst tag-index
  templates read. Nothing is needed in this repo but the map.
- Another natural hierarchy: a broad "Jupyter projects" parent over the
  specific tool tags (`jupyterlab`, `jupyterhub`, `binder`, `voila`,
  `jupyterlite`, `xeus`, and the small ones such as `anywidget`,
  `elyra`, `jupytercad`, `tljh`). Unlike geoscience or jupytercon it
  would sit on most of the archive, so it is more a tag-index grouping
  than a tag every post should carry, and probably wants the parent-map
  approach above rather than double-tagging. An idea only, not acted
  on.

## 3b. Tag names (tags.json `display`)

The tags are slugs, because Medium's are. The sites rendered
`jupyter-notebook`, `ipython` and `jupyterhub` where a reader expects
"Jupyter Notebook", "IPython" and "JupyterHub". Spelling them correctly
is a display concern, not an identity one, so medium-archive's
`"display"` section names a tag and nothing else moves. A tag stays one
slug through `posts.json`, the rest of `tags.json`, and every
`/tags/<tag>/` URL and per-tag feed, so nothing in `redirects.csv` or
the sites' link structure shifts. A tag with no entry shows as itself
with its hyphens as spaces, which covers the plain topic tags
(`open-science` → "open science", `cloud-computing` → "cloud
computing"). The 26 entries are the ones with a proper name to get
right.

Those are the Jupyter projects (`jupyterlab` → "JupyterLab",
`jupyter-notebook` → "Jupyter Notebook", `jupytercad` → "JupyterCAD",
`mystmd` → "MyST", `voila` → "Voilà", and `tljh` → "TLJH", the acronym
rather than "The Littlest JupyterHub", which is too long for a chip),
the outside projects and platforms (`github` → "GitHub", `kubernetes` →
"Kubernetes", `docker` → "Docker", `javascript` → "JavaScript",
`webassembly` → "WebAssembly", `devops` → "DevOps", `cpp` → "C++", `ai`
→ "AI"), and `outreachy` → "Outreachy". The tool tags whose own
projects spell themselves lowercase (`anywidget`, `nbviewer`,
`repo2docker`, `xeus`) are left alone deliberately: correct
capitalization there is lowercase.

Five tags changed in the tag rather than its name, while the file was
open. `jupyterenterprisegateway` → `jupyter-enterprise-gateway`
("Jupyter Enterprise Gateway"), so the one run-together slug hyphenates
like the rest. Four one-post tool tags fold into the topic tag they sit
under: `3dslicer` and `itkwidgets`, both about interactive 3D rendering
in a notebook, into `visualization` (15 → 17); `ipycanvas` and
`ipycytoscape`, both ipywidgets libraries, into `widgets` (11 → 14, the
third being the `Jupyter Games` post that carried `ipycanvas` via
`"add"`). The Medium tag `canvas` now renames straight to `widgets`,
which left the `ipycanvas` rename with nothing to match; `convert` said
so, and it went. 56 tags.
