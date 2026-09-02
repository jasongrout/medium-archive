"""The hugo step: build a Hugo site in <out>/site-hugo/ from the
converted archive. Same reproducibility contract as the myst step (see
sites.py); render with `hugo` or `hugo server` inside <out>/site-hugo/
(https://gohugo.io).

Each post becomes a Hugo leaf bundle, content/posts/<stem>/index.md with
its images beside it, so the bundle directory name is the page URL
(/posts/<stem>/). The <figure>/<figcaption> shells convert writes
around captioned images become calls to a figure shortcode the
exporter ships with every site (see figure_shortcodes), so the
rendered page carries the same markup Medium served -- a <figure>
holding the img (with the responsive srcset ladder body images get)
and its <figcaption>, no paragraph wrappers, caption styled by CSS --
and the caption stays programmatically associated with its picture. Front matter is JSON (Hugo reads it natively): tags and
authors feed Hugo's taxonomies, which give the tag/author listing pages
and per-term RSS feeds, and every old inbound path (Medium slug+id,
/p/<id>, Ghost-era) becomes an alias, so Hugo emits redirect stubs for
old links on any static host.

Tags stay slugs in front matter, so each term and its /tags/<tag>/ URL
are exactly the archive's tag; the name a tag is shown under (tags.json's
`display`) arrives instead as a term page, content/tags/<tag>/_index.md
with that title, which is how every place Hugo renders a term -- cards,
the tag page and its <title>, the chip index, the per-tag feed -- picks
it up at once.

Hugo has no default theme. The exporter writes a small self-contained
one (layouts/ + css, from the package's templates/hugo/ and
templates/shared/ files) with light and dark palettes and a
light/dark/system picker in the header (the choice persists per
browser; with none stored, the system scheme decides) and
click-to-zoom body images (post pages open an image whose original
holds more detail than the column shows full size in a modal, like
Medium's); search is then
the one feature Hugo does not generate (run `pagefind --site public`
after `hugo` for a static search UI). site.json's optional `hugo`
section tunes the generated config: `locale`, `avatar` and `favicon`
(overriding the top-level keys), and `params` merged last into
[params].
"""

import json
import re
import shutil
import sys

from .sites import (ImagePlacer, bake_cover_thumbnails,  # noqa: F401
                    clean_site, export_content, fill_template, image_size,
                    load_site_inputs, old_paths, page_stems, pick_cover,
                    tag_names, template_text, write_redirects_csv)

# The built-in theme: file in the site -> its templates/ source (see
# templates/README.md for the rationale behind the individual files).
# The regular list and taxonomy pages share one layout; the stylesheet
# is the card look shared with the pelican theme. The feed override and
# the figure shortcode (with the image partial it and the render hook
# share) are content policy rather than styling: the pages' figure
# calls resolve to that shortcode, which takes the caption as inner
# content.
TEMPLATES = {
    "layouts/_default/baseof.html": "hugo/layouts/_default/baseof.html",
    "layouts/partials/card.html": "hugo/layouts/partials/card.html",
    "layouts/partials/share.html": "hugo/layouts/partials/share.html",
    "layouts/index.html": "hugo/layouts/index.html",
    "layouts/_default/single.html": "hugo/layouts/_default/single.html",
    "layouts/_default/list.html": "hugo/layouts/_default/list.html",
    "layouts/_default/taxonomy.html": "hugo/layouts/_default/list.html",
    "layouts/_default/terms.html": "hugo/layouts/_default/terms.html",
    "layouts/_default/archives.html": "hugo/layouts/_default/archives.html",
    "layouts/_default/search.html": "hugo/layouts/_default/search.html",
    "layouts/alias.html": "hugo/layouts/alias.html",
    "layouts/_default/_markup/render-image.html":
        "hugo/layouts/_default/_markup/render-image.html",
    "layouts/_default/rss.xml": "hugo/layouts/_default/rss.xml",
    "layouts/shortcodes/figure.html": "hugo/layouts/shortcodes/figure.html",
    "layouts/partials/post-image.html":
        "hugo/layouts/partials/post-image.html",
    "static/css/style.css": "shared/card.css",
}


# The <figure> shell convert writes around a captioned image
# (link-wrapped or not), in the exact shape _Converter emits it: tag
# lines and the single image and caption lines between them, all
# blank-line separated.
FIGURE_BLOCK_RE = re.compile(
    r"<figure>\n\n(\[)?!\[([^\]\n]*)\]\(([^)\s]+)\)(?(1)\]\(([^)\s]+)\))\n\n"
    r"<figcaption>\n\n([^\n]+)\n\n</figcaption>\n\n</figure>")


def figure_shortcodes(markdown: str) -> str:
    """Convert's figure shells as calls to the exported figure
    shortcode, the caption as inner content -- an attribute could not
    carry its Markdown (links, emphasis). Rendering via the shortcode
    rather than the raw shell keeps the img and the caption out of
    Goldmark's <p> wrappers and gives the img the render hook's srcset
    ladder, which raw HTML would bypass. A shell around anything else
    (the link an embed became, an inlined gist) stays raw HTML, which
    Goldmark renders as-is: the unsafe renderer stays on in the
    generated config for it, and for the old bodies that carry HTML
    fragments of their own."""
    def call(m):
        _, alt, src, link, caption = m.groups()
        q = lambda v: v.replace(chr(92), "").replace(chr(34), chr(92) + chr(34))
        args = f'src="{src}"'
        if alt:
            args += f' alt="{q(alt)}"'
        if link:
            args += f' link="{q(link)}"'
        return "{{< figure %s >}}%s{{< /figure >}}" % (args, caption)
    return FIGURE_BLOCK_RE.sub(call, markdown)


