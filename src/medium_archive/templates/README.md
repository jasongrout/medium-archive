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
  no attribute means Source Serif, the default (see `card.css`).
- `font-picker.html` is the body-font switch: a `<select>`, not a
  button like the theme picker, since it offers nine choices, too many
  to cycle one click at a time. It floats fixed at the page's
  bottom-right corner instead of sitting beside the theme button in
  the header (`card.css`), so it stays reachable once a long article
  has scrolled the header away; it is spliced in once, near the end of
  the body, rather than into the nav. Each `<option>` carries the
  family it offers as its own inline style, so the open list previews
  every choice in the face it names; the select's own font-family is
  set from script on every change, so the closed box previews the
  current choice too, the way the old cycling button's own text did.
  The choice persists per browser, like the theme picker's. It exists
  to let reviewers compare candidate typography before the blog
  settles on one: Source Serif, the superfamily Medium set the
  publication in and this picker's default, the jupyter.org
  Helvetica stack the site launched with, the reader's own platform
  UI font, Inter, two standalone sans faces picked for their own
  look (Atkinson Hyperlegible, Nunito Sans), and Source Sans and the
  IBM Plex superfamily as both a sans and a serif face. Headings and
  chrome stay sans under every choice: a superfamily's sans option ("Source
  Sans", "IBM Plex Sans") runs the whole page, article included, in
  its own sans and mono faces; its serif sibling (the default "Source
  Serif", "IBM Plex Serif") keeps headings and chrome on that same
  sans face, as Medium did, and points only the article's running
  text at the serif face instead, with the superfamily's own mono
  still under its code. A choice's code follows its own mono face
  wherever it has one (the superfamilies', Atkinson Hyperlegible's
  own); System UI's is the platform's own ui-monospace stack, and a
  choice with no mono face of its own (Helvetica, Inter, Nunito Sans)
  falls back to that same platform stack. The article's reading size
  belongs to `.post` rather than to any one choice, so the nine differ
  in family alone. The losing styles, and the picker with them, come
  out once that is decided.
  `card.css` states the choices as `--body-font` / `--mono`, so a new
  candidate is a `:root[data-font=...]` block redefining those rather
  than another pass over the rules that use them.
- `link-init.html` and `link-picker.html` are the same pair again for
  link colour, and the picker sits directly above the font one in the
  floating stack, since the two are the same kind of question. It
  exists for the same reason: to compare candidates on real posts
  before the blog settles on one. A stored choice pins `data-link` on
  `<html>`; no attribute means the default, ink words under an accent
  rule. The choices are the default; the same rule darkened to clear
  3:1 against the card; three blues that colour the word and its rule
  together, at the accent's OKLCH complement (228deg) and two steps
  round towards a conventional link blue; that complement again at the
  7:1 the body grays hold; and, as the two controls the rest are read
  against, the plainest link there is (ink words under a rule in that
  same ink) and the browser's own, its colour and its own rule.
  `card.css` states a choice as a pair of values, light and dark, so a
  candidate is one `:root[data-link=...]` block and no scheme rules of
  its own; it also carries the reasoning behind the numbers. The losing
  choices, and the picker with them, come out once the blog decides.
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
  only the engine knows a post's URL: hugo's `_partials/share.html` and
  the pelican theme's `share()` macro in `macros.html`, each called
  twice. Each link is the network's own documented share URL: LinkedIn
  and Facebook take the page address alone and read the rest off its
  Open Graph tags, Bluesky and Mastodon take a prefilled `text` of the
  title and address, and Mastodon's goes to share.joinmastodon.org,
  the network's own share sheet, which asks the reader for their
  server and remembers it, so no script of this theme's is needed. The
  sprite carries `width`/`height` 0 as well as the stylesheet's
  `display: none`, so it is out of the flow even before the CSS lands.
  `card.css` keeps the marks monochrome on hover: deepening a logomark
  is within most of these networks' brand guidelines, recoloring it to
  the site accent is not.
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
- `code-copy.html` is the copy button in the corner of every code
  block, spliced into the post templates beside `image-zoom.html`,
  since only article pages have code blocks. Every `<pre>` in the
  article is one, whatever the engine wrapped it in (a fenced block
  from convert, a Goldmark or Pygments highlight div, an inlined
  gist or Carbon snippet inside a figure): the script wraps each in a
  `.code-block` div, the positioning box `card.css` pins the button
  to, so a wide block scrolls under the button rather than carrying it
  off; when the button shows (on hover, on keyboard focus, always
  on touch) is the stylesheet's business, explained there. The button's markup is a `<template>`, cloned per block, so
  the two icons (a clipboard in the theme picker's stroked style, and
  the check that replaces it for a moment after a copy) are HTML
  rather than strings in the script. They swap by `hidden` attribute,
  toggled as an attribute: SVG elements have no `hidden` property, so
  assigning one, as the theme picker could on its HTML, sets nothing. The copied text is the block's
  text content without its trailing newline. The status line beside
  the template is a live region a screen reader announces the copy
  through, since a changed button label is not read out. Without the
  async clipboard API (an insecure origin) no button is added, so the
  page never shows a button that cannot work.
- `dark-palette.css` is included twice by `card.css`: once for an
  explicit picker choice (`data-theme="dark"`) and once for a dark
  system scheme with no stored choice. `--accent` doubles as the link
  color and stays the same in both palettes. The `--syn-*` colours
  are the syntax-highlighting set for that palette, GitHub's own
  Primer prettylights colours unaltered (an AA scheme: every token
  clears 4.5:1 on that palette's `--code-bg` except the light comment
  grey, GitHub's own shortfall, and a test holds them there);
  `card.css` names the light set beside its other light values and
  applies both
  through the token rules under `.post .highlight`, on the class
  names Chroma (Hugo, with `noClasses` off in `hugo.toml.tmpl`) and
  Pygments (Pelican, through the fence rule in the generated config's
  reader, which names the same `highlight` class) share.
- `card.css` is the card-grid look, written as both the hugo theme's
  and the pelican theme's stylesheet.

## hugo/

The built-in theme, in the layout structure current Hugo looks pages
up in -- `baseof.html`, `home.html`, `page.html`, `section.html`,
`taxonomy.html` and the underscored `_partials/`, `_shortcodes/` and
`_markup/` (`hugo.TEMPLATES` maps each file into the site; the post
section and a term's page share `section.html`, written to the site as
`term.html` too), plus:

- `hugo.toml.tmpl` is the generated site config. Its
  `[markup.highlight]` turns off Chroma's inline styles, whose default
  Monokai would paint a dark block on the light page; the tokens get
  classes instead and `card.css` colours them per palette.
- `content/tags/_content.gotmpl` is a content adapter: it creates one
  term page per entry of `data/tags.json` (tag slug -> display name,
  written by `sites.write_data_files`), so the tag pages, cards, chip
  index and per-tag feeds all show a tag's name while its URL stays
  the slug -- and a checked-in copy of the site renames a tag by
  editing that one data file.
- `content/authors/_content.gotmpl` is the same adapter for authors,
  over `data/authornames.json` (author slug -> name, from the same
  writer). Bylines need it more than tags do: a name left as the term
  puts its accents and punctuation into the path, and the pelican site
  folds the same name to ASCII, so without it the two engines serve one
  author at two different addresses.
- `layouts/rss.xml` gives full-content feeds, like the
  publication's original Medium feed: summary in `<description>`,
  complete body in `<content:encoded>`, capped by `services.rss.limit`.
  Feed readers resolve relative URLs unreliably, so root-relative
  src/href become absolute against baseURL, and the responsive
  srcset/sizes attributes, meaningless in a feed, are stripped. Written
  for site and per-term feeds alike.
- `layouts/_partials/post-image.html` renders one body image:
  responsive, lazily-loaded variants (webp encodes of the still
  originals; gif/svg/webp sources pass through untouched). The render
  hook and the figure shortcode share it, so captioned and bare images
  carry the same markup. The post's first image (front matter
  `first_image`, from the exporter) is fetched eagerly at high priority
  instead of lazily, as WordPress treats the first content image.
- `layouts/_partials/paginator.html` is the one paginator a listing
  page (home, a section, a term) renders from, for the list templates
  and for the head alike: page 2 of a listing is its own address, and
  `baseof.html` names it in the canonical link, `og:url` and `<title>`
  rather than page one, which search engines would fold every page
  into. Hugo keeps the first paginator a page builds, so head and body
  asking with the same arguments get the same one.
- `layouts/_partials/jsonld.html` is every page's structured data: one
  schema.org graph, as WordPress's SEO plugins emit it -- the
  `Organization` (publisher: logo, `site.Params.profiles` as `sameAs`)
  and the `WebSite` (the search page as its `SearchAction`) on every
  page, referenced by `@id` from a `BreadcrumbList` placing the page,
  a post's `BlogPosting` (headline, dates, authors with their profile
  from `data/authors.json` (read through `hugo.Data`) as `sameAs`, cover with dimensions,
  keywords) and an author page's `ProfilePage`. Built as dicts and
  jsonified so every value is escaped for a `<script>`.
