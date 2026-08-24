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

## Remaining

- Re-run `fetch` on real archives to backfill `raw/<id>/media/` for
  gist embeds, then `convert` + `lint` (the placeholders the 2026-08
  audit archive currently flags: 26 embeds across 7 posts). The
  medium.com/media endpoint and the anti-hijacking-prefix parsing were
  implemented against mediumexporter's usage and canned tests only —
  the development sandbox could not reach medium.com — so verify the
  first live run's output.

Archive-specific follow-ups (posts whose images still need fetching,
hand-correction candidates) live in each archive's own notes, alongside
its `fixups/`.