def front_matter(url: str, post: dict, cover: str | None = None) -> str:
    front = {"title": post["title"]}
    if post.get("date"):
        front["date"] = post["date"]
    if post.get("updated"):
        front["lastmod"] = post["updated"]
    if post.get("description"):
        front["description"] = post["description"]
    if post.get("tags"):
        front["tags"] = post["tags"]
    if post.get("author"):
        front["authors"] = [post["author"]]      # the author taxonomy
        front["author"] = post["author"]         # card byline, feed creator
    if cover:               # bundle resource: the card cover and og:image
        front["cover"] = cover
    front["aliases"] = [path for path, _ in old_paths(post, url)]
    return json.dumps(front, indent=2, ensure_ascii=False) + "\n\n"


def _toml_params(params: dict) -> str:
    """[params] as TOML: flat keys first, dict values as sub-tables whose
    dict entries render as inline tables. Values go through JSON, whose
    scalar/list syntax TOML shares."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    flat, tables = [], []
    for key, value in params.items():
        if isinstance(value, dict):
            rows = [f"[params.{key}]"]
            for name, item in value.items():
                if isinstance(item, dict):
                    inner = ", ".join(f"{k} = {j(v)}" for k, v in item.items())
                    rows.append(f"{name} = {{ {inner} }}")
                else:
                    rows.append(f"{name} = {j(item)}")
            tables.append("\n".join(rows))
        else:
            flat.append(f"{key} = {j(value)}")
    return "\n\n".join(["[params]\n" + "\n".join(flat)] + tables)


def write_tag_terms(site, names: dict):
    """A branch bundle per tag, content/tags/<tag>/_index.md, carrying
    the name the tag is shown under. Front matter keeps the slug, so the
    term and its /tags/<tag>/ URL are unchanged and it is only the title
    Hugo renders that gains its spaces and capitals -- which means every
    place a term's title reaches (cards, the tag page heading and
    <title>, the chip index, per-tag RSS) is covered at once, in a real
    theme as much as in the built-in one."""
    for tag, name in sorted(names.items()):
        term = site / "content" / "tags" / tag
        term.mkdir(parents=True, exist_ok=True)
        (term / "_index.md").write_text(
            json.dumps({"title": name}, ensure_ascii=False) + "\n",
            encoding="utf-8")


def build_site(out):
    manifest, config = load_site_inputs(out)
    stems = page_stems(manifest)
    hugo_config = config.get("hugo", {})
    site = out / "site-hugo"
    clean_site(site, keep=("public", "resources"))

    (site / "content").mkdir(parents=True)
    (site / "content" / "_index.md").write_text(
        json.dumps({"title": config["title"]}) + "\n\n"
        + (config.get("intro", "") + "\n" if config.get("intro") else ""),
        encoding="utf-8")
    # the theme's Pagefind search page and year-grouped archives timeline
    (site / "content" / "search.md").write_text(
        json.dumps({"title": "Search", "layout": "search",
                    "url": "/search/"}) + "\n", encoding="utf-8")
    (site / "content" / "archives.md").write_text(
        json.dumps({"title": "Archives", "layout": "archives",
                    "url": "/archives/"}) + "\n", encoding="utf-8")
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
    pages = export_content(
        out, site, manifest, stems,
        lambda url, p: front_matter(url, p,
                                    cover=("images/cover.jpg" if have_pillow
                                           else covers.get(url))
                                    if url in covers else None),
        placer=ImagePlacer(out, config), transform=figure_shortcodes)
    if have_pillow:
        bake_cover_thumbnails(out, site, manifest, stems, covers)
    write_tag_terms(site, tag_names(manifest, out))

    params = {"description": config.get("description", "")}
    # "avatar" (site.json top level, or hugo section): archive-relative
    # path of a hand-picked site logo, shown in the header; copied into
    # the site so the site stays self-contained
    avatar = hugo_config.get("avatar") or config.get("avatar")
    if avatar:
        src = out / avatar
        if src.is_file():
            dst = site / "static" / "img" / ("avatar" + src.suffix)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            params["avatar"] = f"img/{dst.name}"
        else:
            print(f"avatar not found, skipped: {src}", file=sys.stderr)
    # "favicon" (site.json top level, or hugo section): archive-relative
    # path of the tab icon; copied to the site root so browsers that ask
    # for /favicon.ico by convention are covered when it is an .ico
    favicon = hugo_config.get("favicon") or config.get("favicon")
    if favicon:
        src = out / favicon
        if src.is_file():
            dst = site / "static" / ("favicon" + src.suffix)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            params["favicon"] = dst.name
        else:
            print(f"favicon not found, skipped: {src}", file=sys.stderr)
    # "announcement": a site-wide banner above the header -- an http(s)
    # URL the theme fetches client-side (empty content hides the banner,
    # like Sphinx themes' html announcement option), or literal HTML
    if config.get("announcement"):
        params["announcement"] = config["announcement"]
    params.update(hugo_config.get("params", {}))
    (site / "hugo.toml").write_text(fill_template(
        "hugo/hugo.toml.tmpl",
        base_url=json.dumps(config.get("base_url", "https://example.org/")),
        title=json.dumps(config["title"], ensure_ascii=False),
        locale=json.dumps(hugo_config.get("locale", "en")),
        params=_toml_params(params),
    ), encoding="utf-8")
    for rel, src in TEMPLATES.items():
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template_text(src), encoding="utf-8")
    write_redirects_csv(site, manifest, stems, lambda stem: f"/posts/{stem}/")
    print(f"hugo done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    print(f"render it with: cd {site} && hugo server   (or: hugo; then "
          "`pagefind --site public` for search)", file=sys.stderr)
    return site


def cmd_hugo(args):
    build_site(args.out)
