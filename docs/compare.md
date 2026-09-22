# Hugo vs Pelican for this archive

**Recommendation: Pelican**, for extensibility. The two sites are
nearly identical in output; Hugo rebuilds faster and needs less
engine-specific code, but Pelican offers in-process extension points
(readers, signals) in Python. MyST is out of scope (see `todo.md`,
section 0).

## Method

```sh
medium-archive convert --clean   # 336 posts, lint: 0 problems
medium-archive hugo              # base_url http://localhost:1313
medium-archive pelican           # base_url http://localhost:1314
cd site-hugo    && hugo    && pagefind --site public
cd site-pelican && pelican && pagefind --site output
```

Versions: hugo 0.158.0 extended, pelican 4.12.0, python 3.11.15,
markdown 3.10.3, pillow 12.3.0, pagefind 1.5.2, gifsicle 1.94. Both
sites were served and inspected in headless Chromium.

Measured before posts moved to `/posts/<year>/<slug>/` and before
Pelican switched to a CommonMark reader (`commonmark.md`). The URL
change applies equally to both sites.

## Output

| | Hugo | Pelican |
|---|---|---|
| Post URLs | 336 | 336 (identical sets) |
| Total addresses | 1377 | 1211 |
| Pagefind index | 336 pages / 15905 words | 336 pages / 15868 words |
| `sitemap.xml` entries | 505 | 505 |
| Output size | 558 MB | 557 MB |

Hugo's extra 166 addresses are `page/1/` redirect stubs. Rendered in
light and dark at 1280×900, no probed metric differed (card, chip,
share-link, related-post and JSON-LD counts; backgrounds; figures,
highlighted code and `srcset` on a code- and image-heavy post).

Differences found:

- **Related posts**: same three on 148 of 336 posts (mean overlap 2.13
  of 3); the two rank ties differently.
- **Markdown**, 27 posts, all from python-markdown not following
  CommonMark: Hugo showed stray `**` on 15 posts; Pelican dropped bare
  `<angle-bracket>` words on 2; Hugo applied typographic quotes and
  ellipses. The CommonMark reader and the `convert` emphasis fix have
  since resolved these (`commonmark.md`).
- **Dates**: "September 2, 2026" vs "September 02, 2026".

## Build time

| | Hugo | Pelican |
|---|---|---|
| Exporter step | 11.0 s | 11.0 s |
| Cold build | 18.0 s | 20.4 s |
| Rebuild, caches warm | 1.1 s | 5.5 s |

Cold builds are dominated by image encoding in both. Pelican has no
page-level cache and re-renders every page.

## Code

| lines | Hugo | Pelican |
|---|---|---|
| Exporter (Python) | 331 | 262 |
| Templates | 460 (Go, 20 files) | 384 (Jinja, 12 files) |
| Generated config | 56 (TOML) | 149 (Python) |
| Site plugin | -- | 370 (Python) |
| Total | 847 | 1165 |

A further 901 lines (`card.css`, `shared/`) are shared. The Pelican
plugin reimplements what Hugo has built in: redirect stubs, sitemap,
`robots.txt`, responsive images, first-image priority, related posts,
term display names. Go templates are harder to read for the same logic
and lack string processing (the feed template needs chained
`replaceRE` calls).

## Extensibility

Pelican's config is executed Python and can register readers and signal
handlers. A `.ipynb` reader was prototyped in 26 lines and fed Pelican's
tag, author and date handling from notebook metadata; MyST could be
added the same way through myst-parser.

Hugo has no in-process extension mechanism (`exec` is not a template
function). Notebooks would need an external pre-build conversion, and
MyST directives would need reimplementing as shortcodes.

## Verdict

Hugo is faster to rebuild (5×), smaller in engine-specific code, and
more widely used. Pelican is preferred because it can be extended at
the reader and Markdown layer in Python, which the likely future
features (notebook posts, MyST) need. The shared theme is
engine-neutral, so switching later costs only the engine-specific
layer.
