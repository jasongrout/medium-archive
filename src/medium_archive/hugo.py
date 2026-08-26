"""The hugo step: build a Hugo site in <out>/site-hugo/ from the
converted archive. Same reproducibility contract as the myst step (see
sites.py); render with `hugo` or `hugo server` inside <out>/site-hugo/
(https://gohugo.io).

Each post becomes a Hugo leaf bundle, content/posts/<stem>/index.md with
its images beside it, so the bundle directory name is the page URL
(/posts/<stem>/). Front matter is JSON (Hugo reads it natively): tags and
authors feed Hugo's taxonomies, which give the tag/author listing pages
and per-term RSS feeds, and every old inbound path (Medium slug+id,
/p/<id>, Ghost-era) becomes an alias, so Hugo emits redirect stubs for
old links on any static host.

Tags stay slugs in front matter, so each term and its /tags/<tag>/ URL
are exactly the archive's tag; the name a tag is shown under (tags.json's
`display`) arrives instead as a term page, content/tags/<tag>/_index.md
with that title, which is how every place Hugo renders a term -- cards,
the tag page and its <title>, the chip index, the per-tag feed -- picks
it up at once, under a real theme as much as the built-in one.

Hugo has no default theme. By default the exporter writes a small
self-contained one (layouts/ + css, from the package's templates/hugo/
and templates/shared/ files) with light and dark palettes and a
light/dark/system picker in the header (the choice persists per
browser; with none stored, the system scheme decides) and
click-to-zoom body images (post pages open an image whose original
holds more detail than the column shows full size in a modal, like
Medium's); search is then
the one feature Hugo does not generate (run `pagefind --site public`
after `hugo` for a static search UI). Or name a real theme in site.json --

    "hugo": {"theme": "dream",
             "theme_repo": "https://github.com/g1eny0ung/hugo-theme-dream",
             "params": {...}}                       # optional overrides

-- and the exporter emits that theme's config instead of its own
layouts; clone the theme into <out>/site-hugo/themes/<name> once
(regeneration preserves themes/). The Dream theme
(https://hugo-theme-dream.g1en.site) gets first-class treatment: each
post's first image becomes its summary-card cover, the /posts archives
page and /search page (Dream's built-in title+description search) are
created, the RSS nav item is enabled, an Authors nav item points at the
author taxonomy, and siteStartYear is derived from the oldest post.
"""

import json
import shutil
import sys

from .sites import (ImagePlacer, bake_cover_thumbnails,  # noqa: F401
                    clean_site, export_content, fill_template, image_size,
                    load_site_inputs, old_paths, page_stems, pick_cover,
                    tag_names, template_text, write_redirects_csv)

# The built-in theme, written when site.json names no real theme: file
# in the site -> its templates/ source (see templates/README.md for the
# rationale behind the individual files). The regular list and taxonomy
# pages share one layout; the stylesheet is the card look shared with
# the pelican theme.
TEMPLATES = {
    "layouts/_default/baseof.html": "hugo/layouts/_default/baseof.html",
    "layouts/partials/card.html": "hugo/layouts/partials/card.html",
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
    "static/css/style.css": "shared/card.css",
}


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
        front["author"] = post["author"]         # per-post byline (Dream)
        if post.get("author_url"):
            front["authorlink"] = post["author_url"]
    if cover:               # bundle resource: Dream's card and og:image
        front["cover"] = cover
        front["images"] = [cover]
    front["aliases"] = [path for path, _ in old_paths(post, url)]
    return json.dumps(front, indent=2, ensure_ascii=False) + "\n\n"


def _toml_params(params: dict) -> str:
    """[params] as TOML: flat keys first, dict values as sub-tables whose
    dict entries render as inline tables (Dream's navItems form). Values
    go through JSON, whose scalar/list syntax TOML shares."""
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


def dream_params(manifest: dict, config: dict) -> dict:
    """Dream's conventions, derived from the archive: RSS in the nav, an
    Authors item for the author taxonomy, the site's first year."""
    years = [p["date"][:4] for p in manifest.values() if p.get("date")]
    params = {"headerTitle": config["title"], "author": config["title"],
              "rss": True}
    if years:
        params["siteStartYear"] = int(min(years))
    params["navItems"] = {
        "authors": {"href": "/authors", "icon": "people", "title": "Authors"}}
    return params


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
    theme = hugo_config.get("theme")
    dream = theme == "dream"
    site = out / "site-hugo"
    clean_site(site, keep=("public", "resources", "themes"))

    (site / "content").mkdir(parents=True)
    (site / "content" / "_index.md").write_text(
        json.dumps({"title": config["title"]}) + "\n\n"
        + (config.get("intro", "") + "\n" if config.get("intro") else ""),
        encoding="utf-8")
    if dream:
        # Dream renders /posts as an archives timeline and turns an empty
        # search section into its built-in title+description search page
        (site / "content" / "posts").mkdir()
        (site / "content" / "posts" / "_index.md").write_text(
            json.dumps({"title": "Archives"}) + "\n", encoding="utf-8")
        (site / "content" / "search").mkdir()
        (site / "content" / "search" / "_index.md").write_text("{}\n",
                                                               encoding="utf-8")
    elif not theme:
        # the built-in theme's Pagefind search page and year-grouped
        # archives timeline
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
        placer=ImagePlacer(out, config))
    if have_pillow:
        bake_cover_thumbnails(out, site, manifest, stems, covers)
    write_tag_terms(site, tag_names(manifest, out))

    params = {"description": config.get("description", "")}
    if dream:
        params.update(dream_params(manifest, config))
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
        theme=f"theme = {json.dumps(theme)}\n" if theme else "",
        params=_toml_params(params),
    ), encoding="utf-8")
    if not theme:               # the theme provides layouts and styling
        for rel, src in TEMPLATES.items():
            path = site / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template_text(src), encoding="utf-8")
    # the feed override is written even under a real theme: feed policy
    # is content policy, not styling (see templates/README.md)
    rss = site / "layouts" / "_default" / "rss.xml"
    rss.parent.mkdir(parents=True, exist_ok=True)
    rss.write_text(template_text("hugo/layouts/_default/rss.xml"),
                   encoding="utf-8")
    write_redirects_csv(site, manifest, stems, lambda stem: f"/posts/{stem}/")
    print(f"hugo done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    if theme and not (site / "themes" / theme).is_dir():
        repo = hugo_config.get("theme_repo", "<theme repository>")
        print(f"theme missing (kept across regenerations): "
              f"git clone {repo} {site / 'themes' / theme}", file=sys.stderr)
    print(f"render it with: cd {site} && hugo server   (or: hugo; then "
          "`pagefind --site public` for search)", file=sys.stderr)
    return site


def cmd_hugo(args):
    build_site(args.out)
