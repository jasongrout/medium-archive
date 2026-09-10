"""The hugo step: build a Hugo site in site-hugo/ from the
converted archive. Same reproducibility contract as the myst step (see
sites.py); render with `hugo` or `hugo server` inside site-hugo/
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
per-term RSS feeds. Every old inbound path (Medium slug+id, /p/<id>,
Ghost-era) is carried by whichever redirect mechanism site.toml's
"redirects" asks for (see sites.REDIRECT_MODES): as an alias, which
Hugo emits a redirect stub for and which works on any static host, as
a `_redirects` file for the hosts that turn one into HTTP 301s, or as
both. Hugo's own sitemap.xml (page lastmod from the post's updated
date) is joined by a robots.txt naming it, and the theme's pages carry the metadata search engines and
share targets read (see templates/README.md): the structured data's
author and publisher profiles come from data/authors.json (the Medium
profile of every byline) and site.toml's "profiles"/"twitter", the
og:image of a page with no cover from its "share_image", and a post
that declared a canonical on another host (Medium's "originally
published at") carries it as `canonical` in its front matter; the
Medium copy is never a page's canonical. Each post page closes with a
"More posts" block (Hugo's related content, by shared tags).

Tags stay slugs in front matter, so each term and its /tags/<tag>/ URL
are exactly the archive's tag; the names tags are shown under
(tags.json's `display`) arrive instead as one data file, data/tags.json,
from which a content adapter, content/tags/_content.gotmpl, creates the
term pages with those titles -- which is how every place Hugo renders a
term (cards, the tag page and its <title>, the chip index, the per-tag
feed) picks a name up at once, and how a checked-in copy of the site
renames a tag by editing one file rather than a directory per tag.
Author names (data/authornames.json) and the byline profiles the
structured data reads (data/authors.json) are the same arrangement.
The pelican exporter writes all three files, with the same names and
contents, and its generated config reads them the way Hugo reads these
(see sites.write_data_files).

Hugo has no default theme. The exporter writes a small self-contained
one (layouts/ + css, from the package's templates/hugo/ and
templates/shared/ files) with light and dark palettes and a
light/dark/system picker in the header (the choice persists per
browser; with none stored, the system scheme decides) and
click-to-zoom body images (post pages open an image whose original
holds more detail than the column shows full size in a modal, like
Medium's); search is then
the one feature Hugo does not generate (run `pagefind --site public`
after `hugo` for a static search UI).

The config is written as a directory, config/_default/, so that what
the site says about itself and how it is built are separate files:
params.toml carries the data the theme renders from (the masthead and
where it points, the banner, the footer line, the newsletter band, the
share image, `noindex`, the publication's handle and profiles), and
hugo.toml the machinery -- the taxonomies, the related-posts index,
the paginator, Goldmark and Chroma -- plus the address, name and
language Hugo takes only at the root of its configuration. That is the
same split the pelican site makes between its site.toml and its
generated pelicanconf.py, in the file Hugo's own conventions put it
in. Hugo reads a config directory in preference to a root config file,
so there is one place to look. site.toml's optional `hugo` section
tunes what is written: `locale`, `avatar`, `favicon`, `logo` and
`logo_dark` (overriding the top-level keys), and `params` merged last
into params.toml.
"""

import json
import sys
from pathlib import Path

from .paths import archive_dir, site_dir, site_inputs
from .siteconf import documented_toml
from .sites import (Covers, ImagePlacer, author_slug, canonical_for,
                    caption_text, clean_site, copy_site_asset,
                    export_content, fill_template, front_matter_yaml,
                    load_site_inputs, masthead_link, newsletter_params,
                    old_paths, page_stems, quote_arg,
                    redirect_mode, redirect_rules, redirects_file,
                    rewrite_figures, site_profiles, wants_redirect_stubs,
                    wants_redirects_file, write_data_files,
                    write_redirects_csv, write_templates)

