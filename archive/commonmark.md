# A CommonMark renderer for the Pelican site

Pelican renders Markdown with [python-markdown][], which predates
CommonMark and does not follow it. Hugo renders with Goldmark, which
does. `compare.md` measured that gap from the outside: the two sites
disagree on 27 of 336 posts, and every disagreement is a place where
python-markdown guesses and Goldmark applies the spec. Writing new
posts against a spec, rather than against one implementation's habits,
argues for replacing the renderer now that Pelican is the chosen
engine.

[markdown-it-py][] is the CommonMark reference port for Python, is what
MyST and Jupyter Book parse with, and carries the same optional
extensions Goldmark offers. This file records what it costs to put it
under Pelican for this archive.

**Summary.** Plugins exist; `pelican-markdown-it-reader` is the closest
maintained one, and installing it renders all 336 posts, but as it
stands it costs this site heading ids, syntax-highlighting colours,
figure captions and half its responsive images. The fuller
`minchin.pelican.readers.commonmark` builds nothing at all until the
front matter is YAML, and then invents 103 tag pages out of `#123`
issue references until told not to. A reader written into
the config the exporter already generates -- 74 lines of Python, no
plugin -- reproduces the current site exactly: every listing, tag,
author, feed and archive page identical, and 73 of 336 article pages
differing only where the two parsers genuinely disagree. One of those
differences fixes the one defect `compare.md` recorded against Pelican
that lost content; another recovers lists python-markdown ran into a
paragraph. The one that reads worse -- malformed emphasis markers left
literal, 18 posts -- is what Goldmark does too, and belongs in
`convert` rather than in the renderer.

[python-markdown]: https://python-markdown.github.io
[markdown-it-py]: https://markdown-it-py.readthedocs.io

## How this was measured

```sh
medium-archive convert --clean --out .    # 336/336 posts
medium-archive pelican --out .
cd site-pelican && pelican                # once per renderer, output/ cleaned between
```

Versions: pelican 4.12.0, python 3.11.15, markdown 3.10.3,
markdown-it-py 4.2.0, mdit-py-plugins 0.6.1, pygments 2.19.2, pillow
12.3.0, pelican-markdown-it-reader 3.0.0.

Three full builds were compared page by page (1211 pages each), with
attribute order, self-closing form and whitespace canonicalised so only
real differences count: the current python-markdown build, the same
site with `pelican-markdown-it-reader` installed, and the same site
with a reader written for it.

## What exists off the shelf

| package | latest | parser | front matter | notes |
|---|---|---|---|---|
| [pelican-markdown-it-reader][mdit-reader] | 3.0.0, 2026-06-28 | markdown-it-py 4 | YAML, with a `Key: value` fallback | MIT, pelican >= 4.11, 223 lines, tables + footnotes + deflists, Pygments fences, restores `{attach}`-style placeholders |
| [minchin.pelican.readers.commonmark][minchin] | 2.4.2, 2026-08-12 | markdown-it-py | YAML (can be turned off) | front matter, footnotes, deflists, tables, strikethrough, sub/sup on by default; pulls in beautifulsoup4 and the author's plugin autoloader |
| [pelican-myst-reader][myst] | 1.4.0, 2024-09-19 | myst-parser (markdown-it-py underneath) | YAML | AGPL-3.0; MyST is a CommonMark superset, so this is the heavier "MyST everywhere" option rather than a plain renderer swap |
| [pelican-frontmark][frontmark] | 1.2.1, 2019-12-09 | commonmark.py | YAML | unmaintained, pre-dates markdown-it-py |
| [theskumar/pelican-commonmark][theskumar] | 2018 | commonmark.py | none | unmaintained |

[mdit-reader]: https://github.com/gaige/markdown-it-reader
[minchin]: https://github.com/MinchinWeb/minchin.pelican.readers.commonmark
[myst]: https://github.com/ashwinvis/myst-reader
[frontmark]: https://github.com/noirbizarre/pelican-frontmark
[theskumar]: https://github.com/theskumar/pelican-commonmark

One mechanic is worth knowing before installing any of them. Pelican
imports every installed `pelican.plugins.*` namespace package at
startup, and `Readers.__init__` maps *every* `BaseReader` subclass it
can see onto that subclass's file extensions. A reader plugin therefore
takes over `.md` as soon as it is installed, whether or not it appears
in `PLUGINS` -- this site's `PLUGINS` list names only its own site
plugin, and installing the package still switched the renderer for the
whole build.

## What a drop-in install does to this site

`pelican-markdown-it-reader` builds all 336 posts and resolves
`{attach}` correctly. Measured against the current build:

