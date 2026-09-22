# Site scaffolding

Files the site exporters copy into each generated site: generator
configs, themes, CSS and shared JS. Edit them here; copies in a
generated site are overwritten on the next export.

Loading (`sites.template_text`, `sites.fill_template`):

- Files are copied byte-for-byte, except:
- An `@include <path>` marker line (`<!-- @include shared/x.html -->`,
  `/* @include shared/x.css */`) is replaced by that templates-relative
  file. This is how both card themes share `shared/`.
- `*.tmpl` files are filled with `string.Template` (`$title`,
  `$base_url`, ...). Site data is not templated in: it is written as
  separate data files (`config/_default/params.toml` for Hugo,
  `site.toml` for Pelican) that the config reads, so `pelicanconf.py`
  is not a template.

The shared snippets and CSS are emitted verbatim, so they carry no
comments; their rationale is below. Go-template and Jinja comments are
fine.

## shared/ (Hugo and Pelican)

These must contain no `{{ }}` or `{% %}` syntax (enforced by a test).

- `theme-init.html`: runs before the stylesheet to apply a stored
  light/dark choice as `data-theme` on `<html>` without a flash. No
  attribute means `prefers-color-scheme` decides.
- `theme-picker.html`: light/system/dark picker in the header, hidden
  until its script runs. "System" clears the stored choice.
- `font-init.html`, `font-picker.html`: the body-font picker, a fixed
  `<select>` at the bottom-right, for comparing typography candidates.
  Default Source Serif (article) with Source Sans (chrome and
  headings). Choices, serif-bodied first: Source Serif, IBM Plex Serif,
  Literata, Merriweather; then Atkinson Hyperlegible Next, Helvetica,
  IBM Plex Sans, Inter, Source Sans, System UI. Code uses the choice's
  own mono face where it has one, otherwise the platform `ui-monospace`
  stack (Literata keeps Source Code Pro). `font-size-adjust` holds every
  choice at the default's x-height (`.486` on `body`, `.475` on
  `.post`), so the picker compares faces rather than sizes; it must
  follow the `font` shorthand, which resets it. A new candidate is a
  `:root[data-font=...]` block in `card.css` redefining `--body-font`
  and `--mono`.
- `link-init.html`, `link-picker.html`: the same pair for link colour,
  stacked above the font picker. Default `ink-accent` (ink text and
  underline, underline turns accent on hover). Others: `ink` (no hover
  accent), two blues at 7:1 and 5.5:1 contrast (with the accent hover),
  and the browser default. The hover underline is at least 2px
  (`--rule-w`). The accent itself (2.83:1) colours no link text. A
  candidate is one `:root[data-link=...]` block with light and dark
  values.
- `term-sort.html`: sort control for the tag/author chip indexes, by
  name (the no-JS order) or by count. Choice persists per browser.
- `nav-current.html`: sets `aria-current="page"` on the nav link whose
  path is the longest prefix of the current path.
- `feed-icon.html`: RSS icon SVG, used in the header and beside term
  headings that have a feed.
- `announcement.html`: fills the `.announcement` banner (emitted only
  when `site.toml` sets `announcement`) from its `data-source`: an
  http(s) URL is fetched (empty content keeps it hidden), anything else
  is literal HTML. The last fetched content is cached and rendered
  synchronously to avoid layout shift. Dismissal is stored per content,
  so a new announcement reappears. Content is wrapped in
  `.announcement-content` to match jupyter.org's banner metrics; the
  font is `--body-font`.
- `share-icons.html`: hidden SVG sprite of the LinkedIn, Facebook,
  Bluesky, Mastodon (Simple Icons) and email marks. The share bar itself
  is per engine (Hugo `_partials/share.html`, Pelican `share()` in
  `macros.html`) and rendered twice per post. LinkedIn and Facebook get
  the URL only (they read Open Graph tags); Bluesky and Mastodon get
  title and URL as `text`, Mastodon via share.joinmastodon.org. Hover
  darkens the marks rather than recolouring them, per brand guidelines.
- `image-zoom.html` (post pages only): makes a body image zoomable when
  its `width` attribute exceeds its rendered width, and opens the `src`
  (the full-size original) in a `<dialog>` captioned by alt text or the
  `<figcaption>`. Linked images are skipped. Closes on click, Esc or
  scroll.
- `clip-motion.html` (post pages only): clips are written as posters
  with `controls` and `preload="none"`; this script autoplays them muted
  and looped while on screen, unless `prefers-reduced-motion: reduce`.
  A clip the reader paused is not restarted. Covers Giphy `<video>`s
  too.
- `code-copy.html` (post pages only): wraps each article `<pre>` in a
  `.code-block` and adds a copy button from a `<template>` (clipboard
  and check icons toggled by the `hidden` attribute, since SVG elements
  lack a `hidden` property). Copies the text without its trailing
  newline and announces it through a live region. No button is added
  without the async clipboard API.
