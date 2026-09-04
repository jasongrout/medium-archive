"""The pelican step: build a Pelican site in <out>/site-pelican/ from
the converted archive. Same reproducibility contract as the myst step
(see sites.py); render with `pelican -l` (serve) or `pelican` (build)
inside <out>/site-pelican/ (https://getpelican.com, `pip install
pelican markdown-it-py mdit-py-plugins`).

The site reads CommonMark rather than the python-markdown dialect
Pelican reads by default: the generated config carries a reader built
on markdown-it-py, which replaces Pelican's own (see the config
template). That is where everything this site needs from the Markdown
layer hangs -- heading ids, Pygments on the class the shared theme
styles, Pelican's {attach} placeholders, the body-image marking, and
the figure directive below.

Each post becomes content/posts/<stem>/index.md with its images beside
it; image references are rewritten to Pelican's `{attach}` form so the
files publish next to the article at /posts/<stem>/. Body images load
lazily (the reader marks every image in an article's body) and are
served responsively: after each build the embedded plugin
encodes webp variants of every still body image at the same widths as
the hugo theme's render hook (480/736/1104, never upscaled,
mtime-cached) and rewrites the article's img tags with srcset/sizes
and real width/height. Metadata uses Pelican's `Key: value` header format; tags and
authors are first-class in Pelican, so tag/author listing pages and
Atom feeds (site-wide and per tag/author) come out of the box. Tags
reach Pelican as slugs, so tag.slug and every /tags/<slug>/ URL are
exactly the archive's tag rather than whatever Pelican's slugify would
make of a name like "C++"; the names tags are shown under (tags.json's
`display`) go into pelicanconf.py as TAG_DISPLAY, from which the site
plugin names the Tag objects once the tags are collected -- Pelican
renders a tag from the object everywhere, the per-tag feed title
included, and that one it builds in Python out of reach of a template.
Authors take the same route, and need it more: a byline is a person's
name, so left as the term it would reach each generator raw -- hugo
keeping its accents and punctuation in the path, Pelican folding them
away -- and one author would sit at two addresses. Both exporters write
sites.author_slug's slug instead, AUTHOR_DISPLAY carries the names, and
the site plugin puts them on the Author objects the same way.

The exporter writes its own theme, from the package's templates/pelican/
and templates/shared/ files -- the card-grid blog shared with
the hugo step, light and dark palettes and the header's
light/dark/system picker included: paginated home of cover-image
cards, article pages (with click-to-zoom body images: an image whose
original holds more detail than the column shows opens full size in a
modal, like Medium's), tag/author card listings, chip indexes
(sortable by name or by post count), an
archives timeline, and a /search/ page wired to Pagefind
(run `pagefind --site output` after `pelican` for full-text search with
highlighted, in-context excerpts). Card covers are 640x360 thumbnails
generated at export time when Pillow is installed (`pip install
pillow`), center-cropped or letterboxed by aspect ratio (see
sites.make_cover_thumbnail); without it, cards use the full-size image.

Pelican has no built-in equivalent of Hugo's aliases, so the
generated config embeds a small plugin (templates/pelican/site_plugin.py,
appended verbatim): after each build it reads the
exported redirects.csv and writes a meta-refresh redirect stub at every
old inbound path (Medium slug+id, /p/<id>, Ghost-era) -- the same stub
pages Hugo renders for aliases, working on any static host -- plus the
same map as a `_redirects` file for hosts that turn one into HTTP 301s.
The plugin also writes what Pelican has no built-in for and Hugo emits
on its own: a sitemap.xml of the site's pages (post lastmod from the
updated date) and a robots.txt naming it, and the related posts each
post page closes with (by shared tags, then author, then date); the
theme's pages carry the metadata search engines and share targets read
(see templates/README.md): the structured data's author and publisher
profiles come from AUTHOR_LINKS (the Medium profile of every byline)
and site.json's "profiles"/"twitter", the og:image of a page with no
cover from its "share_image", and a post that declared a canonical on
another host (Medium's "originally published at") carries it as a
Canonical: header; the Medium copy is never a page's canonical.
"""

