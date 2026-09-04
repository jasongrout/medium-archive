# Hugo vs Pelican for this archive

Both sites were generated from this archive and compared, to decide which
generator the blog ships on. The MyST site is out of scope here; it stays
the simpler alternate (see `todo.md`, section 0).

**Recommendation: Pelican.** Functionality is a tie to a degree that
surprised the comparison, so the decision falls to the second criterion,
extensibility, where the two differ structurally rather than by degree.

## How this was measured

Everything below was regenerated from `raw/` + `fixups/` on one machine,
so the two engines saw byte-identical content:

```sh
medium-archive convert --clean --out .   # 336/336 posts, lint: 0 problems
medium-archive hugo --out .              # base_url http://localhost:1313
medium-archive pelican --out .           # base_url http://localhost:1314
cd site-hugo    && hugo    && pagefind --site public
cd site-pelican && pelican && pagefind --site output
```

Versions: hugo 0.158.0 extended, pelican 4.12.0, python 3.11.15,
markdown 3.10.3, pillow 12.3.0, pagefind 1.5.2, gifsicle 1.94.

`base_url` was pointed at a localhost port per engine so that absolute
links, share URLs and Open Graph tags resolved while both sites were
served and driven in headless Chromium. `site.json` was restored
afterwards; only `compare.md` is committed.

## Functionality: a tie

| | Hugo | Pelican |
|---|---|---|
| Exporter step, warm image cache | 16.9 s | 16.8 s |
| Generator build, cold | 28.1 s | 32.6 s |
| **Generator rebuild, warm** | **1.6 s** | **9.0 s** |
| Pagefind index | 336 pages / 15905 words | 336 pages / 15869 words |
| Output size | 559 MB | 559 MB |
| Files / HTML files | 3713 / 1392 | 3758 / 1211 |
| Post URLs | 336 | 336 — identical sets |

The first Hugo export took 12 min, but that is the one-time
`.image-cache/` bake (800 images re-encoded, 139 resized, 501 MB ->
223 MB) which both exporters then hard-link from. Against a warm cache
the two exporter steps are within 0.1 s of each other.

The HTML count differs for two benign reasons. Hugo emits 167
`page/1/` redirect stubs (a reader who edits a URL to `/tags/binder/page/1/`
lands on the term page; Pelican 404s there) and a `/posts/` section page
with its own feed. Neither engine is missing a page the other has: the
336 post URLs are identical, and every listing, index, feed, sitemap,
`robots.txt` and `_redirects` file is present in both.

Rendered in headless Chromium at 1280x900, in light and dark, every
probed metric matched:

| page | metric | hugo | pelican |
|---|---|---|---|
| home | cards / images | 24 / 21 | 24 / 21 |
| post | share links / related / JSON-LD | 10 / 3 / 1 | 10 / 3 / 1 |
| tags | chips | 57 | 57 |
| authors | chips | 108 | 108 |
| home, dark | body background | `rgb(19,19,19)` | `rgb(19,19,19)` |

A code- and image-heavy post (`build-your-jupyter-dashboard-using-solara`)
matched on 14 `<pre>` blocks, 14 highlighted blocks, 7 figures with 7
captions, 11 lazy images and 1 eager first image. Article pages are
pixel-identical in dark mode.

Neither engine wins on features. Both carry the full feature set the
card theme promises.

## Defects found, two per engine

