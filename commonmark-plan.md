# Plan: a CommonMark renderer for the Pelican exporter

Pelican renders Markdown with python-markdown, which follows no
specification; the Hugo exporter's Goldmark follows CommonMark. The two
sites disagree on 27 of 336 posts of the reference archive because of
it. This plan replaces the Pelican site's renderer with markdown-it-py,
the CommonMark reference port for Python, so posts can be written
against a specification with the optional extensions Goldmark offers.

The measurements behind it, taken against the reference archive
(336 posts, 1211 pages), are in that archive's `commonmark.md`:
what the packaged reader plugins cost, what a reader written for this
exporter costs, and every page whose rendering changes.

## Decisions taken

**Write the reader; do not adopt a packaged one.** The three candidates
were measured. `minchin.pelican.readers.commonmark` builds 0 of 336
articles until the front matter is YAML, then turns 57 tags into 160 by
harvesting `#123` issue references out of post bodies, drops every
heading id, and warns once per internal link. It configures back to
parity, but the configuration is the argument against it, and it brings
a BeautifulSoup pass, an h1-as-title rule and a monkey-patch with it.
`pelican-markdown-it-reader` is 223 clean lines but its parser build
takes no configuration at all, so the theme's highlight class, heading
ids and the body-image marking cannot be reached. The reader written
here is 74 lines in the config this exporter already generates and
reproduces today's site exactly.

**Figures become a directive the reader renders, not HTML in the
content.** Pelican has no shortcodes, but the reader is an extension
point, and a markdown-it container is the analogue of the Hugo figure
shortcode. Each exporter already writes figures in its engine's idiom
(hugo a shortcode, myst a `:::{figure}` directive); only pelican bakes
raw HTML into the content, which is what needs python-markdown's
`md_in_html` to render a caption at all.

**`:::` rather than a `{{< >}}` shortcode syntax.** `:::` is a
convention shared with MyST and Pandoc, `mdit_py_plugins.container`
parses it (including not firing inside code fences), and it does not
imply a general shortcode system that this site does not have. The
alternative considered and rejected: teaching the reader Hugo's
`{{< figure >}}` syntax, which `hugo.figure_shortcodes` already emits on
one line, so both exporters would emit one identical string. Rejected
because `compare.md` chose Pelican and notes that choosing one lets the
other exporter be deleted; baking a Hugo-ism into Pelican content buys
parity with an exporter that may not outlive it. **This reverses if the
project decides to ship both engines indefinitely**, and it is ~25 extra
lines in the reader to change -- cheap now, expensive after the content
is exported either way. Neither `{{<` nor `:::` appears in any of the
336 posts.

**The front matter stays `Key: value` for now.** Changing it is
orthogonal to the renderer, and the reader reads either. See phase 4.

## The figure directive

The exporter writes, in place of today's `<figure markdown="span">`
shell:

```
::: figure src="{attach}images/001.png" alt="A screencast" link="https://demo.example"
The UI for **creating** an assignment, see [the docs](https://x.example).
:::
```

and the reader's render rule turns it into exactly the markup the theme
and the site plugin expect today:

```html
<figure>
<a href="https://demo.example"><img alt="A screencast" src="{attach}images/001.png" loading="lazy" data-body-image=""></a>
<figcaption>The UI for <strong>creating</strong> an assignment, see <a href="https://x.example">the docs</a>.</figcaption>
</figure>
```

Notes that the implementation has to honour:

- The caption is the container's body, rendered by the site's own
  parser with its `<p>` wrapper suppressed -- the counterpart of the
  Hugo shortcode's `RenderString`, and the reason the caption picks up
  whatever extension set the config enables.
- `src` is left exactly as written. `{attach}` is in an attribute the
  parser never touches, so Pelican's intra-site link pass resolves it
  after the render, as it does for today's raw HTML.
