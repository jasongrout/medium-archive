# Hugo vs Pelican for this archive

Both sites are generated from this archive by `medium-archive`, from the
same converted posts and the same shared theme, so they can be compared
on identical content. This is the comparison behind choosing which one
the blog ships on. The MyST site is out of scope; it stays the simpler
alternate (see `todo.md`, section 0).

**Recommendation: Pelican**, on extensibility. The two sites are
equivalent to a degree that leaves little to choose between them on
output, and Hugo is meaningfully faster to rebuild, so the decision
rests on which one this blog can grow into.

## How this was measured

```sh
medium-archive convert --clean --out .   # 336/336 posts, lint: 0 problems
medium-archive hugo --out .              # base_url http://localhost:1313
medium-archive pelican --out .           # base_url http://localhost:1314
cd site-hugo    && hugo    && pagefind --site public
cd site-pelican && pelican && pagefind --site output
```

Versions: hugo 0.158.0 extended, pelican 4.12.0, python 3.11.15,
markdown 3.10.3, pillow 12.3.0, pagefind 1.5.2, gifsicle 1.94.

`base_url` is pointed at a localhost port per engine so absolute links,
share URLs and Open Graph tags resolve while both sites are served and
driven in headless Chromium. `site.json` is restored afterwards; only
this file is committed.

## What the two sites have in common

| | Hugo | Pelican |
|---|---|---|
| Post URLs | 336 | 336 — identical sets |
| Total addresses | 1377 | 1211 |
| Pagefind index | 336 pages / 15905 words | 336 pages / 15868 words |
| `sitemap.xml` entries | 505 | 505 |
| Output size | 558 MB | 557 MB |
| Files | 3697 | 3530 |

Every address Pelican serves, Hugo serves too. The 166 Hugo has beyond
them are all `page/1/` redirect stubs, one per paginated listing, so a
reader who edits a URL to `/tags/binder/page/1/` lands on the term page
where Pelican returns 404. Every listing, index, feed, `sitemap.xml`,
`robots.txt` and `_redirects` file is present in both.

Rendered in headless Chromium at 1280x900, in light and dark, **no
probed metric differed**:

| page | metric | both |
|---|---|---|
| home | cards / images | 24 / 21 |
| post | share links / related / JSON-LD | 10 / 3 / 1 |
| tags | chips | 57 |
| authors | chips | 108 |
| home | body background, light / dark | `rgb(244,244,244)` / `rgb(19,19,19)` |

A code- and image-heavy post matched on all of: 14 `<pre>` blocks, 14
syntax-highlighted blocks, 7 figures with 7 captions, 4 responsive
`srcset` images, 1 eager first image. Article pages are pixel-identical
in dark mode.

## Where the two sites actually differ

These are the only differences found, and they are small. They are
listed because a comparison that reported nothing would be hiding the
resolution it was measured at, not because any of them decides the
choice.

**Related posts are chosen differently.** Both engines put three at the
foot of an article (335 of 336 posts agree on the count), but they pick
the same three on only 148 of 336, with a mean overlap of 2.13 of 3.
Both score by shared tags, then author, then date; Hugo's own related
index and the Pelican plugin's scoring simply rank ties differently.
Neither is wrong.

**Markdown edge cases resolve differently**, on 27 of 336 posts:

- **Hugo shows stray `**` to readers on 15 posts.** Goldmark is
  CommonMark-strict about emphasis flanking, so a malformed marker in
  an old post stays literal text: "Thanks to Bloomberg\*\*, Saturday,
  August 25th\*\*". python-markdown is more forgiving and renders the
  emphasis, which reads correctly. Pelican is better here.
- **Pelican silently drops bare `<angle-bracket>` words on 2 posts.**
  `recipes_emscripten/<my_package>` loses `<my_package>` entirely, and
  `#include <wasm_simd128.h>` loses the header name. Hugo escapes them
  and keeps the text. Hugo is better here, and this is the one
  difference that loses content rather than formatting.
- **Hugo applies typographic substitution** that Pelican does not:
  straight quotes become curly on 21 posts, `...` becomes `…` on
  several more. Cosmetic, and arguably an improvement, but it means
  the two sites do not render byte-identical prose.

**Dates are formatted differently** on every post: Hugo renders
"September 2, 2026", Pelican "September 02, 2026". Purely the format
string on each side.

Body-image alt text matches on 333 of 336 posts; the 3 that differ are
the same typographic substitution.

## Build performance

Hugo and Pelican cache different things, so the honest comparison is
two numbers, not one.

| | Hugo | Pelican |
|---|---|---|
| Exporter step (`medium-archive <engine>`) | 11.0 s | 11.0 s |
| Generator build, no caches | 18.0 s | 20.4 s |
| **Generator rebuild, caches warm** | **1.1 s** | **5.5 s** |

