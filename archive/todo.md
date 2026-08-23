# Archive notes and remaining work

## 0. MyST site

`medium-archive myst --out .` builds the browsable site in `site/`
(gitignored, like `posts/` — both regenerate from `raw/` + `fixups/`);
`site.json` holds the hand-written site title, description and
landing-page intro. Render with `myst start` or `myst build --html`
inside `site/` (`npm install -g mystmd`; the first build downloads the
book-theme template). Last full validation: `myst build --html` renders
all 333 pages with built-in full-text search; the only warnings are
~57 links to in-page anchors that never survived the original Medium
conversion (old footnote anchors, also dead in `posts/`), one h3→h5
heading jump published that way in 2015, and Medium-hosted images on
any post whose images were never fetched (none currently — `lint` is
clean).

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
