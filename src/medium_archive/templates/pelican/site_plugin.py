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
    # to the pages this site serves. Works on any static host.
    import csv
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "redirects.csv"), newline="",
              encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
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


class _SitePlugins:
    @staticmethod
    def register():
        from pelican import signals
        signals.finalized.connect(_optimize_article_images)
        signals.finalized.connect(_write_redirect_stubs)


PLUGINS = [_SitePlugins]