The exporters are equal: both place the same display copies out of the
shared `.image-cache/`, and both take about 11 seconds.

A cold build is close, because both are dominated by image encoding —
Hugo's image pipeline and the Pelican plugin's Pillow pass do the same
work. Hugo keeps its results in `resources/` (11 MB), Pelican keeps its
webp variants beside the images in `output/`; deleting either forces
the re-encode, which is what CI does on a fresh clone.

The rebuild is where they part. With caches warm, Hugo re-renders the
whole site in about a second; Pelican takes five, because it re-renders
every page every time and has no page-level cache. That is the number
that matters while writing a post, and Hugo wins it by 5x.

## Code weight

Engine-specific code carried by the exporter:

| | Hugo | Pelican |
|---|---|---|
| Exporter driver (Python) | 331 | 262 |
| Templates | 460 (Go, 20 files) | 384 (Jinja, 12 files) |
| Generated config | 56 (TOML) | 149 (Python) |
| Site plugin | — | 370 (Python) |
| **Total** | **847** | **1165** |

A further 901 lines — `card.css` and the `shared/` JS snippets — are
spliced byte-identically into both themes and belong to neither.

Pelican needs those 370 plugin lines, in nine functions, to reproduce
what Hugo has built in: redirect stubs (Hugo's `aliases`),
`sitemap.xml`, `robots.txt`, responsive image variants, first-image
fetch priority, related posts, and the display names for tags and
authors. That gap is real, and it would widen with any further
WordPress-style SEO behavior.

The templates invert it. The same page-title logic, from the two base
templates:

```go-html-template
{{ with $pager }}{{ $url = .URL | absURL }}{{ if gt .PageNumber 1 }}{{ $name = printf "%s · Page %d" $name .PageNumber }}{{ end }}{{ end }}
```

```jinja
{% set page_suffix = " · Page " ~ articles_page.number if articles_page and articles_page.number > 1 else "" %}
```

`layouts/_default/rss.xml` shows the ceiling: three chained `replaceRE`
calls on one line to absolutize URLs and strip `srcset` from feed
content, because Go templates have no real string processing. Pelican
gets full-content Atom feeds from its own machinery with no template at
all.

## Extending it

This is where the two genuinely differ, rather than differing by degree.

**Pelican has in-process extension points, and this exporter already
uses them.** `pelicanconf.py` is executed Python: it defines a
python-markdown `Treeprocessor` inline to mark and lazy-load body
images, and appends a plugin that hooks Pelican's signals. Anything
that needs to touch a post between "read from disk" and "written as
HTML" has somewhere to go.

The two extensions this blog is most likely to want both land there:

- **Notebook-sourced posts.** Registering a `.ipynb` reader is 26
  non-blank lines in `pelicanconf.py` — a `BaseReader` subclass
  connected to the `readers_init` signal. Built and run against a real
  notebook: its executed outputs became the post body, and its
  metadata fed Pelican's native tag, author and date handling.
- **MyST.** The same reader hook takes myst-parser, which is a
  docutils plugin, alongside Pelican's own docutils-based reader.

**Hugo has no in-process equivalent.** It is a single Go binary, and
`exec` is not a template function — a build that calls one fails with
`function "exec" not defined`. Notebooks therefore need an out-of-band
pre-build step (`nbconvert` to Markdown) plus a separate watcher to
keep `hugo server`'s live reload honest, and MyST directives would have
to be reimplemented as Go-template shortcodes. Hugo's extension surface
is templates, shortcodes, render hooks and content adapters: enough to
shape a site, not enough to change how a post is read.

## Verdict

Hugo is better on three counts, and they are not trivial: rebuilds are
5x faster, it needs 318 fewer lines of engine-specific code, and it is
far more widely used, which matters for finding answers and for
long-term viability. It also handles one Markdown edge case better and
gives redirect stubs for `page/1/` for free.

It is not, however, *much cleaner or better*, which is the bar for
overriding a preference for Python. Its template language is
measurably harder to read for the same logic, its stray-emphasis
handling is worse on more posts than its angle-bracket handling is
better, and it is closed to precisely the two extensions this blog is
most likely to want.

Pelican costs 5-second rebuilds — tolerable for authoring, and it will
grow with the archive — and 370 lines of plugin that Hugo gets for
free. It buys extension points at the reader and Markdown layer, in the
language the rest of the Jupyter toolchain is written in.

The choice is also low-regret. Both engines produce the same site
today, and the 901-line shared theme is engine-neutral, so a later
switch costs the engine-specific layer rather than the design. Picking
one also lets the other exporter be deleted, the way `zola` already
was.