| | python-markdown | markdown-it-reader |
|---|---|---|
| posts with heading ids | 248 | 0 |
| posts whose code blocks carry the theme's `highlight` class | 112 | 0 (`codehilite` instead) |
| pages leaking `markdown="span"` into the HTML | 0 | 189 |
| pages showing unrendered Markdown in a caption | 0 | 40 |
| posts with responsive `srcset` images | 60 | 36 |
| body images with `width`/`height` | 2009 | 1538 |

The `srcset` row is a comparison, not an absolute: both builds ran on
an export made without Pillow, which leaves fewer images in a format
the variant ladder covers. With Pillow at export, the same site has 81.

Each has the same cause: the generated `pelicanconf.py` reaches into
python-markdown, and the plugin exposes no equivalent hooks.

- **Heading ids** come from python-markdown's `toc` extension. The
  plugin enables tables, footnotes and deflists, and nothing else, so
  headings lose their ids and Pagefind loses its per-section anchors.
  `mdit_py_plugins.anchors` is the counterpart.
- **The highlight class** is hard-coded to `codehilite` in the plugin's
  fence rule, while the shared theme styles `.highlight` -- the class
  Chroma emits for Hugo and codehilite is configured to emit here. The
  tokens are still marked up; they simply come out uncoloured.
- **Figure captions.** `convert`'s captioned images become a `<figure>`
  shell with `markdown="span"`, which is python-markdown's `md_in_html`
  telling it to render Markdown inside an HTML block. CommonMark says
  the contents of an HTML block are raw, so the attribute leaks and 40
  pages show `[text](url)` and `**bold**` to the reader.
- **Responsive images.** The config marks every image in an article's
  Markdown tree with `data-body-image` and `loading="lazy"` through a
  python-markdown `Treeprocessor`; the site plugin's post-build pass
  reads that mark to encode webp variants and stamp dimensions.
  Unmarked, only the images inside figure shells (which carry the
  attribute literally) keep the treatment.

## Adopting minchin's reader, measured

`minchin.pelican.readers.commonmark` is the most complete of the
packaged readers (1143 lines across the package, against 223 for
`pelican-markdown-it-reader`), so it was run against this site rather
than judged from its README. It can be configured into parity, and the
configuration is the argument against it.