- `layouts/_partials/related.html` closes a post page with up to three
  related posts (Hugo's related content, by the `[related]` indices
  the generated config sets: shared tags, then author, then date), as
  listing cards, kept out of the search index.
- `layouts/robots.txt` names the sitemap Hugo generates, or disallows
  everything when site.json sets `"noindex"` (the same switch puts a
  `noindex` robots tag on every page, as a page's own front matter
  does for the search page).
- `layouts/_markup/render-image.html` handles body images from
  Markdown image syntax, delegated to the partial.
- `layouts/_shortcodes/figure.html` renders a captioned (and possibly
  linked) body image as the `<figure>`/`<figcaption>` Medium served:
  the image through the same partial, the caption rendered inline with
  no `<p>` wrapper, styling left to CSS. The exporter rewrites
  convert's raw figure shells into calls to this shortcode
  (`hugo.figure_shortcodes`). The caption is passed as inner content,
  which Hugo's built-in figure shortcode would drop.

## pelican/

- `pelicanconf.py.tmpl` is the generated config. Most of it is the
  CommonMark reader that replaces Pelican's python-markdown one
  (`pip install markdown-it-py mdit-py-plugins`), which is where
  everything this site needs from the Markdown layer hangs: heading
  ids for search anchors, Pygments on the `highlight` class the shared
  stylesheet styles, Pelican's `{attach}` placeholders (markdown-it
  percent-encodes a link target, so the braces are put back before
  Pelican's intra-site pass looks for them), the marking that tells
  the site plugin's post-build pass which images are a body's, and the
  `::: figure` directive the exporter writes for a captioned image --
  the counterpart of the hugo theme's figure shortcode, rendering the
  caption with this same parser so it is not raw HTML in the content.
  The reader is registered through a plugin whose `register()` builds
  the class, so the config can be read (and tested) without Pelican
  installed. It reads YAML front matter between `---` fences, the shape
  the hugo site writes too (see `sites.front_matter_yaml`), rather
  than Pelican's own `Key: value` headers that nothing else reads; Pelican's
  metadata processors then turn the lists into `Tag` and `Author`
  objects and parse the dates. Beyond CommonMark it enables what the hugo site's Goldmark
  enables -- tables, strikethrough, footnotes, definition lists and the
  typographer (curly quotes, the ellipsis, en and em dashes) -- so the
  two sites read and set a post the same way. markdown-it's
  `(c)`/`(tm)`/`(r)` substitutions are the exception, left off because
  Goldmark has no equivalent and this publication writes `501(c)(3)`.
  The config also reads the site's data files from beside itself:
  `TAG_DISPLAY` and `AUTHOR_DISPLAY` from `data/tags.json` and
  `data/authornames.json`, the slug-to-name maps for tags and authors
  (both reach Pelican as slugs so their URLs are exact; see `tags.py`
  and `sites.author_slug`), and `AUTHOR_LINKS` from
  `data/authors.json`. They are the same three files the hugo
  site reads through `hugo.Data` -- `sites.write_data_files` writes
  them for both -- and they are kept out of the config because a name
  or a profile is what a checked-in copy of a site corrects by hand
  while this file is generated; a missing one leaves the terms showing
  as their slugs rather than failing the build. The config also renders
  `INTRO`, site.json's landing-page blurb, through the reader's own
  parser: `index.html` emits it into the same `.intro` block the hugo
  landing page uses, and Jinja has no Markdown filter to do it in the
  theme.