# The files the exporter copies in: file in the site -> its templates/
# source (see templates/README.md for the rationale behind the
# individual files). The built-in theme is most of them: the regular
# list and taxonomy pages share one layout, and the stylesheet is the
# card look shared with the pelican theme. The feed override and the
# figure shortcode (with the image partial it and the render hook
# share) are content policy rather than styling: the pages' figure
# calls resolve to that shortcode, which takes the caption as inner
# content. The README and the .gitignore are neither: they are what
# make the directory a repository of its own rather than a build
# output, which is what it becomes once the archive is done with it.
# (The .gitignore's source is named without the dot, so that git does
# not read it as an ignore file for templates/hugo/ itself.)
TEMPLATES = {
    "README.md": "hugo/README.md",
    ".gitignore": "hugo/gitignore",
    "layouts/baseof.html": "hugo/layouts/baseof.html",
    "layouts/_partials/card.html": "hugo/layouts/_partials/card.html",
    "layouts/_partials/share.html": "hugo/layouts/_partials/share.html",
    "layouts/_partials/paginator.html":
        "hugo/layouts/_partials/paginator.html",
    "layouts/_partials/jsonld.html": "hugo/layouts/_partials/jsonld.html",
    "layouts/_partials/related.html": "hugo/layouts/_partials/related.html",
    "layouts/robots.txt": "hugo/layouts/robots.txt",
    "layouts/home.html": "hugo/layouts/home.html",
    "layouts/page.html": "hugo/layouts/page.html",
    # one listing layout for the post section and for a tag's or an
    # author's page; the terms index has its own
    "layouts/section.html": "hugo/layouts/section.html",
    "layouts/term.html": "hugo/layouts/section.html",
    "layouts/taxonomy.html": "hugo/layouts/taxonomy.html",
    "layouts/archives.html": "hugo/layouts/archives.html",
    "layouts/search.html": "hugo/layouts/search.html",
    "layouts/alias.html": "hugo/layouts/alias.html",
    "layouts/_markup/render-image.html":
        "hugo/layouts/_markup/render-image.html",
    "layouts/rss.xml": "hugo/layouts/rss.xml",
    "layouts/_shortcodes/figure.html": "hugo/layouts/_shortcodes/figure.html",
    "layouts/_partials/post-image.html":
        "hugo/layouts/_partials/post-image.html",
    "static/css/style.css": "shared/card.css",
    # the term pages, from data/tags.json and data/authornames.json
    # (see sites.write_data_files)
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
                 canonical: str | None = None, aliases: bool = True) -> str:
    front = {"title": post["title"]}
    if post.get("date"):
        front["date"] = post["date"]
    if post.get("updated"):
        front["lastmod"] = post["updated"]
    if post.get("subtitle"):        # the page's subtitle line (page.html)
        front["subtitle"] = post["subtitle"]
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
    if aliases:     # Hugo renders a redirect stub at each (alias.html)
        front["aliases"] = [path for path, _ in old_paths(post, url)]
    return front_matter_yaml(front)


# The three keys Hugo takes at the root of its configuration rather
# than as params, and so writes into hugo.toml instead: the site's
# address, its name and its language. params.toml documents the rest.
HUGO_ROOT_KEYS = ("base_url", "title", "locale")

# Keys this site resolves to a different path from the pelican site
# that siteconf's examples are written for: its images sit under
# static/ and assets/ rather than inside a theme, so what params.toml
# shows of an unset one has to be what this exporter would write.
HUGO_EXAMPLES = {
    "avatar": "img/avatar.svg",
    "favicon": "favicon.svg",
    "logo": "img/logo.svg",
    "logo_dark": "img/logo-dark.svg",
    "share_image": "img/share.png",
}

# What params.toml has no key for at all: the landing-page blurb is
# content/_index.md on this site, and the two image sizes and the
# redirect mode are things the pelican config needs told and Hugo works
# out or is given elsewhere (its own image pipeline; aliases in each
# post's front matter, or static/_redirects).
HUGO_OMITTED = ("intro", "share_image_size", "cover_size", "redirects")