As installed and listed in `PLUGINS`, with the site as the exporter
writes it today: **0 of 336 articles build.** The reader wants YAML
front matter; against Pelican's `Key: value` headers it finds no
metadata and Pelican skips every file ("could not find information
about 'title'"). With the headers rewritten as YAML, all 336 build in
21 s, and then:

| | as configured today | with minchin, defaults | after configuring it |
|---|---|---|---|
| articles built | 336 | 336 (YAML front matter first; 0 without) | 336 |
| tag pages (plus the index) | 58 | **161** | 58 |
| posts with heading ids | 248 | 0 | 248 |
| body images with `width`/`height` | 2009 | 1538 | 2009 |
| posts with the theme's highlight class | 112 | 112 | 112 |
| build warnings | 6 | 120 | 120 |

The tag row is the one to look at. The reader harvests Obsidian-style
inline `#tag` tokens out of the body, so every `#3288` issue reference
and `#Masks4All` hashtag in a post became a tag with its own page --
57 real tags became 160 -- and those tokens are stripped from the text
that reaches the reader. Turning it off means setting
`COMMONMARK_INLINE_TAG_SYMBOLS` to a character no post uses; setting it
to the empty string throws inside the reader and takes all 336 articles
down again.

The 114 remaining warnings, one per internal `/posts/<slug>/` link in
the archive, come from the reader's own link rewriting: it prefixes
relative links with `{filename}` or `{static}` by extension and warns
about anything else, and root-relative site links are anything else. It
leaves them alone, correctly, but the build is never clean again --
which matters for a repo whose CI is green on "0 problems".

The figure captions are missing from the table because no reader fixes
them: 189 pages leak `markdown="span"` under minchin exactly as they do
under the other two, since that is CommonMark, not the plugin. It is
the exporter's to fix, whichever reader is chosen.

Parity on the rest is reachable. Its fence rule emits `codehilite
highlight`, so the theme's stylesheet matches; heading ids and the
body-image marking go in through `COMMONMARK["extensions"]`, though not
as render rules -- the reader installs its own `image`, `link_open` and
`fence` rules *after* the extensions, so anything of ours in those
slots is overwritten and the marking has to be done as a core rule that
sets token attributes instead. Beyond that the package brings
opinions this site does not want (first `<h1>` promoted to the title
and removed from the body, a duplicate-`<h1>` pass), a BeautifulSoup
parse and re-serialisation of every article, a monkey-patch of
`Readers.check_file`, a dependency on the author's plugin autoloader,
and a fresh `MarkdownIt` built per file.

`pelican-markdown-it-reader` is the opposite trade: 223 readable lines,
no opinions beyond CommonMark, but its `_build_md` takes no
configuration at all, so heading ids, the theme's highlight class and
the body-image marking cannot be reached from outside it.

**Recommendation: write the reader.** The generated `pelicanconf.py` is
already the place where this site's Markdown layer is configured, the
reader is 74 lines against 1143, and it reproduces today's site exactly
with no settings to discover and no behavior to switch off. The real
dependency either way is markdown-it-py, which is doing the parsing in
all three options; what a package adds on top of it here is another
project's idea of what a blog post is. Should that change -- if the
exporter ever wants MyST, or wiki links, or inline tags -- adopting a
reader then is a `PLUGINS` line, and the YAML front matter recommended
below is the only part of the archive that would have to move first.

## Writing one instead

The config the exporter generates is executed Python that already
defines a python-markdown extension inline, so a reader is a natural
thing to put there. The whole of it, minus the metadata header parsing
and imports:

```python
def _make_md():
    md = _MarkdownIt("commonmark", {"xhtmlOut": False}).enable("table")
    md.use(_footnote).use(_deflist)
    md.use(_anchors, max_level=6, slug_func=lambda s: _slugify(s, "-"))

    def fence(self, tokens, idx, options, env):        # theme's class
        token = tokens[idx]
        lexer = (_lexer_by_name(token.info.split()[0]) if token.info
                 else _guess_lexer(token.content))
        return _highlight(token.content, lexer,
                          _HtmlFormatter(cssclass="highlight", wrapcode=True))

    def image(self, tokens, idx, options, env):        # the Treeprocessor
        token = tokens[idx]
        token.attrSet("src", _unescape_placeholders(token.attrGet("src")))
        token.attrSet("loading", "lazy")
        token.attrSet(BODY_IMAGE_ATTR, "")
        return self.image(tokens, idx, options, env)

    def link_open(self, tokens, idx, options, env):    # {attach}, {static}
        token = tokens[idx]
        token.attrSet("href", _unescape_placeholders(token.attrGet("href")))
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("fence", fence)
    md.add_render_rule("image", image)
    md.add_render_rule("link_open", link_open)
    return md


class _CommonMarkReader(_BaseReader):
    enabled = True
    file_extensions = ["md", "markdown", "mkd", "mdown"]
    ...
```

`_unescape_placeholders` turns `%7Battach%7D` back into `{attach}`:
markdown-it percent-encodes link targets, and Pelican's intra-site link
pass needs the brace form. Everything else is a `BaseReader` subclass
connected to the `readers_init` signal, plus a loop over the article's
one-line `Key: value` header. 74 non-comment lines in total.

With it in place, every metric in the table above returns to its
python-markdown value: 248 posts with heading ids, 112 with `.highlight`
code, 2009 body images with dimensions, 81 with `srcset` (see the note
under the table above), no leaked attributes, no unrendered captions. Build time is unchanged (21.9 s vs
22.6 s for 336 posts), and the build's warnings are the same six
cosmetic empty-alt ones. Of 1211 pages, the 875 listing, tag, author,
archive, search and feed pages are identical; 73 of the 336 article
pages differ.

The dependency ledger improves slightly. `markdown` is an optional
extra of pelican, not a requirement; Pygments is required either way.
The swap trades `markdown` for `markdown-it-py` and `mdit-py-plugins`.
The reader above borrows python-markdown's `slugify` so heading ids stay
byte-identical with today's site; standalone it is six lines
(`unicodedata.normalize`, strip non-word characters, lowercase, join on
hyphens), after which python-markdown is gone entirely -- the config's
one other use of it, rendering `site.json`'s landing-page intro, is the
same one-line call on either library.

## What has to change in the posts

**Figure captions must be rendered at export.** This is the one real
change to what `medium-archive pelican` writes, and it moves the
Pelican content toward the Hugo content: the Hugo exporter already
hands captions to a shortcode rather than relying on the renderer to
descend into HTML. In this archive that is 728 captions across 189
posts. The `<figure markdown="1">` variant (the shell around an embed
link, 10 posts) just drops its attribute; its contents are separated by
blank lines, which ends the HTML block and lets CommonMark parse them
anyway.

**Front matter is optional but worth doing.** The reader can read the
`Key: value` headers Pelican has always used, and the prototype does.
Every off-the-shelf plugin prefers YAML between `---` fences, `posts/`
already writes a `---`-fenced JSON block, and the Hugo site's front
matter is JSON, so moving Pelican to YAML would leave the two engines'
content differing only in the fence -- and would make any of the
packaged readers a drop-in for the custom one.

Nothing else in the tree is affected: `{attach}` image colocation, tags
and authors as slugs, `Cover`, `Summary` and `Canonical` headers, and
the redirect stubs all behave as before.

## Where the pages actually change

The 73 article pages that differ, by cause:

| posts | difference | reads better |
|---|---|---|
| 18 | a malformed emphasis marker stays literal: `task**.**`, `*"quoted,"*said` | python-markdown |
| 15 | non-ASCII characters percent-encoded in a link target (`/posts/and-voil%C3%A0/`) | equivalent |
| 14 | `***text***` nests as `<em><strong>` rather than `<strong><em>` | equivalent |
| 13 | two blockquotes separated by a blank line stay two, instead of merging into one | CommonMark |
| 9 | a list boundary is read differently: a `- item` directly under a paragraph line becomes a list (2 posts), a sub-list attaches to the item above it, a bullet list after a numbered one stays its sibling | markdown-it, or equivalent |
| 5 | an ordered list starting at 3 renders `<ol start="3">` | markdown-it |
| 3 | a fence with no language gets a different Pygments guess | equivalent |
| 2 | a bare `<my_package>` / `<wasm_simd128.h>` survives as text | markdown-it |
| 1 | a code span in a caption breaks at a different backtick | equivalent |

The last row but one is the defect `compare.md` recorded against
Pelican and in favour of Hugo, now fixed: the bare angle-bracket words
Pelican silently dropped, which was the one difference that lost
content. Two posts also gain lists that python-markdown left as a
paragraph of literal `- ` text, because CommonMark lets a bullet list
interrupt a paragraph and python-markdown wants a blank line first.

The 18 stray markers are the difference `compare.md` already records
against Hugo (15 posts showing a stray `**`; the count here also covers
single `*`), and they arise the same way. CommonMark's flanking rules
refuse to open emphasis on a `**` sitting between a word character and
punctuation, and the markers come from Medium's editor wrapping a stray
period or quote in `<strong>`. The renderer is not the place to fix that. `convert` knows
it is emitting emphasis around nothing but punctuation, so it can drop
or reposition the marker at conversion time, which fixes Hugo and
Pelican together; a `lint` rule for "emphasis a CommonMark parser will
not open" is the way to keep it fixed.

## What the swap buys

Goldmark's optional extensions have markdown-it-py counterparts, which
is the point of picking this parser rather than a bare CommonMark one:

| Goldmark / Hugo | markdown-it-py |
|---|---|
| tables | built in (`enable("table")`) |
| strikethrough | built in (`enable("strikethrough")`) |
| task lists | `mdit_py_plugins.tasklists` |
| footnotes | `mdit_py_plugins.footnote` |
| definition lists | `mdit_py_plugins.deflist` |
| attributes (`{.class #id}`) | `mdit_py_plugins.attrs` |
| typographer (curly quotes, en dashes, ellipses) | `typographer: True` plus the `smartquotes`/`replacements` rules |
| auto heading ids | `mdit_py_plugins.anchors` |
| linkify | `enable("linkify")`, needs `linkify-it-py` |
| passthrough / math | `mdit_py_plugins.dollarmath`, `.texmath`, `.amsmath` |
| shortcodes | no equivalent; `mdit_py_plugins.container` and `.admon` cover the block cases |

`MarkdownIt("gfm-like")` turns on the GitHub-flavoured set in one call.
Two knobs are worth a decision rather than a default: the typographer,
which is on in Hugo and accounts for the curly quotes on 21 posts that
`compare.md` recorded as a difference between the sites, and linkify,
which turns bare URLs into links and would change 2015-era posts.

## Recommended order

1. **(Done 2026-09.)** In medium-archive, captioned images became a
   `::: figure` directive the reader renders -- the counterpart of the
   hugo exporter's figure shortcode -- rather than raw HTML needing
   `md_in_html`, and the generated `pelicanconf.py` carries the reader
   in place of the `_BodyImages` extension and the `MARKDOWN` setting.
   The measured result is the one this file predicts: 336 posts, six
   warnings, every non-article page identical, 73 article pages
   differing. See `commonmark-plan.md` in that repository.
2. Decide the extension set (typographer yes, to match Hugo; linkify
   probably not) and the front-matter format (YAML, to match everything
   else).
3. Separately, in `convert`, stop emitting emphasis that wraps only
   punctuation, and lint for markers CommonMark will not open. That is
   the only change that touches the posts' text, and it improves the
   Hugo site too.
