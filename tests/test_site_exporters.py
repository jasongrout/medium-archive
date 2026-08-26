"""The hugo and pelican steps: posts/ + posts.json -> a site."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from medium_archive import hugo, pelican, sites

BASE = "https://blog.example.com"


def make_post(out: Path, manifest: dict, slug: str, mid: str, date: str,
              body: str, **extra) -> str:
    url = f"{BASE}/{slug}-{mid}"
    d = f"posts/{date[:10]}-{slug}"
    post = {"title": slug.replace("-", " ").title(), "author": "Ada Lovelace",
            "author_url": "https://medium.com/@ada", "date": date,
            "updated": None, "original_url": url,
            "original_path": f"/{slug}-{mid}", "medium_id": mid, "slug": slug,
            "canonical_url": None, "ghost_url": None, "description": "About " + slug,
            "tags": ["example"], "images": [], "body_source": "page",
            "dir": d, **extra}
    manifest[url] = post
    post_dir = out / d
    post_dir.mkdir(parents=True)
    (post_dir / "index.md").write_text(
        "---\n" + json.dumps({k: v for k, v in post.items() if k != "dir"})
        + "\n---\n\n" + body, encoding="utf-8")
    return url


@pytest.fixture
def archive(tmp_path):
    manifest = {}
    make_post(tmp_path, manifest, "first-post", "aaa111aaa111",
              "2020-01-05T10:00:00Z",
              f"Hello. See [the sequel]({BASE}/second-post-bbb222bbb222).\n",
              ghost_url=f"{BASE}/2015/06/01/first-post")
    second = tmp_path / "posts/2021-03-01-second-post"
    make_post(tmp_path, manifest, "second-post", "bbb222bbb222",
              "2021-03-01T10:00:00Z",
              "An image:\n\n![pic](images/001-pic.png)\n\n"
              "```\n![fenced](images/lit.png)\n```\n",
              images=["images/001-pic.png"])
    (second / "images").mkdir()
    (second / "images" / "001-pic.png").write_bytes(b"PNG")
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    (tmp_path / "site.json").write_text(json.dumps(
        {"title": "Example Blog", "description": "An example.",
         "intro": "Welcome.", "base_url": "https://blog.example.org/"}))
    return tmp_path


def test_hugo_site(archive):
    (archive / "icon.svg").write_bytes(b"SVG")
    cfg = json.loads((archive / "site.json").read_text())
    cfg["favicon"] = "icon.svg"
    (archive / "site.json").write_text(json.dumps(cfg))
    site = hugo.build_site(archive)
    page = site / "content/posts/second-post/index.md"
    front = json.loads(page.read_text().split("\n\n", 1)[0])
    assert front["title"] == "Second Post"
    assert front["tags"] == ["example"] and front["authors"] == ["Ada Lovelace"]
    assert front["aliases"] == ["/second-post-bbb222bbb222", "/p/bbb222bbb222"]
    assert (page.parent / "images/001-pic.png").read_bytes() == b"PNG"
    # the Ghost-era path becomes an alias too
    first = json.loads((site / "content/posts/first-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    assert "/2015/06/01/first-post" in first["aliases"]
    # in-publication links point at the new page URLs
    assert "](/posts/second-post/)" in (site / "content/posts/first-post/index.md").read_text()
    config = (site / "hugo.toml").read_text()
    assert 'baseURL = "https://blog.example.org/"' in config
    assert 'author = "authors"' in config
    # the tab icon lands at the site root, under its canonical name
    assert 'favicon = "favicon.svg"' in config
    assert (site / "static/favicon.svg").read_bytes() == b"SVG"
    assert 'rel="icon"' in (site / "layouts/_default/baseof.html").read_text()
    # full-content feed, capped: announce new posts, don't ship the archive
    assert "[services.rss]\nlimit = 20" in config
    rss = (site / "layouts/_default/rss.xml").read_text()
    assert "content:encoded" in rss and "srcset" in rss
    # a literal <?xml gets HTML-escaped by Hugo's template engine,
    # producing an invalid feed; it must go through safeHTML
    assert 'printf "<?xml' in rss and "safeHTML" in rss
    assert not rss.lstrip("{}-% \n").startswith("<?xml")
    assert (site / "layouts/_default/single.html").exists()
    # a year-grouped archives timeline, like the pelican theme's
    assert (site / "layouts/_default/archives.html").exists()
    assert '"layout": "archives"' in (site / "content/archives.md").read_text()
    assert "Welcome." in (site / "content/_index.md").read_text()
    assert (site / "redirects.csv").read_text().count("/posts/first-post/") == 3


def test_hugo_dream_theme(archive):
    (archive / "logo.png").write_bytes(b"IMG")
    (archive / "site.json").write_text(json.dumps(
        {"title": "Example Blog",
         "hugo": {"theme": "dream", "theme_repo": "https://example.org/d.git",
                  "avatar": "logo.png", "params": {"motto": "hello"}}}))
    site = hugo.build_site(archive)
    config = (site / "hugo.toml").read_text()
    assert 'theme = "dream"' in config
    assert 'headerTitle = "Example Blog"' in config and "rss = true" in config
    assert "siteStartYear = 2020" in config
    assert 'authors = { href = "/authors", icon = "people", title = "Authors" }' in config
    assert 'motto = "hello"' in config          # user params merge last
    assert 'avatar = "img/avatar.png"' in config
    assert (site / "static/img/avatar.png").read_bytes() == b"IMG"
    # the theme brings its own layouts -- except the feed override, which
    # is content policy, not styling; Dream's extra pages are created
    layouts = [str(p.relative_to(site)) for p in (site / "layouts").rglob("*")
               if p.is_file()]
    assert layouts == ["layouts/_default/rss.xml"]
    assert (site / "content/search/_index.md").exists()
    assert "Archives" in (site / "content/posts/_index.md").read_text()
    front = json.loads((site / "content/posts/second-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    # the baked card cover doubles as Dream's card and og:image; junk
    # bytes defeat Pillow and are copied in unchanged
    assert front["cover"] == "images/cover.jpg"
    assert front["images"] == ["images/cover.jpg"]
    assert (site / "content/posts/second-post/images/cover.jpg"
            ).read_bytes() == b"PNG"
    assert front["author"] == "Ada Lovelace"
    assert front["authorlink"] == "https://medium.com/@ada"


def test_cover_skips_gifs_and_huge_stills(tmp_path):
    import struct
    images = tmp_path / "images"
    images.mkdir()
    png = lambda w, h: (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                        + struct.pack(">II", w, h) + b"\x00" * 8)
    (images / "big.png").write_bytes(png(7532, 3464))
    (images / "small.png").write_bytes(png(800, 600))
    (images / "anim.gif").write_bytes(b"GIF89a" + struct.pack("<HH", 400, 300))
    assert hugo.image_size(images / "big.png") == (7532, 3464)
    assert hugo.image_size(images / "anim.gif") == (400, 300)
    post = {"images": ["images/anim.gif", "images/big.png", "images/small.png"]}
    assert hugo.pick_cover(post, tmp_path) == "images/small.png"
    assert hugo.pick_cover({"images": ["images/anim.gif"]}, tmp_path) is None
    assert hugo.pick_cover({"images": ["images/missing.png"]}, tmp_path) is None


def test_cover_thumbnails_crop_or_letterbox(tmp_path):
    from PIL import Image

    from medium_archive import sites

    def thumb(im, name):
        src, dst = tmp_path / name, tmp_path / (name + ".jpg")
        im.save(src)
        assert sites.make_cover_thumbnail(src, dst)
        out = Image.open(dst)
        assert out.size == (640, 360)
        return out

    # near-16:9: center-cropped, filling the frame edge to edge
    out = thumb(Image.new("RGB", (800, 450), (160, 20, 20)), "photo.png")
    assert out.getpixel((3, 3))[0] > 100

    # a wide wordmark on white keeps its full width, letterboxed on the
    # border's color instead of cropped
    logo = Image.new("RGB", (1400, 200), "white")
    logo.paste(Image.new("RGB", (1360, 160), "black"), (20, 20))
    out = thumb(logo, "wordmark.png")
    assert all(c > 200 for c in out.getpixel((320, 10)))    # white band
    assert all(c < 60 for c in out.getpixel((320, 180)))    # content kept...
    assert all(c < 60 for c in out.getpixel((15, 180)))     # ...edge to edge

    # a small square logo is centered at no more than 2x, not blown up
    # to fill; transparency composites onto white, not black
    sq = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    sq.paste(Image.new("RGBA", (60, 60, ), (0, 0, 0, 255)), (20, 20))
    out = thumb(sq, "logo.png")
    assert all(c < 60 for c in out.getpixel((320, 180)))    # 2x: 120px wide
    assert all(c > 200 for c in out.getpixel((320, 70)))    # its own margin
    assert all(c > 200 for c in out.getpixel((100, 180)))   # canvas margin

    # no uniform border to extend: the frame fills with a blurred
    # cover-crop of the image itself, never flat bars
    import os
    noisy = Image.frombytes("RGB", (300, 900), os.urandom(300 * 900 * 3))
    out = thumb(noisy, "tall.png")
    corners = {out.getpixel(p) for p in ((3, 3), (636, 3), (3, 356))}
    assert len(corners) > 1


def test_tag_display_names_reach_both_sites(archive):
    """tags.json's display map names each tag on the rendered site while
    the tag itself -- front matter, tag URL -- stays a slug."""
    (archive / "tags.json").write_text(json.dumps(
        {"display": {"example": "Example Tag"}}))
    hugo_site = hugo.build_site(archive)
    front = json.loads((hugo_site / "content/posts/second-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    assert front["tags"] == ["example"]           # the tag is still a slug
    term = hugo_site / "content/tags/example/_index.md"
    assert json.loads(term.read_text()) == {"title": "Example Tag"}

    pelican_site = pelican.build_site(archive)
    head = (pelican_site / "content/posts/second-post/index.md") \
        .read_text().split("\n\n", 1)[0]
    assert "Tags: example" in head                # the tag is still a slug
    config = (pelican_site / "pelicanconf.py").read_text()
    assert '"example": "Example Tag"' in config
    assert "_name_tags" in config          # names the Tag objects, so the
    assert "article_generator_finalized" in config   # feeds get it too


def test_tags_display_as_slugs_with_spaces_by_default(archive):
    """No tags.json at all: a tag still shows with its hyphens as spaces."""
    manifest = json.loads((archive / "posts.json").read_text())
    for post in manifest.values():
        post["tags"] = ["open-science"]
    (archive / "posts.json").write_text(json.dumps(manifest))
    site = hugo.build_site(archive)
    term = site / "content/tags/open-science/_index.md"
    assert json.loads(term.read_text()) == {"title": "open science"}


def test_feed_links_carry_the_rss_mark(archive):
    """The header's feed link and the per-term ones on a tag's and an
    author's page are the shared RSS mark, pointing at that term's own
    feed."""
    hugo_site = hugo.build_site(archive)
    nav = (hugo_site / "layouts/_default/baseof.html").read_text()
    assert '<a class="feed-link" href="{{ "index.xml" | relURL }}"' in nav
    assert 'aria-label="RSS"' in nav and "feed-icon" in nav
    term = (hugo_site / "layouts/_default/list.html").read_text()
    assert '.OutputFormats.Get "rss"' in term    # only where a feed exists
    assert 'aria-label="RSS feed for {{ $.Title }}"' in term

    pelican_site = pelican.build_site(archive)
    for page, setting, var in (("tag.html", "TAG_FEED_ATOM", "tag"),
                               ("author.html", "AUTHOR_FEED_ATOM", "author")):
        text = (pelican_site / "theme/templates" / page).read_text()
        assert f"{setting}.format(slug={var}.slug)" in text
        assert f'aria-label="RSS feed for {{{{ {var} }}}}"' in text
        assert "feed-icon" in text
    # the head declares the term's own feed beside the site-wide one
    base = (pelican_site / "theme/templates/base.html").read_text()
    assert "TAG_FEED_ATOM.format(slug=tag.slug)" in base
    assert "AUTHOR_FEED_ATOM.format(slug=author.slug)" in base
    # ... and hugo's head has the same pair, each titled the way that
    # feed titles itself, so a reader files it under the name it shows
    assert 'site.Home.OutputFormats.Get "rss"' in nav
    assert '{{ $.Title }} · {{ site.Title }}' in nav
    css = (pelican_site / "theme/static/css/style.css").read_text()
    assert ".feed-icon" in css and ".page-title .feed-link" in css


class _FakeTag:
    """pelican.urlwrappers.Tag's naming semantics: hash and equality are
    the slug's, and setting a name re-slugifies unless a slug was set
    explicitly first."""

    def __init__(self, name):
        self._name, self._slug, self._from_name = name, None, True

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value
        if self._from_name:
            self._slug = None

    @property
    def slug(self):
        if self._slug is None:
            self._slug = self._name.lower().replace(" ", "-")
        return self._slug

    @slug.setter
    def slug(self, value):
        self._from_name, self._slug = False, value

    def __hash__(self):
        return hash(self.slug)

    def __eq__(self, other):
        return self.slug == other.slug

    def __str__(self):
        return self.name


def test_every_article_gets_the_named_tag_object(archive):
    """Pelican builds a Tag object per article and keys generator.tags on
    the slug, so it holds one object per tag while every other article
    keeps its own. Naming only the dict's keys named a tag on its own
    page and on one article's card, and left it a slug on the rest."""
    (archive / "tags.json").write_text(json.dumps(
        {"display": {"example": "Example Tag"}}))
    site = pelican.build_site(archive)
    namespace = {}
    exec(compile((site / "pelicanconf.py").read_text(), "pelicanconf.py",
                 "exec"), namespace)

    # three articles, each with its own object for the one tag
    articles = [SimpleNamespace(tags=[_FakeTag("example")]) for _ in range(3)]
    generator = SimpleNamespace(tags={articles[0].tags[0]: articles},
                                articles=articles, translations=[],
                                hidden_articles=[], hidden_translations=[],
                                drafts=[], drafts_translations=[])
    namespace["_name_tags"](generator)

    assert [str(a.tags[0]) for a in articles] == ["Example Tag"] * 3
    # one object per slug now, and the slug is untouched
    assert len({id(a.tags[0]) for a in articles}) == 1
    assert articles[0].tags[0].slug == "example"


