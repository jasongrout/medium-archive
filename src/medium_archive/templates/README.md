# Site scaffolding

The files the site exporters copy into each generated site: generator
configs, themes, CSS, and the JS snippets shared between generators.
Editing a file here changes what the exporter writes on its next run;
the copies inside a generated `<out>/site-*` are disposable.

Loading (`sites.template_text` / `sites.fill_template`):

- Files are copied byte-for-byte, except:
- An `@include <path>` marker line — `<!-- @include shared/x.html -->`
  in HTML, `/* @include shared/x.css */` in CSS — is replaced by the
  named templates/-relative file. This is how the hugo and pelican
  themes share the `shared/` snippets.
- `*.tmpl` files take config values through `string.Template`
  (`$title`, `$base_url`, ...); values are serialized by the exporter
  before substitution. `$` placeholders can't collide with the braces
  Go templates, Jinja and Python dicts use, so the files read naturally.

Files here carry no comments beyond what their formats can hide from
the rendered output (Go-template and Jinja comments are fine; the
shared HTML/JS snippets and CSS are emitted verbatim, so their
rationale lives below instead).

## shared/ — spliced into both card themes (hugo + pelican)

These embed verbatim in both engines' pages, so they must carry no
`{{ }}` / `{% %}` template syntax (a test enforces this).

- `theme-init.html` — runs before the stylesheet loads, so a stored
  choice cannot flash the wrong scheme: an explicit light/dark choice
  pins `data-theme` on `<html>`; no attribute means
  `prefers-color-scheme` decides (see `card.css`).
- `theme-picker.html` — the header's light/system/dark picker. Hidden
  until its script runs, since without JS a choice could not apply
  anyway; picking "system" clears the stored choice so
  `prefers-color-scheme` rules again. The choice persists per browser.
- `term-sort.html` — the tag/author chip indexes' sort control: by name
  (A-Z, the order the generators emit, so the no-JS page reads the
  same) or by count, most posts first. Hidden until its script runs;
  the choice persists per browser, like the theme picker's. The wiring
  waits for DOMContentLoaded because the chip list follows the control
  in the page.
- `nav-current.html` — marks the header nav link whose path is the
  longest prefix of the current page's with `aria-current="page"`
  (which `card.css` paints in the accent, like jupyter.org's navbar):
  the home link catches post and pagination pages, `/tags/` catches
  every tag page, and so on. The feed link (no trailing slash) never
  matches.
- `feed-icon.html` — the RSS mark, as an inline SVG in the same
  stroked 24x24 style as the theme picker's icons. It is the header's
  feed link, and the link beside a tag's or an author's heading where
  that term has a feed of its own (`card.css` sizes both through
  `.feed-icon`). Being a marker *line*, the `@include` sits on its own
  line inside the anchor; the whitespace that leaves is not a flex item,
  so the icon still centres.
- `announcement.html` — the site-wide announcement banner. The base
  templates emit the `.announcement` div (above the header, hidden)
  only when site.json sets `"announcement"`; the script fills it from
  the div's `data-source` — an http(s) URL is fetched client-side, so
  many sites can share one live banner file (how Jupyter projects use
  Sphinx's `announcement` option with jupyter.org/assets/banner.html;
  empty content keeps the banner hidden), anything else is the banner
  HTML itself. The last fetch's content is cached per browser and
  rendered synchronously on the next page, so navigating the site
  doesn't shift the layout when the banner arrives; the live fetch
  corrects a changed announcement after the fact. Dismissal persists
  per browser keyed by the banner's content, so a changed announcement
  shows again.
- `share-icons.html` — the five share marks as one hidden `<symbol>`
  sprite the post templates `<use>`: LinkedIn's, Facebook's, Bluesky's
  and Mastodon's own logomarks (Simple Icons' reproductions, at their
  24x24 grid) plus an envelope drawn to match. The hrefs stay in each
  engine's post template, since only the engine knows the post's URL;
  the sprite is what the two share. It carries `width`/`height` 0 as
  well as the stylesheet's `display: none`, so it is out of the flow
  even before the CSS lands.
