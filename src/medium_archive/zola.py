"""The zola step: build a Zola site in <out>/site-zola/ from the
converted archive. Same reproducibility contract as the myst step (see
sites.py); render with `zola serve` or `zola build` inside
<out>/site-zola/ (https://www.getzola.org).

Each post becomes content/posts/<stem>/index.md with its images beside
it (Zola colocation), so the directory name is the page URL
(/posts/<stem>/). Front matter is TOML: tags and authors feed Zola's
taxonomies -- per-term listing pages and per-term Atom feeds are built
in, as are the site feed (atom.xml) and a full-text search index -- the
exporter's templates wire it to a search box in the page header, so
search works out of the box. Old inbound paths become aliases, so Zola emits
redirect stubs for old links on any static host. The exporter writes a
small self-contained set of Tera templates (from the package's
templates/zola/ files); replace them without touching content/.
"""

import json
import sys

from .sites import (ImagePlacer, clean_site, export_content, fill_template,
                    load_site_inputs, old_paths, page_stems, template_text,
                    write_redirects_csv)

# file in the site -> its templates/ source
TEMPLATES = {
    "templates/base.html": "zola/templates/base.html",
    "templates/index.html": "zola/templates/index.html",
    "templates/page.html": "zola/templates/page.html",
    "templates/section.html": "zola/templates/section.html",
    "templates/taxonomy_list.html": "zola/templates/taxonomy_list.html",
    "templates/taxonomy_single.html": "zola/templates/taxonomy_single.html",
    "static/css/style.css": "zola/static/css/style.css",
}

POSTS_SECTION = """\
+++
title = "Posts"
sort_by = "date"
template = "section.html"
+++
"""


def front_matter(url: str, post: dict, stem: str) -> str:
    """TOML front matter; strings via JSON, whose escapes TOML shares."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    # explicit slug: Zola strips a leading YYYY-MM-DD- from the directory
    # name, which would collide the date-disambiguated duplicate slugs
    lines = ["+++", f"title = {j(post['title'])}", f"slug = {j(stem)}"]
    if post.get("description"):
        lines.append(f"description = {j(post['description'])}")
    if post.get("date"):
        lines.append(f"date = {post['date']}")       # TOML datetime, unquoted
    if post.get("updated"):
        lines.append(f"updated = {post['updated']}")
    lines.append(f"aliases = {j([p for p, _ in old_paths(post, url)])}")
    lines.append("[taxonomies]")
    if post.get("tags"):
        lines.append(f"tags = {j(post['tags'])}")
    if post.get("author"):
        lines.append(f"authors = {j([post['author']])}")
    return "\n".join(lines) + "\n+++\n\n"


def build_site(out):
    manifest, config = load_site_inputs(out)
    stems = page_stems(manifest)
    site = out / "site-zola"
    clean_site(site, keep=("public",))

    (site / "content" / "posts").mkdir(parents=True)
    (site / "content" / "_index.md").write_text(
        "+++\n+++\n\n" + (config.get("intro", "") + "\n"
                          if config.get("intro") else ""), encoding="utf-8")
    (site / "content" / "posts" / "_index.md").write_text(POSTS_SECTION,
                                                          encoding="utf-8")
    pages = export_content(out, site, manifest, stems,
                           lambda url, p: front_matter(url, p, stems[url]),
                           placer=ImagePlacer(out, config))

    (site / "config.toml").write_text(fill_template(
        "zola/config.toml.tmpl",
        base_url=json.dumps(config.get("base_url", "https://example.org")
                            .rstrip("/")),
        title=json.dumps(config["title"], ensure_ascii=False),
        description=json.dumps(config.get("description", ""),
                               ensure_ascii=False),
    ), encoding="utf-8")
    for rel, src in TEMPLATES.items():
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template_text(src), encoding="utf-8")
    write_redirects_csv(site, manifest, stems, lambda stem: f"/posts/{stem}/")
    print(f"zola done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    print(f"render it with: cd {site} && zola serve   (or: zola build)",
          file=sys.stderr)
    return site


def cmd_zola(args):
    build_site(args.out)