def test_pelican_site(archive):
    (archive / "logo.png").write_bytes(b"IMG")
    (archive / "icon.svg").write_bytes(b"SVG")
    cfg = json.loads((archive / "site.json").read_text())
    cfg["avatar"] = "logo.png"
    cfg["favicon"] = "icon.svg"
    (archive / "site.json").write_text(json.dumps(cfg))
    site = pelican.build_site(archive)
    text = (site / "content/posts/second-post/index.md").read_text()
    head = text.split("\n\n", 1)[0]
    assert "Title: Second Post" in head
    assert "Date: 2021-03-01 10:00" in head
    assert "Author: Ada Lovelace" in head
    assert "Tags: example" in head and "Slug: second-post" in head
    assert "Cover: images/" in head          # summary-card cover
    # colocated images become {attach} links -- but not inside fences
    assert "]({attach}images/001-pic.png)" in text
    assert "![fenced](images/lit.png)" in text
    config = (site / "pelicanconf.py").read_text()
    assert 'SITENAME = "Example Blog"' in config
    assert 'ARTICLE_URL = "posts/{slug}/"' in config
    assert "FEED_MAX_ITEMS = 20" in config
    assert 'THEME = "theme"' in config
    assert '"search.html": "search/index.html"' in config
    assert "_LazyImages" in config           # body images load lazily
    assert 'AVATAR = "theme/img/avatar.png"' in config
    assert (site / "theme/static/img/avatar.png").read_bytes() == b"IMG"
    assert 'FAVICON = "theme/favicon.svg"' in config
    assert (site / "theme/static/favicon.svg").read_bytes() == b"SVG"
    assert 'rel="icon"' in (site / "theme/templates/base.html").read_text()
    for tpl in ("base", "index", "article", "tag", "tags", "author",
                "authors", "archives", "search", "macros", "pagination"):
        assert (site / f"theme/templates/{tpl}.html").exists(), tpl
    assert "card-grid" in (site / "theme/static/css/style.css").read_text()
    assert (site / "redirects.csv").exists()
    # the embedded plugin turns redirects.csv into redirect stubs and
    # rewrites body images into responsive webp variants
    assert "PLUGINS = [_SitePlugins]" in config
    assert "signals.finalized" in config and "redirects.csv" in config
    assert "_optimize_article_images" in config
    assert "VARIANT_WIDTHS = (480, 736, 1104)" in config


