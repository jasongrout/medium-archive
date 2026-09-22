# A CommonMark reader for the Pelican site

Pelican's default Markdown renderer, python-markdown, does not follow
CommonMark; Hugo's Goldmark does. This caused the 27-post difference
recorded in `compare.md`. The Pelican exporter now reads posts with
[markdown-it-py](https://markdown-it-py.readthedocs.io) through a reader
defined in the generated `pelicanconf.py`.

## Decision: a custom reader, not a packaged plugin

Measured against the archive (336 posts, 1211 pages), with pelican
4.12.0, markdown-it-py 4.2.0, mdit-py-plugins 0.6.1:

- **pelican-markdown-it-reader** 3.0.0 builds every post, but its
  parser takes no configuration: no heading ids, `codehilite` instead
  of the theme's `highlight` class, and no body-image marking for the
  responsive-image pass.
- **minchin.pelican.readers.commonmark** 2.4.2 builds nothing without
  YAML front matter, then turns `#123` references into tags (57 tags
  became 160) and warns on every internal link. It can be configured to
  parity, but also brings a BeautifulSoup pass, h1-as-title handling
  and a monkey-patch of `Readers.check_file`.
- **A reader in `pelicanconf.py`** (74 lines at the time) reproduced
  the site exactly: all 875 non-article pages identical, 73 article
  pages differing only where the parsers disagree.

Installed `pelican.plugins.*` readers take over `.md` whether or not
they appear in `PLUGINS`.

## What was changed

- Captioned images are written as a `::: figure` directive (the
  counterpart of the Hugo figure shortcode) instead of raw HTML that
  needed python-markdown's `md_in_html`. `:::` was chosen over Hugo's
  `{{< >}}` syntax because it is shared with MyST and Pandoc and parsed
  by `mdit_py_plugins.container`.
- The reader enables tables, strikethrough, footnotes, definition
  lists, heading anchors and the typographer, matching Goldmark. The
  `(c)`/`(tm)`/`(r)` replacements are off (Goldmark lacks them, and
  they changed `501(c)(3)`). Linkify and task lists are off.
- Code blocks use Pygments with the `highlight` class.
- Front matter is YAML between `---` fences, as in `posts/` and the
  Hugo site, so a packaged reader would be a drop-in replacement.
- `convert` unwraps emphasis around punctuation only and writes
  unparseable emphasis as `<em>`/`<strong>`; `lint` reports any left.
  This fixed stray markers on both sites (46 posts changed).
- `convert` prefers the editor state over the RSS body, which restored
  inline code the feed drops.

## Resulting differences from python-markdown

| posts | difference | better |
|---|---|---|
| 18 | malformed emphasis stays literal (since fixed in `convert`) | -- |
| 15 | non-ASCII link targets percent-encoded (since avoided: page names are ASCII) | equivalent |
| 14 | `***text***` nests as `<em><strong>` | equivalent |
| 13 | blockquotes separated by a blank line stay separate | CommonMark |
| 9 | list boundaries read differently (2 posts gain lists) | markdown-it |
| 5 | ordered list start numbers kept | markdown-it |
| 3 | different Pygments guess for unlabelled fences | equivalent |
| 2 | bare `<my_package>` / `<wasm_simd128.h>` kept as text | markdown-it |
| 1 | code span in a caption split differently | equivalent |

Build time was unchanged (21.9 s vs 22.6 s).