- `site_plugin.py` is appended verbatim after the filled config. It
  gives Pelican the redirect stubs Hugo renders for aliases (and the
  `_redirects` file both exporters write), the responsive body images
  the hugo theme's render hook produces (with the first one eager, as
  there), the sitemap and robots.txt Hugo generates on its own, the
  related posts Hugo's related content gives each post (scored the
  same way: shared tags, then author, then date; `article.html` reads
  `article.related_posts`), and the
  names tags and authors are shown under (from `TAG_DISPLAY` and
  `AUTHOR_DISPLAY`, the config's reading of `data/tags.json` and
  `data/authornames.json`, set on the `Tag` and `Author` objects so the
  theme and the per-term feeds both pick them up; both reach Pelican as
  slugs, so their URLs match the hugo site's exactly). It refers to
  names the config defines (`SITEURL`, `PATH`, `TAG_DISPLAY`,
  `AUTHOR_DISPLAY`, `NOINDEX`, and the reader's plugin class in its
  `PLUGINS` line), so it is not importable on its own; the config in
  turn takes `BODY_IMAGE_ATTR` from it, the one definition of the
  marker both halves use.
- `theme/templates/jsonld.html` is the hugo partial of the same name
  in Jinja, included by `base.html` after the page's address, name
  and share image are set; author profiles come from `AUTHOR_LINKS`
  (the config's reading of `data/authors.json`) and the publisher's
  from `PROFILES`, which site.json fills in directly.
- `theme/templates/` is the Jinja theme. `author.html` is `tag.html`
  with the `tag` variable swapped for `author`; keep them in step. Each
  template names its page in a `name` block; `base.html` composes the
  `<title>` and `og:title` from it, adding the page number of a
  paginated listing and the site name, and takes the page's own
  address from Pelican's `output_file`, so page 2 of a listing is
  canonical to itself rather than to page 1. A template that sets
  `noindex` (the search page) gets a `noindex` robots tag.

## myst/

`listing-covers.mjs` is the companion transform for the myst-listing
gallery plugin; its header comment explains why cover images need it.
