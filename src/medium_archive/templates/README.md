# Site scaffolding

The files the site exporters copy into each generated site: generator
configs, themes, CSS, and the JS snippets shared between generators.
Editing a file here changes what the exporter writes on its next run.
The copies inside a generated `<out>/site-*` are disposable.

Loading (`sites.template_text` and `sites.fill_template`):

- Files are copied byte-for-byte, with two exceptions.
- An `@include <path>` marker line is replaced by the named
  templates/-relative file: `<!-- @include shared/x.html -->` in HTML,
  `/* @include shared/x.css */` in CSS. This is how the hugo and pelican
  themes share the `shared/` snippets.
- `*.tmpl` files take config values through `string.Template`
  (`$title`, `$base_url`, ...); the exporter serializes each value
  before substitution. `$` placeholders cannot collide with the braces
  Go templates, Jinja and Python dicts use, so the files read naturally.

Files here carry no comments beyond what their formats can hide from
the rendered output. Go-template and Jinja comments are fine. The
shared HTML/JS snippets and the CSS are emitted verbatim, so their
rationale lives below instead.

## shared/, spliced into both card themes (hugo + pelican)

These embed verbatim in both engines' pages, so they must carry no
`{{ }}` / `{% %}` template syntax. A test enforces this.

- `theme-init.html` runs before the stylesheet loads, so a stored
  choice cannot flash the wrong scheme. An explicit light/dark choice
  pins `data-theme` on `<html>`; no attribute means
  `prefers-color-scheme` decides (see `card.css`).
- `theme-picker.html` is the header's light/system/dark picker. It is
  hidden until its script runs, since without JS a choice could not
  apply anyway. Picking "system" clears the stored choice so
  `prefers-color-scheme` rules again. The choice persists per browser.
- `font-init.html` is the theme-init of the font experiment. It runs
  before the stylesheet loads so a stored choice cannot flash the
  default family first. A stored choice pins `data-font` on `<html>`;
  no attribute means the jupyter.org sans (see `card.css`).
- `font-picker.html` is the header's body-font switch, beside the theme
  picker and built like it: one cycling button, the choice persisted
  per browser. Where the theme button draws its state as an icon, this
  one names it ("Helvetica", "Open Sans", "Source") and sets the name in
  the family it names, so the button says and shows what the reader is
  on. The names are the button's own text, which the script reads back
  for the tooltip and `aria-label`; a fixed `min-width` in `card.css`
  keeps the three from shifting the nav as they cycle. It exists to let
  reviewers compare candidate typography before the blog settles on
  one: the jupyter.org Helvetica stack the site launched with, Open
  Sans (the humanist sans nearest the logo's Myriad Pro), and Source,
  the superfamily Medium set the publication in (Source Serif Pro
  running text, Source Sans Pro headings and chrome, Source Code Pro
  code). The article's reading size belongs to `.post` rather than to
  any one choice, so the three differ in family alone. The losing
  styles, and the picker with them, come out once that is decided.
  `card.css` states the choices as `--body-font` / `--mono`, so a new
  candidate is a `:root[data-font=...]` block redefining those rather
  than another pass over the rules that use them.
- `term-sort.html` is the tag/author chip indexes' sort control: by
  name (A-Z, the order the generators emit, so the no-JS page reads the
  same) or by count, most posts first. Hidden until its script runs;
  the choice persists per browser, like the theme picker's. The wiring
  waits for DOMContentLoaded because the chip list follows the control
  in the page.
- `nav-current.html` marks the header nav link whose path is the
  longest prefix of the current page's with `aria-current="page"`,
  which `card.css` paints in the accent, like jupyter.org's navbar. The
  home link catches post and pagination pages, `/tags/` catches every
  tag page, and so on. The feed link (no trailing slash) never matches.
- `feed-icon.html` is the RSS mark, an inline SVG in the same stroked
  24x24 style as the theme picker's icons. It is the header's feed
  link, and the link beside a tag's or an author's heading where that
  term has a feed of its own (`card.css` sizes both through
  `.feed-icon`). Being a marker line, the `@include` sits on its own
  line inside the anchor. The whitespace that leaves is not a flex
  item, so the icon still centres.
- `announcement.html` is the site-wide announcement banner. The base
  templates emit the `.announcement` div (above the header, hidden)
  only when site.json sets `"announcement"`. The script fills it from
  the div's `data-source`: an http(s) URL is fetched client-side, so
  many sites can share one live banner file (how Jupyter projects use
  Sphinx's `announcement` option with jupyter.org/assets/banner.html;
  empty content keeps the banner hidden), and anything else is the
  banner HTML itself. The last fetch's content is cached per browser
  and rendered synchronously on the next page, so navigating the site
  does not shift the layout when the banner arrives; the live fetch
  corrects a changed announcement after the fact. Dismissal persists
  per browser keyed by the banner's content, so a changed announcement
  shows again.
- `share-icons.html` is the five share marks as one hidden `<symbol>`
  sprite the post pages `<use>`: LinkedIn's, Facebook's, Bluesky's and
  Mastodon's own logomarks (Simple Icons' reproductions, at their 24x24
  grid) plus an envelope drawn to match. A post renders the bar twice,
  under the byline and at the foot, so the marks are defined once and
  referenced ten times. The bar itself stays with each engine, since
  only the engine knows a post's URL: hugo's `partials/share.html` and
  the pelican theme's `share()` macro in `macros.html`, each called
  twice. The sprite carries `width`/`height` 0 as well as the
  stylesheet's `display: none`, so it is out of the flow even before
  the CSS lands. `card.css` keeps the marks monochrome on hover:
  deepening a logomark is within most of these networks' brand
  guidelines, recoloring it to the site accent is not.
