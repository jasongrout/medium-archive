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
- `dark-palette.css` — included twice by `card.css`: once for an
  explicit picker choice (`data-theme="dark"`) and once for a dark
  system scheme with no stored choice. `--accent` doubles as the link
  color and stays the same in both palettes.
- `card.css` — the card-grid look, written as both the hugo theme's and
  the pelican theme's stylesheet.

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
  `_LazyImages` Markdown extension (body images load lazily).
- `site_plugin.py` — appended verbatim after the filled config: gives
  Pelican the redirect stubs Hugo and Zola render for aliases, and the
  responsive body images the hugo theme's render hook produces. It
  refers to names the config defines (`SITEURL`, `PATH`), so it is not
  importable on its own.
- `theme/templates/` — the Jinja theme. `author.html` is `tag.html`
  with the `tag` variable swapped for `author`; keep them in step.

## zola/

`config.toml.tmpl`, the Tera templates, and a small standalone
stylesheet (the zola exporter predates the card look and keeps its
simpler list theme).

## myst/

`listing-covers.mjs` — companion transform for the myst-listing
gallery plugin; its header comment explains why cover images need it.
