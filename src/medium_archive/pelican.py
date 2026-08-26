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
`display`) go into pelicanconf.py as TAG_DISPLAY, which the theme reads
through a tag_name filter.

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
pages Hugo renders for aliases, working on any static host.
"""

import json
import re
import sys

from .sites import (ImagePlacer, bake_cover_thumbnails, clean_site,
                    export_content, fill_template, load_site_inputs,
                    page_stems, pick_cover, tag_names, template_text,
                    write_redirects_csv)

# The theme's files: file in the site -> its templates/ source (see
# templates/README.md). The stylesheet is the card look shared with the
# hugo theme.
TEMPLATES = {
    "theme/templates/base.html": "pelican/theme/templates/base.html",
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


def _meta(key: str, value: str) -> str:
    return f"{key}: {' '.join(value.split())}\n"    # headers are one line


def build_site(out):
    manifest, config = load_site_inputs(out)
    stems = page_stems(manifest)
    site = out / "site-pelican"
    clean_site(site, keep=("output",))
    (site / "content").mkdir(parents=True)

    try:
        from PIL import Image                      # noqa: F401
        have_pillow = True
    except ImportError:
        have_pillow = False
        print("pillow not installed: card covers keep full-size images "
              "(`pip install pillow` and re-run for 640x360 thumbnails)",
              file=sys.stderr)
    covers = {url: cover for url, p in manifest.items()
              if (cover := pick_cover(p, out / p["dir"]))}

    def front_matter(url, post):
        text = _meta("Title", post["title"] or url)
        if post.get("date"):
            text += _meta("Date", post["date"][:16].replace("T", " "))
        if post.get("updated"):
            text += _meta("Modified", post["updated"][:16].replace("T", " "))
        if post.get("author"):
            text += _meta("Author", post["author"])
        if post.get("tags"):
            text += _meta("Tags", ", ".join(post["tags"]))
        text += _meta("Slug", stems[url])
        if url in covers:
            text += _meta("Cover", "images/cover.jpg" if have_pillow
                          else covers[url])
        if post.get("description"):
            text += _meta("Summary", post["description"])
        return text + "\n"

    pages = export_content(out, site, manifest, stems, front_matter,
                           escape=attach_images,
                           placer=ImagePlacer(out, config))
    if have_pillow:
        bake_cover_thumbnails(out, site, manifest, stems, covers)

    import shutil
    avatar = config.get("avatar")
    avatar_setting = None
    if avatar and (out / avatar).is_file():
        dst = site / "theme" / "static" / "img" / ("avatar" + (out / avatar).suffix)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / avatar, dst)
        avatar_setting = f"theme/img/{dst.name}"

    # the tab icon, shipped through the theme's static dir like the avatar
    favicon = config.get("favicon")
    favicon_setting = None
    if favicon and (out / favicon).is_file():
        dst = site / "theme" / "static" / ("favicon" + (out / favicon).suffix)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / favicon, dst)
        favicon_setting = f"theme/{dst.name}"

    (site / "pelicanconf.py").write_text(fill_template(
        "pelican/pelicanconf.py.tmpl",
        title=json.dumps(config["title"], ensure_ascii=False),
        description=json.dumps(config.get("description", ""),
                               ensure_ascii=False),
        base_url=json.dumps(config.get("base_url", "").rstrip("/")),
        # json for the string cases; None must render as Python's None
        avatar=json.dumps(avatar_setting) if avatar_setting else "None",
        favicon=json.dumps(favicon_setting) if favicon_setting else "None",
        # a site-wide banner above the header -- an http(s) URL the theme
        # fetches client-side (empty content hides the banner, like Sphinx
        # themes' html announcement option), or literal HTML
        announcement=(json.dumps(config["announcement"], ensure_ascii=False)
                      if config.get("announcement") else "None"),
        tag_display=json.dumps(dict(sorted(tag_names(manifest, out).items())),
                               ensure_ascii=False, indent=4),
    ) + "\n\n" + template_text("pelican/site_plugin.py"), encoding="utf-8")

    for rel, src in TEMPLATES.items():
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template_text(src), encoding="utf-8")
    write_redirects_csv(site, manifest, stems, lambda stem: f"/posts/{stem}/")
    print(f"pelican done: {pages}/{len(manifest)} pages -> {site}",
          file=sys.stderr)
    print(f"render it with: cd {site} && pelican && pagefind --site output"
          "   (or serve with: pelican -l)", file=sys.stderr)
    return site


def cmd_pelican(args):
    build_site(args.out)