import json
import re
import sys

from .sites import (COVER_SIZE, Covers, ImagePlacer, author_links,
                    author_names, author_slug,
                    canonical_for, caption_text, clean_site,
                    copy_site_asset, export_content, fill_template,
                    image_size, load_site_inputs, page_stems,
                    quote_arg, rewrite_figures, site_profiles, tag_names,
                    template_text, write_redirects_csv, write_templates)

# The theme's files: file in the site -> its templates/ source (see
# templates/README.md). The stylesheet is the card look shared with the
# hugo theme.
TEMPLATES = {
    "theme/templates/base.html": "pelican/theme/templates/base.html",
    "theme/templates/jsonld.html": "pelican/theme/templates/jsonld.html",
    "theme/templates/macros.html": "pelican/theme/templates/macros.html",
    "theme/templates/pagination.html":
        "pelican/theme/templates/pagination.html",
    "theme/templates/index.html": "pelican/theme/templates/index.html",
    "theme/templates/article.html": "pelican/theme/templates/article.html",
    "theme/templates/tag.html": "pelican/theme/templates/tag.html",
    "theme/templates/author.html": "pelican/theme/templates/author.html",
    "theme/templates/tags.html": "pelican/theme/templates/tags.html",
    "theme/templates/authors.html": "pelican/theme/templates/authors.html",
    "theme/templates/archives.html": "pelican/theme/templates/archives.html",
    "theme/templates/search.html": "pelican/theme/templates/search.html",
    "theme/static/css/style.css": "shared/card.css",
}

IMAGE_RE = re.compile(r"\]\((images/[^)\s]+)\)")


def attach_images(line: str) -> str:
    """Colocated image references become {attach} links, so Pelican
    copies each file next to its article and rewrites the URL."""
    return IMAGE_RE.sub(r"]({attach}\1)", line)


def figure_directives(markdown: str) -> str:
    """Convert's figure shells as calls to the figure directive the
    generated config's reader renders, the caption as the directive's
    body -- the counterpart of the hugo exporter's figure shortcode,
    and for the same reasons. An attribute could not carry the
    caption's Markdown (links, emphasis), and rendering the shell as
    raw HTML instead, as this exporter did while pelican rendered with
    python-markdown, needs that library's md_in_html extension to
    render the caption at all: CommonMark says the contents of an HTML
    block are raw. Rendering through the directive also keeps the img
    and the caption out of <p> wrappers, marks the img as a body image
    for the site plugin's post-build pass, and renders the caption with
    the site's own parser, so it picks up whatever extensions the
    config enables.

    A shell around anything else (the link an embed became, an inlined
    gist) stays raw HTML, which the reader passes through: its lines
    are blank-line separated, which ends the HTML block and leaves the
    Markdown between them to be parsed as Markdown.

    The image reference already carries the {attach} prefix: escape
    runs first. It is left exactly as it is here -- the reader writes
    it into an attribute, which no parser touches, so pelican's
    intra-site link pass resolves it on the rendered page."""
    def directive(alt, src, link, caption):
        args = f'src="{src}"'
        # plain text, like the hugo exporter's: an alt is prose for a
        # screen reader, and the two sites should read it out the same
        alt = caption_text(alt or caption)    # the caption describes it
        if alt:
            args += f' alt="{quote_arg(alt)}"'
        if link:
            args += f' link="{quote_arg(link)}"'
        return f"::: figure {args}\n{caption}\n:::"
    return rewrite_figures(markdown, directive)


def _meta(key: str, value: str) -> str:
    return f"{key}: {' '.join(value.split())}\n"    # headers are one line