def test_theme_picker_and_dark_scheme(archive):
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    css = (hugo_site / "static/css/style.css").read_text()
    # dark palette under both routes: an explicit picker choice pins
    # data-theme; with none stored, the system scheme decides
    assert ':root[data-theme="dark"]' in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root:not([data-theme="light"])' in css
    assert ".theme-picker" in css
    assert (pelican_site / "theme/static/css/style.css").read_text() == css
    for base in (hugo_site / "layouts/_default/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        for choice in ("light", "system", "dark"):
            assert f'data-set-theme="{choice}"' in text, base
        # the stored choice applies before the stylesheet loads, so a
        # page cannot flash the wrong scheme
        assert text.index("localStorage.getItem") < text.index("stylesheet")
    # redirect stubs load no stylesheet, so they must paint the palette
    # themselves -- following a redirect must not flash white in dark mode
    for stub_source in ((hugo_site / "layouts/alias.html").read_text(),
                        (pelican_site / "pelicanconf.py").read_text()):
        assert "prefers-color-scheme: dark" in stub_source
        assert 'localStorage.getItem("theme")' in stub_source
    # the snippets embed verbatim, so they must carry no template syntax
    # the other engine would mangle
    for name in ("theme-init", "theme-picker", "term-sort", "announcement",
                 "nav-current", "image-zoom", "feed-icon"):
        snippet = sites.template_text(f"shared/{name}.html")
        assert "{{" not in snippet and "{%" not in snippet
    # without an avatar or announcement the config must still be valid
    # Python (json.dumps(None) would emit a NameError-raising `null`)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "AVATAR = None" in config
    assert "FAVICON = None" in config
    assert "ANNOUNCEMENT = None" in config


def test_announcement_banner(archive):
    banner_url = "https://jupyter.org/assets/banner.html"
    cfg = json.loads((archive / "site.json").read_text())
    cfg["announcement"] = banner_url
    (archive / "site.json").write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    assert f'announcement = "{banner_url}"' in (hugo_site / "hugo.toml").read_text()
    assert f'ANNOUNCEMENT = "{banner_url}"' in (pelican_site / "pelicanconf.py").read_text()
    for base in (hugo_site / "layouts/_default/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        # the banner div sits above the header, emitted only when an
        # announcement is configured; a URL source is fetched
        # client-side, anything else is the banner HTML itself
        assert 'class="announcement"' in text and "data-source" in text, base
        assert text.index('class="announcement"') < text.index("site-header"), base
        assert "fetch(source)" in text, base
        # dismissal is remembered keyed by the banner's content, so a
        # changed announcement clears it and shows again
        assert 'localStorage.setItem("announcement-dismissed", html)' in text, base
        assert 'localStorage.getItem("announcement-dismissed") === html' in text, base
        # the last fetch's content is cached and rendered synchronously,
        # so navigating the site doesn't shift the layout when the
        # banner arrives
        assert 'localStorage.setItem("announcement-cache"' in text, base
        assert text.index("announcement-cache") < text.index("fetch(source)"), base
    css = (hugo_site / "static/css/style.css").read_text()
    assert ".announcement" in css and ".announcement-close" in css


def test_nav_current_highlight(archive):
    # the nav link whose path prefixes the current page's gets
    # aria-current, which the stylesheet paints in the accent
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    for base in (hugo_site / "layouts/_default/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        assert 'setAttribute("aria-current", "page")' in text, base
        # the script follows the nav it marks
        assert text.index("</header>") < text.index("aria-current"), base
    assert 'a[aria-current="page"]' in (hugo_site / "static/css/style.css").read_text()


def test_term_sort_control(archive):
    # the tag/author chip indexes carry the name/count sort control,
    # placed above the chip list it reorders
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    for page in (hugo_site / "layouts/_default/terms.html",
                 pelican_site / "theme/templates/tags.html",
                 pelican_site / "theme/templates/authors.html"):
        text = page.read_text()
        for order in ("name", "count"):
            assert f'data-sort="{order}"' in text, page
        assert text.index("term-sort") < text.index("term-list"), page
    css = (hugo_site / "static/css/style.css").read_text()
    assert ".term-sort" in css
    assert css == (pelican_site / "theme/static/css/style.css").read_text()


def test_image_zoom(archive):
    # post pages carry the click-to-zoom modal, on both engines
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    for page in (hugo_site / "layouts/_default/single.html",
                 pelican_site / "theme/templates/article.html"):
        text = page.read_text()
        assert '<dialog class="zoom-dialog"' in text, page
        # the dialog follows the article whose images it zooms
        assert text.index("</article>") < text.index("zoom-dialog"), page
        # zoom to the src attribute, never currentSrc: src is the
        # full-size original, currentSrc the smaller srcset variant
        assert "full.src = img.src" in text, page
        assert "currentSrc" not in text, page
        # only images holding more detail than the column shows are
        # marked, and the width attribute -- not naturalWidth, which
        # srcset density-corrects -- is what the original measures
        assert 'parseInt(img.getAttribute("width"), 10)' in text, page
        # keyboard reachable, and a linked image keeps its link
        assert 'img.closest("a")' in text, page
        assert "img.tabIndex = 0" in text, page
    css = (hugo_site / "static/css/style.css").read_text()
    assert "img.zoomable { cursor: zoom-in; }" in css
    assert ".zoom-dialog::backdrop" in css
    assert "prefers-reduced-motion" in css
    assert css == (pelican_site / "theme/static/css/style.css").read_text()


def test_build_output_survives_regeneration(archive):
    for module, kept in ((hugo, "public"), (pelican, "output")):
        site = module.build_site(archive)
        (site / kept).mkdir()
        (site / kept / "index.html").write_text("built")
        module.build_site(archive)
        assert (site / kept / "index.html").read_text() == "built"


def line_art(w, h):
    """Flat-colored art like the charts and screenshots most of the
    archive's PNGs are: few colors, long runs of identical pixels."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(im)
    for i in range(h // 40):
        draw.rectangle((20, 20 + i * 40, 20 + (i + 1) * 30, 44 + i * 40),
                       fill="#1f77b4")
        draw.text((26, 24 + i * 40), f"row {i} of the chart", fill="black")
    return im


def make_image_post(tmp_path, still_bytes=None, gif_bytes=None):
    """An archive whose one post carries real images: a large noisy PNG
    (a photograph, in PNG clothing), a small noisy PNG, a wide line-art
    PNG (a chart), and junk bytes with a .png name (unreadable; must
    pass through)."""
    import os

    from PIL import Image

    manifest = {}
    images = ["images/big.png", "images/small.png", "images/chart.png",
              "images/junk.png"]
    if gif_bytes:
        images.append("images/anim.gif")
    make_post(tmp_path, manifest, "picture-post", "ccc333ccc333",
              "2022-06-01T10:00:00Z",
              "![big](images/big.png)\n\n![chart](images/chart.png)\n",
              images=images)
    img_dir = tmp_path / "posts/2022-06-01-picture-post/images"
    img_dir.mkdir()

    def noise(w, h):
        return Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))

    noise(2000, 1200).save(img_dir / "big.png")
    noise(200, 100).save(img_dir / "small.png")
    line_art(2400, 900).save(img_dir / "chart.png")
    (img_dir / "junk.png").write_bytes(b"PNG")
    if gif_bytes:
        frames = [noise(1600, 1200).convert("P") for _ in range(3)]
        frames[0].save(img_dir / "anim.gif", save_all=True,
                       append_images=frames[1:], duration=100, loop=0)
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    (tmp_path / "site.json").write_text(json.dumps({"title": "Pics"}))
    return img_dir


def test_photographs_capped_into_display_copies(tmp_path):
    from PIL import Image

    src = make_image_post(tmp_path)
    site = hugo.build_site(tmp_path)
    placed = site / "content/posts/picture-post/images"
    # a photograph is capped and encoded lossily, whatever it arrived as
    with Image.open(placed / "big.jpg") as im:
        assert max(im.size) == 1600 and im.format == "JPEG"
    assert not (placed / "big.png").exists()
    assert (placed / "big.jpg").stat().st_size < (src / "big.png").stat().st_size
    assert (placed / "small.jpg").stat().st_size < (src / "small.png").stat().st_size
    # the page follows the images it actually got
    page = (site / "content/posts/picture-post/index.md").read_text()
    assert "![big](images/big.jpg)" in page
    # an unreadable file passes through as a hard link
    assert (placed / "junk.png").read_bytes() == b"PNG"
    assert (placed / "junk.png").stat().st_ino == (src / "junk.png").stat().st_ino
    # the display copy is built once and shared across exporters
    pelican_site = pelican.build_site(tmp_path)
    assert (pelican_site / "content/posts/picture-post/images/big.jpg"
            ).stat().st_ino == (placed / "big.jpg").stat().st_ino
    # caps are configurable, 0 leaves stills alone entirely
    (tmp_path / "site.json").write_text(json.dumps(
        {"title": "Pics", "images": {"still_max_edge": 0}}))
    site = hugo.build_site(tmp_path)
    assert (placed / "big.png").stat().st_ino == (src / "big.png").stat().st_ino


def test_line_art_keeps_every_pixel(tmp_path):
    """Charts and screenshots are re-encoded losslessly at their own
    resolution: the small text in them does not survive a downscale, and
    flat color costs little to keep."""
    from PIL import Image, ImageChops

    src = make_image_post(tmp_path)
    site = hugo.build_site(tmp_path)
    placed = site / "content/posts/picture-post/images"
    assert not (placed / "chart.png").exists()
    with Image.open(src / "chart.png") as before, \
            Image.open(placed / "chart.webp") as after:
        assert after.size == before.size          # past the 1600 px cap
        assert not ImageChops.difference(before.convert("RGB"),
                                         after.convert("RGB")).getbbox()
    assert (placed / "chart.webp").stat().st_size < (
        src / "chart.png").stat().st_size
    page = (site / "content/posts/picture-post/index.md").read_text()
    assert "![chart](images/chart.webp)" in page


def test_line_art_classifier(tmp_path):
    import os

    from PIL import Image

    assert sites.is_line_art(line_art(600, 400))
    noise = Image.frombytes("RGB", (300, 200), os.urandom(300 * 200 * 3))
    assert not sites.is_line_art(noise)
    # a photograph on a flat background is still a photograph
    inset = Image.new("RGB", (600, 400), "white")
    inset.paste(noise, (150, 100))
    assert not sites.is_line_art(inset)


@pytest.mark.skipif(not __import__("shutil").which("gifsicle"),
                    reason="gifsicle not installed")
def test_animated_gifs_capped_via_gifsicle(tmp_path):
    from PIL import Image

    src = make_image_post(tmp_path, gif_bytes=True)
    site = hugo.build_site(tmp_path)
    placed = site / "content/posts/picture-post/images/anim.gif"
    with Image.open(placed) as im:
        assert max(im.size) == 1104 and im.n_frames == 3
    assert placed.stat().st_size < (src / "anim.gif").stat().st_size
