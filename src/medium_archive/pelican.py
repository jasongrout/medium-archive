"""The pelican step: build a Pelican site in <out>/site-pelican/ from
the converted archive. Same reproducibility contract as the myst step
(see sites.py); render with `pelican -l` (serve) or `pelican` (build)
inside <out>/site-pelican/ (https://getpelican.com, `pip install
pelican markdown`).

Each post becomes content/posts/<stem>/index.md with its images beside
it; image references are rewritten to Pelican's `{attach}` form so the
files publish next to the article at /posts/<stem>/. Body images load
lazily (a small Markdown extension embedded in the generated config)
and are served responsively: after each build the embedded plugin
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
                    canonical_for, caption_text, clean_site,
                    copy_site_asset, export_content, fill_template,
                    image_size, load_site_inputs, page_stems,
                    rewrite_figures, site_profiles, tag_names,
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

# What marks an <img> as a post's own body image, for the site plugin's
# post-build pass; it strips the attribute again as it rewrites. Most
# images reach the page through the Markdown tree, where the generated
# config's _BodyImages extension sets this. A captioned one does not:
# the figure shell below writes the tag itself, as literal HTML the
# tree never sees, so it has to set the same mark here. Both are the
# article's own content, which is the whole point -- an <img> the theme
# renders (a listing or related-post card) is neither, and so is never
# marked. Keep in step with BODY_IMAGE_ATTR in
# templates/pelican/site_plugin.py; a test holds the two together.
BODY_IMAGE_ATTR = "data-body-image"


def attach_images(line: str) -> str:
    """Colocated image references become {attach} links, so Pelican
    copies each file next to its article and rewrites the URL."""
    return IMAGE_RE.sub(r"]({attach}\1)", line)


FIGURE_TAG_RE = re.compile(r"^<(figure|figcaption)>$", re.M)


def figure_blocks(markdown: str) -> str:
    """Convert's figure shells in the form python-markdown renders the
    way Medium served them: one HTML block, the img a literal tag
    (marked as a body image, since the tag is written here rather than
    rendered from the Markdown tree the config's extension marks; the
    site plugin's post-build pass reads that mark to give the img its
    srcset and dimensions, and strips it), the caption opted in to
    inline processing -- both
    markdown="span", which python-markdown's md_in_html (part of the
    `extra` extension the generated config enables) needs to render the
    caption's Markdown at all, and which keeps img and caption out of
    <p> wrappers. A shell around anything but a single image (the link
    an embed became) keeps its blank-line-separated lines instead,
    opted in with markdown="1" so the Markdown between them renders.
    The image reference already carries the {attach} prefix: escape
    runs first."""
    def block(alt, src, link, caption):
        esc = lambda v: (v.replace("&", "&amp;").replace('"', "&quot;")
                         .replace("<", "&lt;"))
        alt = alt or caption_text(caption)    # the caption describes it
        img = (f'<img alt="{esc(alt)}" src="{src}" loading="lazy"'
               f' {BODY_IMAGE_ATTR}="">')
        if link:
            img = f'<a href="{esc(link)}">{img}</a>'
        return ('<figure markdown="span">\n'
                f"{img}\n"
                f'<figcaption markdown="span">{caption}</figcaption>\n'
                "</figure>")
    markdown = rewrite_figures(markdown, block)
    return FIGURE_TAG_RE.sub(r'<\1 markdown="1">', markdown)


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
            # Pelican splits the list on semicolons when it has any,
            # else on commas: pick the separator no name contains
            names = [a["name"] for a in post["authors"]]
            sep = "; " if any("," in n for n in names) else ", "
            text += _meta("Authors", sep.join(names))
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
                           transform=figure_blocks, covers=covers)

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