- `heading-anchor.html` (post pages only): adds a `#id` link to each
  body heading that already has an id (Goldmark, and the Pelican
  reader's anchors plugin). Done in script rather than markup so the
  mark stays out of feeds and the Pagefind index, and to have one
  implementation.
- `dark-palette.css`: included twice by `card.css`, for
  `data-theme="dark"` and for a dark system scheme with no stored
  choice. `--syn-*` are GitHub Primer syntax colours (every token clears
  4.5:1 on `--code-bg` except the light-palette comment grey; a test
  checks this), applied under `.post .highlight` to the class names
  Chroma and Pygments share.
- `newsletter.html`: the HubSpot signup band (`site.toml`
  `newsletter`). HubSpot renders in an iframe, so the page's ink,
  muted, accent and body-font values are passed as the embed's CSS,
  along with the layout (fields on one row, consent, then button), and
  re-passed when the theme, font or system scheme changes. The band
  stays hidden until the embed loads.
- `plausible.html`: Plausible's published queue stub, verbatim. The
  script tag itself (site-specific URL) is emitted by each base template,
  last in `<head>`, `async`, only when `plausible` is set.
- `card.css`: the stylesheet for both themes.

## hugo/

The theme uses current Hugo's layout names (`baseof.html`,
`home.html`, `page.html`, `section.html`, `taxonomy.html`,
`_partials/`, `_shortcodes/`, `_markup/`); `hugo.TEMPLATES` maps each
into the site, and `section.html` is also written as `term.html`.

- `README.md`, `gitignore`: copied to the site root as `README.md` and
  `.gitignore` (the latter named without the dot so git does not apply
  it here).
- `hugo.toml.tmpl`: taxonomies, related-posts indices, paginator,
  Goldmark and Chroma settings (`noClasses` off, so `card.css` colours
  tokens), plus `baseURL`, title and language.
- `params.toml.tmpl`: the theme's `[params]`, filled from `site.toml`
  (`hugo.params` merged last).
- `content/tags/_content.gotmpl`, `content/authors/_content.gotmpl`:
  content adapters creating a term page per entry of `data/tags.yaml`
  and `data/authors.yaml`, so terms display their names while URLs stay
  slugs, matching Pelican's URLs.
- `layouts/rss.xml`: full-content feeds (`<content:encoded>`), capped
  by `services.rss.limit`, with root-relative URLs made absolute and
  `srcset`/`sizes` removed.
- `layouts/_partials/post-image.html`: one body image with responsive
  webp variants (gif/svg/webp pass through), shared by the render hook
  and the figure shortcode. `first_image` in front matter loads eagerly
  at high priority.
- `layouts/_partials/paginator.html`: one paginator for body and head,
  so page 2+ of a listing has its own canonical URL, `og:url` and
  title.
- `layouts/_partials/jsonld.html`: the schema.org graph
  (`Organization`, `WebSite` with `SearchAction`, `BreadcrumbList`,
  `BlogPosting`, `ProfilePage`), built as dicts and jsonified.
- `layouts/_partials/related.html`: up to three "More posts" cards
  from Hugo's related content, excluded from the search index.
- `layouts/robots.txt`: names the sitemap, or disallows all under
  `noindex`.
- `layouts/_markup/render-image.html`: Markdown images, via the
  partial.
- `layouts/_shortcodes/figure.html`: captioned (optionally linked)
  image as `<figure>`/`<figcaption>`, caption passed as inner content.
  `hugo.figure_shortcodes` writes the calls.

## pelican/

- `README.md`, `gitignore`: as for Hugo.
- `pelicanconf.py`: copied verbatim; holds no site data and reads
  `site.toml`, `data/tags.yaml` (`TAG_DISPLAY`) and `data/authors.yaml`
  (`AUTHOR_DISPLAY`, `AUTHOR_LINKS`) from beside itself (a missing data
  file shows terms as slugs). Its main content is a markdown-it-py
  reader, registered through a plugin so the config loads without
  Pelican installed:
  - YAML front matter between `---` fences, passed to Pelican's
    metadata processors;
  - CommonMark plus tables, strikethrough, footnotes, definition lists
    and typographer, matching Goldmark (the `(c)`/`(tm)`/`(r)`
    replacements are off);
  - heading ids (anchors plugin), Pygments with the `highlight` class,
    restored `{attach}` placeholders, body-image marking for the site
    plugin, and the `::: figure` directive for captioned images.

  It also renders `INTRO` (landing-page blurb) with the same parser.
- `site_plugin.py`: appended to the config. Adds redirect stubs and the
  `_redirects` file, responsive body images (first one eager), sitemap
  and `robots.txt`, "More posts" (`article.related_posts`, scored by
  tags, author, date), and tag/author display names. It uses names the
  config defines, so it cannot be imported alone; the config takes
  `BODY_IMAGE_ATTR` from it.
- `theme/templates/`: the Jinja theme. `term.html` and `terms.html`
  implement tag/author pages and their indexes; `tag.html`,
  `author.html`, `tags.html` and `authors.html` set variables and
  include them. Each template sets a `name` block, from which
  `base.html` builds `<title>` and `og:title` (with page number); the
  canonical URL comes from `output_file`. `noindex` adds a robots tag.
  `jsonld.html` is the Jinja version of the Hugo partial.

## myst/

- `listing-covers.mjs`: companion transform for the myst-listing
  gallery; its header comment explains it.
- `README.md`, `gitignore`: as for Hugo (`myst.TEMPLATES`); the
  `.gitignore` covers `_build/`.