- `share-mastodon.html` — the Mastodon link's click handler. Every
  other network has one address to send a share to; a toot goes to the
  reader's own server, which the page cannot know, so the link asks for
  it and remembers the answer per browser, taking a pasted server URL
  or `@you@server` handle as readily as a bare domain. Without JS the
  link falls back to its href, the server directory. It follows the
  article, so the anchor exists when the script runs (and it waits for
  DOMContentLoaded regardless).
- `image-zoom.html` — click-to-zoom for body images, spliced into the
  post templates (not the base ones: only article pages have body
  images). An image is marked zoomable, and given the cursor, the
  button role and keyboard focus, only while the original holds detail
  the column is not already showing; the measure is the `width`
  attribute both exporters emit, since `naturalWidth` reports the
  srcset variant's width density-corrected to the layout size. The
  modal loads the `src` — always the full-size original, never a
  srcset variant — into a `<dialog>`, captioned with the image's alt
  text. Images inside a link are skipped, so a linked image still
  follows its link. Closes on a click anywhere, on Esc (the dialog's
  own) and on a page scroll, like Medium's. Re-measured on resize.
- `dark-palette.css` — included twice by `card.css`: once for an
  explicit picker choice (`data-theme="dark"`) and once for a dark
  system scheme with no stored choice. `--accent` doubles as the link
  color and stays the same in both palettes.
- `card.css` — the card-grid look, written as both the hugo theme's and
  the pelican theme's stylesheet.

Not shared, though both themes carry it: the Open Graph / `twitter:`
head block each engine's base template (`hugo/layouts/_default/
baseof.html`, `pelican/theme/templates/base.html`) writes for link
previews — the card LinkedIn, Facebook, Mastodon and Bluesky build from
a shared post, and so the other half of the share links at the foot of
one. It cannot live in `shared/` because every value in it is the
engine's own (`.Permalink` against `article.url`, `.Resources.Get`
against `article.cover`), which is the same reason the share hrefs stay
in the post templates. Keep the two in step: they are meant to emit the
same tags, and a test checks that they do.

## hugo/

The built-in theme (`hugo.TEMPLATES` maps each file into the site; the
regular list and taxonomy pages share `list.html`), plus:

- `hugo.toml.tmpl` — the generated site config.
- `layouts/_default/rss.xml` — full-content feeds, like the
  publication's original Medium feed: summary in `<description>`,
  complete body in `<content:encoded>`, capped by
  `services.rss.limit`. Feed readers resolve relative URLs unreliably,
  so root-relative src/href become absolute against baseURL, and the
  responsive srcset/sizes attributes (meaningless in a feed) are
  stripped. Written for site and per-term feeds alike, and also when a
  real theme is configured — feed policy is content policy, not
  styling.
- `layouts/_default/_markup/render-image.html` — body images: serve
  responsive, lazily-loaded variants (webp encodes of the still
  originals; gif/svg/webp sources pass through untouched).

## pelican/

- `pelicanconf.py.tmpl` — the generated config, including the
  `_LazyImages` Markdown extension (body images load lazily) and
  `TAG_DISPLAY`, the tag-slug-to-name map (tags reach Pelican as slugs
  so their URLs are exact; see `tags.py`).
- `site_plugin.py` — appended verbatim after the filled config: gives
  Pelican the redirect stubs Hugo renders for aliases, the responsive
  body images the hugo theme's render hook produces, and the names tags
  are shown under (from `TAG_DISPLAY`, set on the `Tag` objects so the
  theme and the per-tag feeds both pick them up). It refers to names the
  config defines (`SITEURL`, `PATH`, `TAG_DISPLAY`), so it is not
  importable on its own.
- `theme/templates/` — the Jinja theme. `author.html` is `tag.html`
  with the `tag` variable swapped for `author`; keep them in step.

## myst/

`listing-covers.mjs` — companion transform for the myst-listing
gallery plugin; its header comment explains why cover images need it.
