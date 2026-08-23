# Remaining work: conversion-quality follow-ups

Status from the 2026-08-23 session that regenerated `posts/` in the
blog_export archive, audited all 333 conversions, and fixed the converter.
Completed (code + fixups, validated by a full `convert --clean`, a clean
`lint` run, and 57 passing tests):

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

## 1. Recover the 8 empty `undated-*` posts (main remaining item)

These posts' `page.html` captures are Medium's empty shell (title
"Medium", no article markup), so `convert` now reports them FAILED and
they are absent from `posts/`, `posts.json` and `redirects.csv`:

- undated-a-gallery-of-voilà-examples (a2ce7ef99130)
- undated-a-slideshow-template-for-voilà-apps (435f67d10b4f)
- undated-and-voilà (f6a2c08a4a93)
- undated-jupyterlite-jupyter-️-webassembly-️-python (f6e2e41ab3fa)
- undated-need-for-speed-voilà-edition (a9e1300ab3b2)
- undated-online-collaboration-café-launch-… (b713edadf15)
- undated-voilà-is-now-an-official-jupyter-subproject (87d659583490)
- undated-voilà-0-5-0-homecoming (66f2465aa86f)

Plan: re-fetch each `page.html` from the live site or the Wayback Machine
(`fetch --urls FILE --force` with the 8 URLs from `raw/index.json`, or
recover by hand into `raw/<id>/page.html`). Needs network access, which
the 2026-08-23 session did not have.

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