def build_site(out):
    manifest, config = load_site_inputs(out)
    stems = page_stems(manifest)
    site = out / "site-pelican"
    clean_site(site, keep=("output",))
    (site / "content").mkdir(parents=True)
    covers = Covers(out, manifest)

    def front_matter(url, post):
        text = _meta("Title", post["title"] or url)
        if post.get("date"):
            text += _meta("Date", post["date"][:16].replace("T", " "))
        if post.get("updated"):
            text += _meta("Modified", post["updated"][:16].replace("T", " "))
        if post.get("authors"):
            # slugs, as the tags are, so author.slug and every
            # /authors/<slug>/ URL are exactly what the hugo site
            # serves rather than whatever each engine would make of a
            # byline (see sites.author_slug); the site plugin names the
            # Author objects from AUTHOR_DISPLAY once they are collected.
            # A slug holds no comma, so Pelican's comma split is
            # unambiguous and the semicolon form it also accepts, which
            # a name like "Project Jupyter, Inc." used to need, is not.
            text += _meta("Authors", ", ".join(
                author_slug(a["name"]) for a in post["authors"]))
        if post.get("tags"):
            text += _meta("Tags", ", ".join(post["tags"]))
        text += _meta("Slug", stems[url])
        if covers.path(url):
            text += _meta("Cover", covers.path(url))
        if post.get("description"):
            text += _meta("Summary", post["description"])
        if canonical_for(post):       # a copy of that page, and says so
            text += _meta("Canonical", canonical_for(post))
        return text + "\n"

    pages = export_content(out, site, manifest, stems, front_matter,
                           escape=attach_images,
                           placer=ImagePlacer(out, config),
                           transform=figure_directives, covers=covers)

    # the header logo and the tab icon, shipped through the theme's
    # static dir
    avatar = copy_site_asset(out, config.get("avatar"),
                             site / "theme" / "static" / "img", "avatar")
    favicon = copy_site_asset(out, config.get("favicon"),
                              site / "theme" / "static", "favicon")
    # the og:image of every page without a cover of its own, with its
    # dimensions read here (the theme has no image pipeline)
    share = copy_site_asset(out, config.get("share_image"),
                            site / "theme" / "static" / "img", "share")
    share_size = (image_size(site / "theme" / "static" / "img" / share)
                  if share else None)
    setting = lambda v: json.dumps(v) if v else "None"   # Python literals
    (site / "pelicanconf.py").write_text(fill_template(
        "pelican/pelicanconf.py.tmpl",
        title=json.dumps(config["title"], ensure_ascii=False),
        description=json.dumps(config.get("description", ""),
                               ensure_ascii=False),
        base_url=json.dumps(config.get("base_url", "").rstrip("/")),
        avatar=setting(avatar and f"theme/img/{avatar}"),
        favicon=setting(favicon and f"theme/{favicon}"),
        # a site-wide banner above the header -- an http(s) URL the theme
        # fetches client-side (empty content hides the banner, like Sphinx
        # themes' html announcement option), or literal HTML
        announcement=(json.dumps(config["announcement"], ensure_ascii=False)
                      if config.get("announcement") else "None"),
        # the landing-page blurb, Markdown; the config renders it
        intro=setting(config.get("intro")),
        noindex="True" if config.get("noindex") else "False",
        twitter=setting(config.get("twitter")),
        profiles=json.dumps(site_profiles(config)),
        share_image=setting(share and f"theme/img/{share}"),
        share_image_size=setting(share_size and list(share_size)),
        cover_size=setting(list(COVER_SIZE) if covers.pillow else None),
        author_links=json.dumps(author_links(manifest), ensure_ascii=False,
                                indent=4),
        author_display=json.dumps(author_names(manifest), ensure_ascii=False,
                                  indent=4),
        tag_display=json.dumps(dict(sorted(tag_names(manifest, out).items())),
                               ensure_ascii=False, indent=4),
    ) + "\n\n" + template_text("pelican/site_plugin.py"), encoding="utf-8")

    write_templates(site, TEMPLATES)
    write_redirects_csv(site, manifest, stems, lambda stem: f"/posts/{stem}/")
    print(f"pelican done: {pages}/{len(manifest)} pages -> {site}",
          file=sys.stderr)
    print(f"render it with: cd {site} && pelican && pagefind --site output"
          "   (or serve with: pelican -l)", file=sys.stderr)
    return site


def cmd_pelican(args):
    build_site(args.out)
