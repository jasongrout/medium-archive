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
and the caption stays programmatically associated with its picture.
Front matter is YAML between `---` fences (see
sites.front_matter_yaml) -- the form Hugo's own documentation and
themes are written in, and the one the pelican site writes, so a field
is read and hand-edited the same way in either site. Tags and authors
feed Hugo's taxonomies, which give the tag/author listing pages and
per-term RSS feeds, and every old inbound path (Medium slug+id,
/p/<id>, Ghost-era) becomes an alias, so Hugo emits redirect stubs for
old links on any static host; the same map is written as a `_redirects`
file for hosts that turn one into HTTP 301s. Hugo's own sitemap.xml
(page lastmod from the post's updated date) is joined by a robots.txt
naming it, and the theme's pages carry the metadata search engines and
share targets read (see templates/README.md): the structured data's
author and publisher profiles come from data/authors.json (the Medium
profile of every byline) and site.json's "profiles"/"twitter", the
og:image of a page with no cover from its "share_image", and a post
that declared a canonical on another host (Medium's "originally
published at") carries it as `canonical` in its front matter; the
Medium copy is never a page's canonical. Each post page closes with
related posts (Hugo's related content, by shared tags).

Tags stay slugs in front matter, so each term and its /tags/<tag>/ URL
are exactly the archive's tag; the names tags are shown under
(tags.json's `display`) arrive instead as one data file, data/tags.json,
from which a content adapter, content/tags/_content.gotmpl, creates the
term pages with those titles -- which is how every place Hugo renders a
term (cards, the tag page and its <title>, the chip index, the per-tag
feed) picks a name up at once, and how a checked-in copy of the site
renames a tag by editing one file rather than a directory per tag.

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
import sys

from .sites import (Covers, ImagePlacer, author_links, author_names,
                    author_slug, canonical_for,
                    caption_text, clean_site, copy_site_asset,
                    export_content, fill_template, front_matter_yaml,
                    load_site_inputs, old_paths, page_stems, quote_arg,
                    redirect_rules, redirects_file, rewrite_figures,
                    site_profiles, tag_names,
                    write_redirects_csv, write_templates)

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
    "layouts/partials/paginator.html":
        "hugo/layouts/partials/paginator.html",
    "layouts/partials/jsonld.html": "hugo/layouts/partials/jsonld.html",
    "layouts/partials/related.html": "hugo/layouts/partials/related.html",
    "layouts/robots.txt": "hugo/layouts/robots.txt",
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
    # the term pages, from data/tags.json and data/authornames.json
    # (see write_tag_names and write_author_names)
    "content/tags/_content.gotmpl": "hugo/content/tags/_content.gotmpl",
    "content/authors/_content.gotmpl":
        "hugo/content/authors/_content.gotmpl",
}



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
    def call(alt, src, link, caption):
        q = quote_arg                        # shared with the pelican exporter
        args = f'src="{src}"'
        # plain text, like the pelican exporter's: an alt is prose for a
        # screen reader, and the two sites should read it out the same
        alt = caption_text(alt or caption)    # the caption describes it
        if alt:
            args += f' alt="{q(alt)}"'
        if link:
            args += f' link="{q(link)}"'
        return "{{< figure %s >}}%s{{< /figure >}}" % (args, caption)
    return rewrite_figures(markdown, call)


def front_matter(url: str, post: dict, cover: str | None = None,
                 canonical: str | None = None) -> str:
    front = {"title": post["title"]}
    if post.get("date"):
        front["date"] = post["date"]
    if post.get("updated"):
        front["lastmod"] = post["updated"]
    if post.get("description"):
        front["description"] = post["description"]
    if post.get("tags"):
        front["tags"] = post["tags"]
    if post.get("authors"):                      # the author taxonomy
        # slugs, as the tags are: a byline left as the term would put
        # its accents and punctuation in the URL (see sites.author_slug)
        front["authors"] = [author_slug(a["name"]) for a in post["authors"]]
    if cover:               # bundle resource: the card cover and og:image
        front["cover"] = cover
    if post.get("first_image"):     # loaded eagerly, the rest lazily
        front["first_image"] = post["first_image"]
    if canonical:           # the page is a copy of this one, and says so
        front["canonical"] = canonical
    front["aliases"] = [path for path, _ in old_paths(post, url)]
    return front_matter_yaml(front)


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


def write_author_links(site, links: dict):
    """data/authors.json: author name -> profile address, what the
    theme's structured data names as each author's sameAs (on posts and
    on the author's own page) and what a checked-in copy of the site
    edits to add or correct one. The author taxonomy's term titles are
    the names as written, which is the key here."""
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / "authors.json").write_text(
        json.dumps(links, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


def write_author_names(site, names: dict):
    """data/authornames.json: author slug -> the name they are shown
    under, the one file the site's author content adapter
    (content/authors/_content.gotmpl) builds the term pages from. Front
    matter keeps the slug, so the term and its /authors/<slug>/ URL
    match the pelican site's, and only the title Hugo renders carries
    the name's capitals, accents and punctuation."""
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / "authornames.json").write_text(
        json.dumps(dict(sorted(names.items())), indent=2, ensure_ascii=False)
        + "\n", encoding="utf-8")


def write_tag_names(site, names: dict):
    """data/tags.json: tag slug -> the name the tag is shown under, the
    one file the site's content adapter (content/tags/_content.gotmpl,
    in TEMPLATES) builds the term pages from. Front matter keeps the
    slug, so the term and its /tags/<tag>/ URL are unchanged and it is
    only the title Hugo renders that gains its spaces and capitals --
    which means every place a term's title reaches (cards, the tag page
    heading and <title>, the chip index, per-tag RSS) is covered at
    once, in a real theme as much as in the built-in one."""
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / "tags.json").write_text(
        json.dumps(dict(sorted(names.items())), indent=2, ensure_ascii=False)
        + "\n", encoding="utf-8")


def build_site(out):
    manifest, config = load_site_inputs(out)
    stems = page_stems(manifest)
    hugo_config = config.get("hugo", {})
    site = out / "site-hugo"
    clean_site(site, keep=("public", "resources"))

    (site / "content").mkdir(parents=True)
    (site / "content" / "_index.md").write_text(
        front_matter_yaml({"title": config["title"]})
        + (config.get("intro", "") + "\n" if config.get("intro") else ""),
        encoding="utf-8")
    # the theme's Pagefind search page and year-grouped archives timeline;
    # search results are nobody's landing page, so the search page is
    # kept out of the index and the sitemap, as WordPress keeps its own
    (site / "content" / "search.md").write_text(
        front_matter_yaml({"title": "Search", "layout": "search",
                           "url": "/search/", "noindex": True,
                           "sitemap": {"disable": True}}), encoding="utf-8")
    (site / "content" / "archives.md").write_text(
        front_matter_yaml({"title": "Archives", "layout": "archives",
                           "url": "/archives/"}), encoding="utf-8")
    # the tag and author indexes, titled as the nav names them (with
    # capitalizeListTitles off for the terms' sake, Hugo would title
    # them by their lowercase path, which the breadcrumbs would repeat)
    for plural, title in (("tags", "Tags"), ("authors", "Authors")):
        (site / "content" / plural).mkdir(exist_ok=True)
        (site / "content" / plural / "_index.md").write_text(
            front_matter_yaml({"title": title}), encoding="utf-8")
    covers = Covers(out, manifest)
    pages = export_content(
        out, site, manifest, stems,
        lambda url, p: front_matter(url, p, cover=covers.path(url),
                                    canonical=canonical_for(p)),
        placer=ImagePlacer(out, config), transform=figure_shortcodes,
        covers=covers)
    # Hugo makes content/posts/ a section and publishes a list page and
    # a feed for it unasked: /posts/ is the home listing again, its 14
    # pagination pages included, canonical to itself and in the sitemap
    # while nothing links to it -- two indexable addresses for one
    # listing, the second headed by a bare lowercase "posts". Pelican
    # has no sections (posts/<slug>/ is only a URL pattern there), so
    # dropping the page is also what makes the two sites agree. The
    # posts themselves are untouched; only the section's own page goes.
    (site / "content" / "posts" / "_index.md").write_text(
        front_matter_yaml({"title": "Posts",
                           "_build": {"render": "never",
                                      "list": "never"}}),
        encoding="utf-8")
    write_tag_names(site, tag_names(manifest, out))
    write_author_names(site, author_names(manifest))
    write_author_links(site, author_links(manifest))

    params = {"description": config.get("description", "")}
    # "avatar" (site.json top level, or hugo section): a hand-picked site
    # logo, shown in the header; "favicon" likewise: the tab icon, at the
    # site root so browsers that ask for /favicon.ico by convention are
    # covered when it is an .ico
    avatar = copy_site_asset(
        out, hugo_config.get("avatar") or config.get("avatar"),
        site / "static" / "img", "avatar")
    if avatar:
        params["avatar"] = f"img/{avatar}"
    favicon = copy_site_asset(
        out, hugo_config.get("favicon") or config.get("favicon"),
        site / "static", "favicon")
    if favicon:
        params["favicon"] = favicon
    # "announcement": a site-wide banner above the header -- an http(s)
    # URL the theme fetches client-side (empty content hides the banner,
    # like Sphinx themes' html announcement option), or literal HTML
    if config.get("announcement"):
        params["announcement"] = config["announcement"]
    # "noindex": keep search engines off this deployment (a preview);
    # "twitter": the publication's @handle, credited on shared links
    if config.get("noindex"):
        params["noindex"] = True
    if config.get("twitter"):
        params["twitter"] = config["twitter"]
    # "profiles" (+ the twitter handle): the publication's addresses
    # elsewhere, the Organization's sameAs in the structured data
    if site_profiles(config):
        params["profiles"] = site_profiles(config)
    # "share_image": the og:image of every page without a cover of its
    # own (listings, posts with no usable image), under assets/ so the
    # theme can read its dimensions
    share = copy_site_asset(out, config.get("share_image"),
                            site / "assets" / "img", "share")
    if share:
        params["share_image"] = f"img/{share}"
    params.update(hugo_config.get("params", {}))
    (site / "hugo.toml").write_text(fill_template(
        "hugo/hugo.toml.tmpl",
        base_url=json.dumps(config.get("base_url", "https://example.org/")),
        title=json.dumps(config["title"], ensure_ascii=False),
        locale=json.dumps(hugo_config.get("locale", "en")),
        params=_toml_params(params),
    ), encoding="utf-8")
    write_templates(site, TEMPLATES)
    new_path = lambda stem: f"/posts/{stem}/"
    write_redirects_csv(site, manifest, stems, new_path)
    # the same map as a host-level `_redirects` file, copied to the site
    # root from static/ (see sites.redirects_file)
    (site / "static").mkdir(exist_ok=True)
    (site / "static" / "_redirects").write_text(
        redirects_file(redirect_rules(manifest, stems, new_path)),
        encoding="utf-8")
    print(f"hugo done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    print(f"render it with: cd {site} && hugo server   (or: hugo; then "
          "`pagefind --site public` for search)", file=sys.stderr)
    return site


def cmd_hugo(args):
    build_site(args.out)