All four are small; they are recorded here because they were found by
the comparison, not because they favour either choice. All four are
fixed in `medium-archive`: the three below in
[#56](https://github.com/jasongrout/medium-archive/pull/56), and the
author URLs, which change an address and so were kept separate, in
[#57](https://github.com/jasongrout/medium-archive/pull/57). The
measurements above are from the builds as they stood when the
comparison ran, before those fixes.

### Hugo

1. **Author URLs are wrong today.** Hugo does not fold accents or strip
   punctuation from taxonomy terms, so the built site serves
   `/authors/frédéric-collonval/`, `/authors/jürgen-hermann/`,
   `/authors/michał-krassowski/`, `/authors/c.a.m.-gerlach/`,
   `/authors/joe-lucas-/` (trailing hyphen) and
   `/authors/matt-mccormick-@thewtex@fosstodon.org/` — two `@` and a dot
   in a URL path. Pelican transliterates to clean ASCII by default:
   `frederic-collonval`, `jurgen-hermann`, `michal-krassowski`,
   `cam-gerlach`, `joe-lucas`, `matt-mccormick-thewtexfosstodonorg`.
   `removePathAccents = true` alone is not enough: it folds the accents
   but leaves the dots, the `@`, the trailing hyphen and `ł`. The fix
   was to address authors by slug in both exporters, as tags already
   are, which also makes the two engines agree by construction rather
   than by coincidence.
2. **Cards ignore the curated description.** `partials/card.html` renders
   `.Summary`, Hugo's auto-summary of the body, rather than the
   `description` front matter that `convert` writes. All 336 posts have a
   curated description; 4 of the 24 cards on page 1 show different text
   because of it. The robotics post's card reads "Robotics education
   often hits a wall before the fun even begins…" where Pelican correctly
   shows the subtitle "A unified in-browser workflow from CAD to URDF
   kinematics". Fix: `or .Description .Summary`.

### Pelican

1. **`site.json`'s `intro` never reaches the landing page.** The Hugo
   landing page renders it through `content/_index.md`; the Pelican
   `index.html` template has no equivalent and the exporter does not pass
   `intro` into `pelicanconf.py` at all. A documented `site.json` key is
   silently dropped by one of the two preferred targets.
2. **The image pass reaches images it should not.** `site_plugin.py`'s
   `_optimize_article_images` matches `posts/[^/]+/images/[^/]+\.jpe?g`
   against finished HTML, which also matches the baked `cover.jpg` of the
   related-post cards at the foot of each article. The result is 231
   stray `cover-480.webp` files (2.0 MB) that Hugo never generates, and a
   `sizes="(max-width: 800px) 100vw, 736px"` hint on a card image
   displayed at roughly 300 px.

   This one is architecturally telling rather than merely cosmetic.
   Hugo's render hook operates on the Markdown AST, so it structurally
   cannot reach a card the template rendered. Pelican's post-build regex
   pass over final HTML has no such boundary, and gained one more place
   to be wrong the moment the theme grew related-post cards.

Cosmetic, not a defect: dates render "September 2, 2026" on Hugo and
"September 02, 2026" on Pelican (`"January 2, 2006"` versus `%B %d, %Y`).

## Code weight favours Hugo

Engine-specific code carried by this exporter:

| | Hugo | Pelican |
|---|---|---|
| Exporter driver (Python) | 297 | 220 |
| Templates | 447 (Go, 19 files) | 381 (Jinja, 12 files) |
| Generated config | 56 (TOML) | 120 (Python) |
| Site plugin | — | 311 (Python) |
| **Total** | **800** | **1032** |

901 further lines — `card.css` and the `shared/` JS snippets — are spliced
byte-identically into both themes and belong to neither.

Pelican needs those 311 plugin lines to reimplement what Hugo has built
in: redirect stubs (Hugo's `aliases`), `sitemap.xml`, `robots.txt`,
responsive image variants, first-image fetch priority, related posts, and
tag display names. That gap is real and would widen with any further
WordPress-style SEO behavior.

The templates invert the comparison. The same page-title logic, from the
two base templates:

```go-html-template
{{ with $pager }}{{ $url = .URL | absURL }}{{ if gt .PageNumber 1 }}{{ $name = printf "%s · Page %d" $name .PageNumber }}{{ end }}{{ end }}
```

```jinja
{% set page_suffix = " · Page " ~ articles_page.number if articles_page and articles_page.number > 1 else "" %}
```

`layouts/_default/rss.xml` shows the ceiling: three chained `replaceRE`
calls on a single line to absolutize URLs and strip `srcset` from feed
content, because Go templates have no real string processing. Pelican
gets full-content Atom feeds from its own machinery with no template at
all.

## Jupyter integration is the decisive difference

This was tested rather than assumed.

**Pelican has a first-class hook.** Registering a `.ipynb` reader is 26
non-blank lines inside `pelicanconf.py` (37 with blanks). Built and run:
a real notebook with executed outputs became a post, and its tags,
authors, date and slug fed Pelican's native taxonomies. See the appendix.
`readers_init` plus a `BaseReader` subclass is a documented extension
point, and the same hook accepts myst-parser, which is a docutils plugin.

**Hugo has no in-process equivalent.** Verified: `exec` is not a template
function — a build using it fails with `function "exec" not defined`.
Hugo is a single Go binary with no way to run Python during a build.
Notebook-sourced posts therefore require an external pre-build step
(`nbconvert` to Markdown) plus a separate file watcher to keep
`hugo server`'s live reload honest, and MyST directives would have to be
reimplemented as Go-template shortcodes.

The asymmetry already shows in the current code. `pelicanconf.py.tmpl`
defines an 8-line `_LazyImages` Markdown extension inline; the Hugo
equivalent lives in a render-hook partial because there is nowhere else
for it to go. Every future Markdown-level behavior — MyST roles, notebook
cell tags, cross-references — follows that same split.

## Verdict

Hugo is genuinely better on three counts: rebuilds are 5.5x faster
(1.6 s against 9.0 s), it needs 232 fewer lines of engine-specific code,
and it is far more widely used, which matters for finding answers and for
long-term viability.

It is not, however, *much cleaner or better*, which was the bar set for
overriding the Python preference. Its template language is measurably
harder to read for the same logic, its author URLs are currently worse
than Pelican's defaults, and it is closed to precisely the two extensions
this blog is most likely to want.

Pelican costs 9-second rebuilds — tolerable for authoring, though it will
grow with the archive — and 311 lines of plugin that Hugo gets for free.
It buys open extension points at the Markdown and reader layer.

The decision is also low-regret. Both engines produce the same site
today, and the 901-line shared theme is engine-neutral, so a later switch
costs the engine-specific layer rather than the design. Choosing one also
lets the other exporter be deleted, the way `zola` already was.

## Appendix: the notebook reader

Added to a `pelicanconf.py`; no other change. Renders a `.ipynb` with its
executed outputs, taking post metadata from a namespaced `blog` key in
the notebook's own metadata (the top-level notebook schema constrains
`authors` to an array, so post headers live under their own key).

```python
from pelican.readers import BaseReader
from pelican import signals


class NotebookReader(BaseReader):
    """Reads a .ipynb straight into Pelican, executed outputs included.
    Front matter is the notebook's own metadata dict."""

    enabled = True
    file_extensions = ["ipynb"]

    def read(self, source_path):
        import nbformat
        from nbconvert import HTMLExporter

        nb = nbformat.read(source_path, as_version=4)
        exporter = HTMLExporter(template_name="basic")   # a body, not a page
        body, _ = exporter.from_notebook_node(nb)
        metadata = {
            key: self.process_metadata(key, value)
            for key, value in nb.metadata.get("blog", {}).items()
        }
        return body, metadata


def add_reader(readers):
    readers.reader_classes["ipynb"] = NotebookReader


class _NotebookPlugin:
    @staticmethod
    def register():
        signals.readers_init.connect(add_reader)


PLUGINS = [_NotebookPlugin]
```
