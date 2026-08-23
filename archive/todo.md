# Archive notes and remaining work

Status after the 2026-08-23 audit sessions: all 333 posts convert
(`medium-archive convert --clean`), `lint` reports 0 problems, and
`compare` / `compare --state` / `compare --ghost` results are explained
below.

## 1. Fetch the 8 shell posts' images (main remaining item)

Eight posts were captured as Medium's empty app shell (title "Medium",
no rendered article); they convert from the page's embedded editor
state, but their images were never fetched, so those bodies keep remote
`miro.medium.com` URLs — 52 of them, each listed as a `lint` warning
(`lint` names the posts):

- a-gallery-of-voilà-examples (a2ce7ef99130)
- a-slideshow-template-for-voilà-apps (435f67d10b4f)
- and-voilà (f6a2c08a4a93)
- jupyterlite-jupyter-️-webassembly-️-python (f6e2e41ab3fa)
- need-for-speed-voilà-edition (a9e1300ab3b2)
- online-collaboration-café-launch-… (b713edadf15)
- voilà-is-now-an-official-jupyter-subproject (87d659583490)
- voilà-0-5-0-homecoming (66f2465aa86f)

Re-fetch them from the live site (`fetch --urls FILE --force` with
their URLs from `raw/index.json`) to pull the images and a rendered
`page.html`. Needs network access, which the 2026-08-23 sessions did
not have.

## 2. Expected compare results

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

## 3. Smaller observations (optional)

- The grant-narrative post (2b5fb94c3c58) and a few other 2015-era
  posts have list items split mid-sentence and some wrong link targets
  (footnote hrefs attached to the wrong anchors). The damage is
  identical in the Ghost capture and the Medium sources — it was
  published that way in 2015 — so the archive is faithful; fixups could
  hand-correct the worst of it if desired.