- `alt` and `link` are escaped for both `<` and `>` (an alt reading
  `File -> Hub` otherwise ends the tag early for anything reading it
  with a regex, Pelican's own link pass included), and quoted on the
  info line with the same backslash quoting `hugo.figure_shortcodes`
  uses; `shlex.split` undoes it on the reader side. The quoting helper
  belongs in `sites.py` so the two exporters share it.
- The `<img>` carries `loading="lazy"` and `BODY_IMAGE_ATTR`, in that
  form: `_prioritize_first_images` looks for the literal
  ` loading="lazy"` to promote the first image on a page, and
  `_optimize_article_images` keys on the marker. Image optimization is
  otherwise untouched -- encoding stays a post-build pass, because
  `{attach}` is unresolved and output paths do not exist until then.
- Figure shells around anything but a single image (the link an embed
  became, 10 posts in the reference archive) stay raw `<figure>` HTML
  and simply lose their `markdown="1"` attribute: their contents are
  blank-line separated, which ends the HTML block and lets CommonMark
  parse them.

## Phase 1+2 (one change): the swap

The exporter's directive and the reader that renders it have to land
together -- a directive means nothing to python-markdown.

**`src/medium_archive/pelican.py`**
- `figure_blocks` becomes the directive emitter, symmetric with
  `hugo.figure_shortcodes` and `myst.myst_figures`. No parser
  dependency: it builds a string.
- Docstring: the module's account of `markdown="span"` and md_in_html
  goes; the directive and the reader replace it.

**`src/medium_archive/sites.py`**
- The info-line quoting helper, shared with the hugo exporter.

**`src/medium_archive/templates/pelican/pelicanconf.py.tmpl`**
- Remove `_BodyImages` and the `MARKDOWN` setting.
- Add the reader: `MarkdownIt("commonmark", {"xhtmlOut": False})`
  (`xhtmlOut` off keeps the `<img>` shape the site plugin's regex
  expects), `.enable("table")`, the `footnote` and `deflist` plugins,
  `anchors` for heading ids with a six-line slugify inlined so
  python-markdown goes entirely, a `fence` rule on Pygments with
  `cssclass="highlight"` (the class the shared theme styles, and the one
  Chroma emits for hugo), an `image` rule (restore `{attach}`, mark the
  body image, lazy-load), a `link_open` rule (restore `{attach}`), and
  the figure container.
- A `BaseReader` subclass on the `readers_init` signal, reading the
  one-line `Key: value` header and rendering `FORMATTED_FIELDS`
  (Summary) through the same parser.
- `INTRO` renders through the same parser instead of
  `markdown.markdown`.

**Install lines and docs** -- `pelican markdown` becomes
`pelican markdown-it-py mdit-py-plugins` in `cli.py`, the `pelican.py`
docstring, `readme.py` (which generates each archive's README) and this
repository's README; `[dependency-groups] dev` swaps `markdown` for the
two.

**Tests** (`tests/test_site_exporters.py`) -- the three that assert the
`markdown=` shells change to assert the directive; new ones cover a
caption containing a link, emphasis, a code span, `&` and `<`; an alt
containing a quote and a `>`; a link-wrapped figure; and that the
generated config defines the reader and no `MARKDOWN`. A rendering test
runs the config's reader over a sample body and asserts the heading id,
the fence class, the marked lazy image, the resolved-later `{attach}`,
and the figure markup above.

**Acceptance, against the reference archive** -- 336 articles built, 6
warnings (the same cosmetic empty-alt ones), 248 posts with heading ids,
112 with `.highlight` code, 2009 body images with `width`/`height`, 60
with `srcset`, no `markdown=` attribute anywhere in the output, and a
page-by-page canonicalised diff against the python-markdown build
showing the 73 known article pages and no others.

## Phase 3: the extension set (each its own commit)

- Typographer on, for Hugo parity: curly quotes and ellipses on ~21
  posts of the reference archive. Re-run the hugo/pelican comparison
  afterwards; it should remove a row from `compare.md`.
- Strikethrough and task lists on: no effect on existing posts, and
  what a writer expects to work.
- Linkify off: it would rewrite bare URLs in 2015-era posts. Attributes
  (`{.class}`) only if a use appears.
- Document the enabled syntax in `templates/README.md` and in the
  generated archive README, so a writer knows what is available.

## Phase 4: the front matter (optional)

Three options: keep `Key: value` (no dependency, Pelican-native, no
churn); JSON fenced by `---` (stdlib, the shape `posts/<slug>/index.md`
and the hugo front matter already use); YAML (adds pyyaml, makes any
packaged reader a drop-in). Only worth doing if content parity with the
`posts/` layer is wanted for its own sake.

## Phase 5: the emphasis markers, in `convert`

CommonMark will not open emphasis on a `**` between a word character
and punctuation, so Medium's editor wrapping a stray period or quote in
`<strong>` shows the marker to the reader: 18 posts under the new
renderer, and 15 under hugo today. The renderer is not the place to fix
it. `convert` should drop emphasis whose content is only punctuation
and reposition markers CommonMark will not open, and `lint` should
report them so it stays fixed. This is the only change that touches the
text of a post, and it improves the hugo site equally.
