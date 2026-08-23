# Remaining work: conversion-quality follow-ups

Status from the 2026-08-23 session that regenerated `posts/` in the
blog_export archive, audited all 333 conversions, and fixed the converter.
Completed (code + fixups, validated by a full `convert --clean`, a clean
`lint` run, and 88 passing tests):

- **Chrome-only shell guard** — a `page.html` that is Medium's empty app
  shell (no `<article>`, no JSON-LD, no title) is no longer converted into
  a post of nav links: `convert_post` raises and the post is reported
  FAILED (`page_shell` in `src/medium_archive/convert.py`). The 8
  `undated-*` posts now fail cleanly instead of producing chrome (see
  below for recovering them).
- **Byline avatars stripped** — authors with a custom subdomain
  (`name.medium.com`) have no `/@` in the byline href, so their avatar
  block leaked into 28 converted bodies as a remote `miro.medium.com`
  image; `page_body` now also strips on `source=post_page---byline`
  (`src/medium_archive/pages.py`).
- **Embed links** — iframes now render as `[embed: url](url)` instead of
  the double-bracket `[[embed: url]](url)`.
- **Slug percent-decoding** — `slug_of` percent-decodes, so post dir names
  no longer mix `…voil%C3%A0…` and `…voilà…` forms.
- **Ghost-migration line breaks** — Medium's importer turned every wrapped
  source line of a migrated Ghost post into a `<br><br>` pair
  mid-paragraph; for posts with a Ghost origin (a `ghost.json` attached)
  these pairs now collapse to the space the wrap stood for
  (`collapse_br_pairs` in `pages.py`), fixing 8 posts' broken paragraph
  flow. Posts authored in Medium's own editor keep `<br><br>` as the
  intentional paragraph break it is there. Two fixups in the archive
  (`b79bfd18566d-signature-break`, `333efb100d08-schedule-breaks`) restore
  breaks the originals marked explicitly (`<br />`), which the migration
  made indistinguishable from wrap damage.
- **`lint` subcommand** — the audit heuristics are now
  `medium-archive lint`: leftover Medium chrome, unclosed fences, missing
  image files, remote Medium CDN images; exits non-zero on defects so
  regressions surface on every convert (`src/medium_archive/lint.py`).
- **Readability pass** (second audit round): figure captions render in
  italics, matching Medium's small-gray caption styling (including
  orphan captions whose figure never hydrated its image); a leading
  heading that repeats the post title is dropped (two posts rendered
  their title as a body `<h3>` with no `<h1>`); a body no longer opens
  with the `---` divider left over from the removed subtitle block;
  whitespace-only hard-break lines between image-grid entries are
  normalized to blank lines (outside code fences). Four fixups in the
  archive correct authored missing-space-after-period typos
  (`*-sentence-space.sub`, `b7e82b5e1202-caption-space.sub`).
- **Substitution fixups** — raw HTML is often one enormous line, so a
  unified diff of a one-character fix embeds the whole line twice and
  cannot be reviewed. `fixups/*.sub` files now hold single-line
  `old:`/`new:` substitutions (optional exact `count:`, `old-regex:`
  for regexes) that fail loudly like patch hunks; `*.patch` remains for
  structural edits. All 14 fixups in the archive use it, covering the
  export and the rendered page DOM. The page's embedded editor-state
  copy is deliberately left unpatched: its markup offsets index into
  the stored text, so editing it would skew them.

- **Shell posts recovered from the embedded editor state** — the 8 posts
  whose `page.html` is Medium's empty app shell (title "Medium", no
  article markup) turned out to carry the complete post in
  `window.__APOLLO_STATE__`: ordered paragraphs with markups, image ids,
  title, publish timestamps, author and tags. `convert` now reconstructs
  such posts from that state (`body_source: state`,
  `src/medium_archive/state.py`), so all 333 posts convert, with real
  dates and titles (`2019-12-29-voilà-is-now-an-official-jupyter-
  subproject` instead of `undated-…`). A shell with no usable state
  still fails loudly.
- **Embedded editor state is now the preferred Medium body source** —
  every Medium page carries its post twice (rendered HTML + the editor
  state in `window.__APOLLO_STATE__`); converting from the state
  (`export` > `feed` > `state` > `page`) removes all chrome-stripping
  risk and keeps what the renderer destroys: full link spans over code
  fragments, bold on code, and the ~78 iframe embeds (talk videos,
  tweets) that un-hydrated captures drop entirely — embeds now appear
  in 25 posts instead of 1. Link-preview cards render as clean one-line
  links instead of a heading nested inside link text. `compare --state`
  gates it against the account exports: 39/50 identical, the 11 diffs
  all explained (7 fixup-enriched exports, 4 where the state carries
  more than the export — links on code, a tweet, post-export edits).
  `convert --prefer-page` still selects the rendered HTML.
- **Medium link telemetry stripped** — Medium's renderer appends a
  `source=post_page---…`-style query parameter to links it emits, on any
  host; `to_markdown` now drops it (the dash-run value pattern marks it
  as Medium's, so a site's own `source` parameter survives). Cleaned 35
  links across 22 posts.

## 1. Fetch the 8 shell posts' images (main remaining item)

The 8 shell captures never hydrated their images, so those posts keep
remote `miro.medium.com` URLs — 52 of them, each listed as a `lint`
warning (`lint` names the posts). Re-fetch the posts from the live site
(`fetch --urls FILE --force` with their URLs from `raw/index.json`) to
pull the images and a rendered `page.html`. Needs network access, which
the 2026-08-23 sessions did not have.

## 2. Smaller observations (optional)

- The grant-narrative post (2b5fb94c3c58) and a few other 2015-era posts
  have list items split mid-sentence and some wrong link targets
  (footnote hrefs attached to the wrong anchors). The damage is identical
  in the Ghost capture and the Medium sources — it was published that way
  in 2015 — so the archive is faithful; fixups could hand-correct the
  worst of it if desired.
- `compare --ghost` still reports 8 posts whose Ghost original differs
  (dropped images already restored by fixups; remaining diffs are
  hard-wrap normalization and Medium-era edits).