- `share-mastodon.html` is the Mastodon link's click handler. Every
  other network has one address to send a share to. A toot goes to the
  reader's own server, which the page cannot know, so the link asks for
  it and remembers the answer per browser, taking a pasted server URL
  or `@you@server` handle as readily as a bare domain. What is left has
  to look like a host before it is stored or navigated to: a bare
  `@you` normalizes down to `you`, and following that would fail DNS
  and leave junk as the next prompt's default. A modified click
  (ctrl/cmd/shift/alt, or any button but the first) is left alone, so
  "open in a new tab" still means that. Without JS the link falls back
  to its href, the server directory. It follows the article, so both
  bars' anchors exist when the script runs; it binds every one of them,
  and waits for DOMContentLoaded regardless.
- `image-zoom.html` is click-to-zoom for body images, spliced into the
  post templates rather than the base ones, since only article pages
  have body images. An image is marked zoomable, and given the cursor,
  the button role and keyboard focus, only while the original holds
  detail the column is not already showing. The measure is the `width`
  attribute both exporters emit, since `naturalWidth` reports the
  srcset variant's width density-corrected to the layout size. The
  modal loads the `src`, always the full-size original and never a
  srcset variant, into a `<dialog>`, captioned with the image's alt
  text, or with its figure's `<figcaption>` when the alt is empty (most
  Medium images carry no alt, but both exporters keep the
  `<figure>`/`<figcaption>` shell convert writes around a captioned
  image). Images inside a link are skipped, so a linked image still
  follows its link. It closes on a click anywhere, on Esc (the dialog's
  own) and on a page scroll, like Medium's, and re-measures on resize.
- `dark-palette.css` is included twice by `card.css`: once for an
  explicit picker choice (`data-theme="dark"`) and once for a dark
  system scheme with no stored choice. `--accent` doubles as the link
  color and stays the same in both palettes.
- `card.css` is the card-grid look, written as both the hugo theme's
  and the pelican theme's stylesheet.

## hugo/

The built-in theme (`hugo.TEMPLATES` maps each file into the site; the
regular list and taxonomy pages share `list.html`), plus:

- `hugo.toml.tmpl` is the generated site config.
- `layouts/_default/rss.xml` gives full-content feeds, like the
  publication's original Medium feed: summary in `<description>`,
  complete body in `<content:encoded>`, capped by `services.rss.limit`.
  Feed readers resolve relative URLs unreliably, so root-relative
  src/href become absolute against baseURL, and the responsive
  srcset/sizes attributes, meaningless in a feed, are stripped. Written
  for site and per-term feeds alike.
- `layouts/partials/post-image.html` renders one body image:
  responsive, lazily-loaded variants (webp encodes of the still
  originals; gif/svg/webp sources pass through untouched). The render
  hook and the figure shortcode share it, so captioned and bare images
  carry the same markup.
- `layouts/_default/_markup/render-image.html` handles body images from
  Markdown image syntax, delegated to the partial.
- `layouts/shortcodes/figure.html` renders a captioned (and possibly
  linked) body image as the `<figure>`/`<figcaption>` Medium served:
  the image through the same partial, the caption rendered inline with
  no `<p>` wrapper, styling left to CSS. The exporter rewrites
  convert's raw figure shells into calls to this shortcode
  (`hugo.figure_shortcodes`). The caption is passed as inner content,
  which Hugo's built-in figure shortcode would drop.

## pelican/

- `pelicanconf.py.tmpl` is the generated config, including the
  `_LazyImages` Markdown extension (body images load lazily) and
  `TAG_DISPLAY`, the tag-slug-to-name map (tags reach Pelican as slugs
  so their URLs are exact; see `tags.py`).
- `site_plugin.py` is appended verbatim after the filled config. It
  gives Pelican the redirect stubs Hugo renders for aliases, the
  responsive body images the hugo theme's render hook produces, and the
  names tags are shown under (from `TAG_DISPLAY`, set on the `Tag`
  objects so the theme and the per-tag feeds both pick them up). It
  refers to names the config defines (`SITEURL`, `PATH`, `TAG_DISPLAY`),
  so it is not importable on its own.
- `theme/templates/` is the Jinja theme. `author.html` is `tag.html`
  with the `tag` variable swapped for `author`; keep them in step.

## myst/

`listing-covers.mjs` is the companion transform for the myst-listing
gallery plugin; its header comment explains why cover images need it.
