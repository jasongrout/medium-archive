# Substituted into STUB as a format() value, never as a format string:
# the spliced CSS/JS is full of braces.
THEME_HEAD = """\
<!-- @include shared/redirect-head.html -->
"""

STUB = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{target}</title>
<link rel="canonical" href="{target}">
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url={target}">
{theme_head}</head><body><a href="{target}">{target}</a></body></html>
"""


def _write_redirect_stubs(pelican_obj):
    # Pelican has no aliases feature, so after each build this writes a
    # meta-refresh stub at every old inbound path from redirects.csv --
    # the exporter's map of Medium slug+id, /p/<id> and Ghost-era paths
    # to the pages this site serves. Works on any static host. The same
    # map goes to the site root as a `_redirects` file, one
    # `old new 301` rule per line, which Netlify, Cloudflare Pages and
    # their imitators answer with a real HTTP 301 -- credited by search
    # engines to the new page directly; a host that ignores the file
    # serves the stubs.
    import csv
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "redirects.csv"), newline="",
              encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with open(os.path.join(pelican_obj.output_path, "_redirects"), "w",
              encoding="utf-8") as fh:
        fh.writelines(f"{row['old_path']} {row['new_path']} 301\n"
                      for row in rows)
    written = 0
    for row in rows:
        parts = [p for p in row["old_path"].split("/") if p]
        stub = os.path.join(pelican_obj.output_path, *parts, "index.html")
        if os.path.exists(stub):        # never clobber a real page
            continue
        os.makedirs(os.path.dirname(stub), exist_ok=True)
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write(STUB.format(target=SITEURL + row["new_path"],
                                 theme_head=THEME_HEAD))
        written += 1
    print(f"redirect stubs: {written} written from redirects.csv")


# What the sitemap lists: the pages of the site by their URL, with a
# last-modified date where one is known (posts: the Modified header,
# the archive's updated date, else the post date). Collected once the
# articles are read, written after the build beside a robots.txt that
# names the sitemap -- what WordPress serves on its own and Hugo
# generates for its site. Search results, paginated listings and the
# redirect stubs stay out, as they do from Hugo's.
_SITEMAP = []


def _collect_sitemap(article_generator):
    g = article_generator
    _SITEMAP.clear()
    _SITEMAP.append(("", None))
    for article in g.articles:
        modified = getattr(article, "modified", None) or article.date
        _SITEMAP.append((article.url, modified))
    for tag in g.tags:
        _SITEMAP.append((tag.url, None))
    for author, _ in g.authors:
        _SITEMAP.append((author.url, None))
    for url in (TAGS_URL, AUTHORS_URL, ARCHIVES_URL):
        _SITEMAP.append((url, None))


def _write_crawl_files(pelican_obj):
    import os
    from xml.sax.saxutils import escape
    out = pelican_obj.output_path
    with open(os.path.join(out, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write("User-agent: *\n")
        if NOINDEX:
            fh.write("Disallow: /\n")
        else:
            fh.write(f"Allow: /\n\nSitemap: {SITEURL}/sitemap.xml\n")
    lines = ['<?xml version="1.0" encoding="utf-8" standalone="yes"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, modified in _SITEMAP:
        lines.append(f"  <url><loc>{escape(SITEURL + '/' + url)}</loc>"
                     + (f"<lastmod>{modified.isoformat()}</lastmod>"
                        if modified else "") + "</url>")
    lines.append("</urlset>")
    with open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"sitemap: {len(_SITEMAP)} urls")


# Responsive body images, like the hugo exporter's render hook: webp
# variants at these widths (never upscaled), advertised via srcset with
# this sizes hint, plus real width/height so the layout cannot shift.
VARIANT_WIDTHS = (480, 736, 1104)
SIZES_ATTR = "(max-width: 800px) 100vw, 736px"
# An <img> tag, spanning its attribute values rather than stopping at
# the first ">": an alt text can hold one (a caption naming a <code>
# span, say), and a pattern that stopped there would match a fragment
# with no src in it, leaving the image unprocessed and its marker on.
IMG_TAG = r"""<img\b(?:[^>"']|"[^"]*"|'[^']*')*>"""
IMG_TAG_RE = None   # compiled on first use
# Which images this pass may touch: the ones the config's reader
# marked, and only those. The marker is how a body image is told from
# one the theme rendered, since by this point -- the finished HTML --
# the two are indistinguishable markup. A path rule cannot stand in for
# it: a related-post card points into another post's own images/
# directory, exactly where that post's body images live.
BODY_IMAGE_ATTR = "data-body-image"
# Photographs get the variant ladder. png and webp here are line art
# the placer kept whole (see ImagePlacer), whose 9 px text does not
# survive a 736 px variant, and an animated gif would lose its frames.
VARIANT_SUFFIXES = (".jpg", ".jpeg")


def _prioritize_first_images(pelican_obj):
    # Every body image loads lazily (the config's reader marks them as
    # it renders). The first one on a post page is the one most likely
    # on screen at load, so it is fetched eagerly and first instead, as
    # WordPress treats the first content image: lazy-loading the
    # largest visible image delays the page's largest contentful paint.
    # Body images alone qualify -- the header avatar and the
    # related-post cards are not marked, so they cannot be picked; with
    # none, the page is left as it is.
    import glob
    import os
    import re
    img_re = re.compile(IMG_TAG, re.I)
    pages = 0
    for page in glob.glob(os.path.join(pelican_obj.output_path,
                                       "posts", "*", "index.html")):
        with open(page, encoding="utf-8") as fh:
            html = fh.read()
        m = next((m for m in img_re.finditer(html)
                  if BODY_IMAGE_ATTR in m.group(0)), None)
        if not m or ' loading="lazy"' not in m.group(0):
            continue
        first = m.group(0).replace(' loading="lazy"', ' fetchpriority="high"', 1)
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(html[:m.start()] + first + html[m.end():])
        pages += 1
    print(f"first images: {pages} pages load theirs eagerly")


def _optimize_article_images(pelican_obj):
    # Rewrite each article's body images -- the ones the Markdown
    # extension marked, and nothing else: every one gets real
    # width/height, and photographs additionally get lazily loaded
    # responsive variants. Variants are cached by mtime, so only new or
    # changed images are re-encoded on later builds.
    #
    # The marker comes off here, on every marked tag, whether or not
    # this pass had anything to add to it, so it never reaches a reader.
    try:
        from PIL import Image
    except ImportError:
        print("pillow not installed: body images keep their full-size "
              "originals (pip install pillow and rebuild)")
        return
    import glob
    import os
    import re
    tag_re = re.compile(IMG_TAG)
    attr_re = re.compile(r'([-\w]+)="([^"]*)"')
    marker_re = re.compile(r'\s*\b%s\b(?:="[^"]*")?' % BODY_IMAGE_ATTR, re.I)
    stats = {"variants": 0, "pages": 0}

    here = os.path.dirname(os.path.abspath(__file__))

    def rewrite(match):
        tag = match.group(0)
        if not marker_re.search(tag):    # the theme's, not a body's
            return tag
        bare = marker_re.sub("", tag, count=1)
        attrs = dict(attr_re.findall(tag))
        src = attrs.get("src", "")
        path = src[len(SITEURL):] if SITEURL and src.startswith(SITEURL) else src
        # an image the archive never localized (a remote CDN URL that
        # lint reports) has no file here to measure or re-encode
        if "srcset" in attrs or "://" in path:
            return bare
        parts = path.lstrip("/").split("/")
        local = os.path.join(pelican_obj.output_path, *parts)
        # encode from (and cache against) the content-side original:
        # Pelican freshens the output copy's mtime on every build, which
        # would defeat the cache
        source = os.path.join(here, PATH, *parts)
        if not os.path.exists(source):
            source = local
        try:
            wants_variants = path.lower().endswith(VARIANT_SUFFIXES)
            with Image.open(source) as im:
                width, height = im.size
                srcset = []
                # line art and animations are read for their dimensions
                # alone; only a photograph is decoded and re-encoded
                if wants_variants:
                    if im.mode == "P":
                        im = im.convert("RGBA")
                    elif im.mode not in ("RGB", "RGBA"):
                        im = im.convert("RGB")
                for vw in (VARIANT_WIDTHS if wants_variants else ()):
                    if width < vw:
                        continue
                    variant = os.path.splitext(local)[0] + "-%d.webp" % vw
                    if (not os.path.exists(variant) or
                            os.path.getmtime(variant) < os.path.getmtime(source)):
                        vh = max(1, round(height * vw / width))
                        im.resize((vw, vh), Image.Resampling.LANCZOS).save(
                            variant, "WEBP", quality=75)
                        stats["variants"] += 1
                    srcset.append("%s-%d.webp %dw"
                                  % (os.path.splitext(src)[0], vw, vw))
        except OSError:
            return bare
        extra = ""
        if "width" not in attrs and "height" not in attrs:
            extra += ' width="%d" height="%d"' % (width, height)
        if srcset:
            extra += ' srcset="%s" sizes="%s"' % (", ".join(srcset), SIZES_ATTR)
        if not extra:
            return bare
        end = "/>" if bare.endswith("/>") else ">"
        return bare[:-len(end)] + extra + end

    for page in glob.glob(os.path.join(pelican_obj.output_path,
                                       "posts", "*", "index.html")):
        with open(page, encoding="utf-8") as fh:
            html = fh.read()
        rewritten = tag_re.sub(rewrite, html)
        if rewritten != html:
            with open(page, "w", encoding="utf-8") as fh:
                fh.write(rewritten)
            stats["pages"] += 1
    print("responsive images: %(variants)d variants encoded, "
          "%(pages)d pages rewritten" % stats)


def _name_tags(article_generator):
    # A tag reaches Pelican as the archive's slug, so tag.slug -- what
    # /tags/<slug>/, the per-tag feed's filename and the object's own
    # hash are built from -- is exactly right, and only the name a
    # reader sees is left to set. Pelican renders a tag from the Tag
    # object everywhere, including the per-tag feed's title, which it
    # builds in Python out of reach of any template; so the objects
    # themselves are named here, the way the hugo site's content adapter
    # titles each term from data/tags.json. Runs on article_generator_finalized: the
    # tags are collected by then and nothing is written yet.
    #
    # Pelican builds a Tag object per article, from that article's own
    # Tags: header, and generator.tags is a dict keyed on the slug -- so
    # it holds one object per tag and every other article keeps its own.
    # Naming the dict's keys alone would name a tag on its own page and
    # on one article's card, and leave it a slug on all the others; so
    # each article's list is pointed at the one named object instead,
    # which leaves exactly one Tag per slug in the whole build.
    canonical = {}

    def name(tag):
        got = canonical.get(tag.slug)
        if got is None:
            shown = TAG_DISPLAY.get(tag.slug)
            if shown and shown != tag.name:
                tag.slug = tag.slug     # pin it: setting a name otherwise
                tag.name = shown        # re-slugifies, "C++" -> /tags/c/
            canonical[tag.slug] = got = tag
        return got

    for tag in article_generator.tags:      # the dict's keys first, so
        name(tag)                           # its objects are the shared ones
    articles = 0
    for group in ("articles", "translations", "hidden_articles",
                  "hidden_translations", "drafts", "drafts_translations"):
        for article in getattr(article_generator, group, ()):
            if getattr(article, "tags", None):
                article.tags = [name(tag) for tag in article.tags]
                articles += 1
    print(f"tag names: {len(canonical)} tags named across {articles} articles")


def _name_authors(article_generator):
    # The authors' counterpart of _name_tags, and for the same reason: a
    # byline reaches Pelican as the archive's slug, so author.slug --
    # what /authors/<slug>/, the per-author feed's filename and the
    # object's own hash are built from -- matches the hugo site exactly,
    # and only the name a reader sees is left to set. Pelican renders an
    # author from the Author object everywhere, the per-author feed's
    # title included, which it builds in Python out of reach of any
    # template; so the objects themselves are named here.
    #
    # generator.authors is a list of (author, articles) pairs, and each
    # article carries its own Author objects, so as with tags every
    # article's list is pointed at the one named object per slug.
    canonical = {}

    def name(author):
        got = canonical.get(author.slug)
        if got is None:
            shown = AUTHOR_DISPLAY.get(author.slug)
            if shown and shown != author.name:
                author.slug = author.slug   # pin it: setting a name
                author.name = shown         # otherwise re-slugifies
            canonical[author.slug] = got = author
        return got

    for author, _articles in article_generator.authors:
        name(author)
    articles = 0
    for group in ("articles", "translations", "hidden_articles",
                  "hidden_translations", "drafts", "drafts_translations"):
        for article in getattr(article_generator, group, ()):
            if getattr(article, "authors", None):
                article.authors = [name(a) for a in article.authors]
                articles += 1
            if getattr(article, "author", None):
                article.author = name(article.author)
    print(f"author names: {len(canonical)} authors named across "
          f"{articles} articles")


def related_posts(article, articles, limit=3):
    # The posts most like this one, for the "More posts" block at
    # the foot of its page: scored the way the hugo site's [related]
    # config scores them -- a shared tag counts for most, a shared
    # author for some, and among equals the nearer in time comes
    # first -- and only posts that share something at all.
    tags = {t.slug for t in getattr(article, "tags", ())}
    authors = {a.name for a in getattr(article, "authors", ())}

    def score(other):
        return (100 * len(tags & {t.slug for t in getattr(other, "tags", ())})
                + 30 * len(authors & {a.name for a in getattr(other, "authors", ())}))

    ranked = sorted(((score(o), -abs((o.date - article.date).total_seconds()), o)
                     for o in articles if o is not article),
                    key=lambda t: (t[0], t[1]), reverse=True)
    return [o for s, _, o in ranked[:limit] if s > 0]


def _relate_articles(article_generator):
    # Runs on article_generator_finalized, once every article and its
    # tags exist and before anything is written; article.html reads
    # article.related_posts.
    articles = article_generator.articles
    for article in articles:
        article.related_posts = related_posts(article, articles)
    print(f"related posts: {len(articles)} articles")


class _SitePlugins:
    @staticmethod
    def register():
        from pelican import signals
        signals.article_generator_finalized.connect(_name_tags)
        signals.article_generator_finalized.connect(_name_authors)
        signals.article_generator_finalized.connect(_relate_articles)
        signals.article_generator_finalized.connect(_collect_sitemap)
        signals.finalized.connect(_prioritize_first_images)
        signals.finalized.connect(_optimize_article_images)
        signals.finalized.connect(_write_redirect_stubs)
        signals.finalized.connect(_write_crawl_files)


# _CommonMarkPlugin comes from the generated config's own section,
# above this one: it puts the CommonMark reader in front of pelican's
# python-markdown one.
PLUGINS = [_CommonMarkPlugin, _SitePlugins]