def build_site(root, site=None, force=False):
    archive = archive_dir(root)
    inputs = site_inputs(root)
    manifest, config = load_site_inputs(root)
    stems = page_stems(manifest)
    hugo_config = config.get("hugo", {})
    mode = redirect_mode(config)        # site.toml "redirects"
    # site-hugo/ beside the archive, or wherever --site-out sends it
    site = Path(site) if site else site_dir(root, "hugo")
    clean_site(site, keep=("public", "resources"),
               expect=("config", "content"), force=force)

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
    covers = Covers(archive, manifest)
    pages = export_content(
        archive, site, manifest, stems,
        lambda url, p: front_matter(url, p, cover=covers.path(url),
                                    canonical=canonical_for(p),
                                    aliases=wants_redirect_stubs(mode)),
        placer=ImagePlacer(root, config), transform=figure_shortcodes,
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
                           "build": {"render": "never",
                                     "list": "never"}}),
        encoding="utf-8")
    # data/tags.json, data/authornames.json and data/authors.json: the
    # slug-to-name maps the term content adapters build the tag and
    # author pages from, and the byline profiles the structured data
    # names as each author's sameAs. Hugo reads them through hugo.Data;
    # the pelican site is given the same three files (see
    # sites.write_data_files).
    write_data_files(site, manifest, archive)

    params = {}
    if config.get("description"):
        params["description"] = config["description"]
    # without a footer line the footer carries the site's description,
    # as it always has (baseof.html)
    if config.get("footer"):
        params["footer"] = config["footer"]
    # every image key may be set in site.toml's [hugo] section instead,
    # to give this site a different mark from the pelican one. The
    # favicon goes to the site root, so browsers that ask for
    # /favicon.ico by convention are covered when it is an .ico.
    avatar = copy_site_asset(
        inputs, hugo_config.get("avatar") or config.get("avatar"),
        site / "static" / "img", "avatar")
    if avatar:
        params["avatar"] = f"img/{avatar}"
    favicon = copy_site_asset(
        inputs, hugo_config.get("favicon") or config.get("favicon"),
        site / "static", "favicon")
    if favicon:
        params["favicon"] = favicon
    logo = copy_site_asset(
        inputs, hugo_config.get("logo") or config.get("logo"),
        site / "static" / "img", "logo")
    if logo:
        params["logo"] = f"img/{logo}"
        logo_dark = copy_site_asset(
            inputs, hugo_config.get("logo_dark") or config.get("logo_dark"),
            site / "static" / "img", "logo-dark")
        if logo_dark:
            params["logo_dark"] = f"img/{logo_dark}"
        # read only where there is a logo to carry it, as the dark
        # mark is (see sites.masthead_link)
        link = masthead_link(config)
        if link:
            params["logo_link"] = link
    if config.get("announcement"):
        params["announcement"] = config["announcement"]
    if config.get("noindex"):
        params["noindex"] = True
    if config.get("twitter"):
        params["twitter"] = config["twitter"]
    # the twitter handle's own profile joins the list here
    if site_profiles(config):
        params["profiles"] = site_profiles(config)
    # see sites.newsletter_params
    newsletter = newsletter_params(config)
    if newsletter:
        params["newsletter"] = newsletter
    # under assets/, so the theme's own image pipeline can read its
    # dimensions rather than being told them
    share = copy_site_asset(inputs, config.get("share_image"),
                            site / "assets" / "img", "share")
    if share:
        params["share_image"] = f"img/{share}"
    params.update(hugo_config.get("params", {}))
    # The config as a directory rather than one hugo.toml, so that what
    # this site says about itself and how it is built are separate
    # files: params.toml is the site's data, hand-editable and the only
    # one a checked-in copy of the site has to touch for its own
    # furniture, and every key in it carries what it is for; hugo.toml
    # is the machinery, plus the three keys Hugo takes at the root of
    # its configuration and nowhere else -- its address, its name and
    # its language. Hugo reads a config directory in preference to a
    # root config file, so nothing else in the site is a second place
    # to look. The pelican site splits the same two apart the same way
    # (site.toml and pelicanconf.py).
    config_dir = site / "config" / "_default"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hugo.toml").write_text(fill_template(
        "hugo/hugo.toml.tmpl",
        base_url=json.dumps(config.get("base_url", "https://example.org/")),
        title=json.dumps(config["title"], ensure_ascii=False),
        locale=json.dumps(hugo_config.get("locale")
                          or config.get("locale") or "en"),
    ), encoding="utf-8")
    # every key under its own documentation, an unset one commented
    # out beside an example of it set, from the same table the pelican
    # site's site.toml is written from (siteconf.SITE_KEYS) -- so the
    # two engines cannot come to describe the same key differently
    (config_dir / "params.toml").write_text(fill_template(
        "hugo/params.toml.tmpl",
        params=documented_toml(params, examples=HUGO_EXAMPLES,
                               omit=HUGO_ROOT_KEYS + HUGO_OMITTED)),
        encoding="utf-8")
    write_templates(site, TEMPLATES)
    new_path = lambda stem: f"/posts/{stem}/"
    # the map itself, whichever mechanism serves it: what a redirect
    # rule set built anywhere else is built from
    write_redirects_csv(site, manifest, stems, new_path)
    # the same map as a host-level `_redirects` file, copied to the site
    # root from static/ (see sites.REDIRECT_MODES)
    if wants_redirects_file(mode):
        (site / "static").mkdir(exist_ok=True)
        (site / "static" / "_redirects").write_text(
            redirects_file(redirect_rules(manifest, stems, new_path)),
            encoding="utf-8")
    print(f"hugo done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    print(f"render it with: cd {site} && hugo server   (or: hugo; then "
          "`pagefind --site public` for search)", file=sys.stderr)
    return site


def cmd_hugo(args):
    build_site(args.out, args.site_out, args.force)
