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
# Photographs only -- png and webp here are line art the placer kept
# whole (see ImagePlacer), whose 9 px text does not survive a 736 px
# variant, and an animated gif would lose its frames.
VARIANT_WIDTHS = (480, 736, 1104)
SIZES_ATTR = "(max-width: 800px) 100vw, 736px"
IMG_TAG_RE = None   # compiled on first use
ARTICLE_IMG = r"/?posts/[^/]+/images/[^/]+\.(?:png|jpe?g|gif|webp)"
VARIANT_IMG = r"/?posts/[^/]+/images/[^/]+\.jpe?g"


def _prioritize_first_images(pelican_obj):
    # Every body image loads lazily (the _LazyImages extension). The
    # first one on a post page is the one most likely on screen at
    # load, so it is fetched eagerly and first instead, as WordPress
    # treats the first content image: lazy-loading the largest visible
    # image delays the page's largest contentful paint. Body images
    # alone qualify (the header avatar is not one); with none, the
    # page is left as it is.
    import glob
    import os
    import re
    img_re = re.compile(r'<img\b[^>]*\bsrc="(?:%s)?(%s)"[^>]*>'
                        % (re.escape(SITEURL), ARTICLE_IMG), re.I)
    pages = 0
    for page in glob.glob(os.path.join(pelican_obj.output_path,
                                       "posts", "*", "index.html")):
        with open(page, encoding="utf-8") as fh:
            html = fh.read()
        m = img_re.search(html)
        if not m or ' loading="lazy"' not in m.group(0):
            continue
        first = m.group(0).replace(' loading="lazy"', ' fetchpriority="high"', 1)
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(html[:m.start()] + first + html[m.end():])
        pages += 1
    print(f"first images: {pages} pages load theirs eagerly")


def _optimize_article_images(pelican_obj):
    # Rewrite each article's body images (the constrained pattern this
    # exporter itself emits; anything else passes through): every one
    # gets real width/height and a link to the file itself, and
    # photographs additionally get lazily loaded responsive variants.
    # Variants are cached by mtime, so only new or changed images are
    # re-encoded on later builds.
    try:
        from PIL import Image
    except ImportError:
        print("pillow not installed: body images keep their full-size "
              "originals (pip install pillow and rebuild)")
        return
    import glob
    import os
    import re
    tag_re = re.compile(r"<img\b[^>]*>")
    attr_re = re.compile(r'([-\w]+)="([^"]*)"')
    path_re = re.compile(ARTICLE_IMG + "$", re.I)
    variant_re = re.compile(VARIANT_IMG + "$", re.I)
    stats = {"variants": 0, "pages": 0}

    here = os.path.dirname(os.path.abspath(__file__))

    def rewrite(match):
        tag = match.group(0)
        attrs = dict(attr_re.findall(tag))
        src = attrs.get("src", "")
        path = src[len(SITEURL):] if SITEURL and src.startswith(SITEURL) else src
        if "srcset" in attrs or not path_re.fullmatch(path):
            return tag
        parts = path.lstrip("/").split("/")
        local = os.path.join(pelican_obj.output_path, *parts)
        # encode from (and cache against) the content-side original:
        # Pelican freshens the output copy's mtime on every build, which
        # would defeat the cache
        source = os.path.join(here, PATH, *parts)
        if not os.path.exists(source):
            source = local
        try:
            wants_variants = bool(variant_re.fullmatch(path))
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
            return tag
        extra = ""
        if "width" not in attrs and "height" not in attrs:
            extra += ' width="%d" height="%d"' % (width, height)
        if srcset:
            extra += ' srcset="%s" sizes="%s"' % (", ".join(srcset), SIZES_ATTR)
        if not extra:
            return tag
        end = "/>" if tag.endswith("/>") else ">"
        return tag[:-len(end)] + extra + end

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


class _SitePlugins:
    @staticmethod
    def register():
        from pelican import signals
        signals.article_generator_finalized.connect(_name_tags)
        signals.article_generator_finalized.connect(_collect_sitemap)
        signals.finalized.connect(_prioritize_first_images)
        signals.finalized.connect(_optimize_article_images)
        signals.finalized.connect(_write_redirect_stubs)
        signals.finalized.connect(_write_crawl_files)


PLUGINS = [_SitePlugins]
