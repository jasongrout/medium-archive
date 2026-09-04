"""The hugo and pelican steps: posts/ + posts.json -> a site."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from medium_archive import hugo, pelican, sites

BASE = "https://blog.example.com"


def make_post(out: Path, manifest: dict, slug: str, mid: str, date: str,
              body: str, **extra) -> str:
    url = f"{BASE}/{slug}-{mid}"
    d = f"posts/{date[:10]}-{slug}"
    post = {"title": slug.replace("-", " ").title(), "date": date,
            "authors": [{"name": "Ada Lovelace", "url": "https://medium.com/@ada"}],
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
    assert front["tags"] == ["example"] and front["authors"] == ["ada-lovelace"]
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


FIGURE_BODY = ("<figure>\n\n![Alt text](images/001-fig.gif)\n\n"
               "<figcaption>\n\nThe caption, with a "
               "[link](https://example.com).\n\n</figcaption>\n\n"
               "</figure>\n")


def captioned_archive(archive):
    manifest = json.loads((archive / "posts.json").read_text())
    make_post(archive, manifest, "captioned-post", "ccc333ccc333",
              "2022-06-01T10:00:00Z", FIGURE_BODY,
              images=["images/001-fig.gif"])
    d = archive / "posts/2022-06-01-captioned-post"
    (d / "images").mkdir()
    (d / "images" / "001-fig.gif").write_bytes(b"GIF")
    (archive / "posts.json").write_text(json.dumps(manifest))
    return archive


def test_hugo_page_keeps_caption_in_its_figure(archive):
    site = hugo.build_site(captioned_archive(archive))
    # the shell becomes a call to the shipped figure shortcode, the
    # caption as inner content so its Markdown still renders
    page = (site / "content/posts/captioned-post/index.md").read_text()
    assert ('{{< figure src="images/001-fig.gif" alt="Alt text" >}}'
            "The caption, with a [link](https://example.com)."
            "{{< /figure >}}") in page
    # the shortcode the figure calls resolve to, and the image partial
    # it shares with the render hook
    assert (site / "layouts/shortcodes/figure.html").exists()
    assert (site / "layouts/partials/post-image.html").exists()


def test_pelican_page_renders_the_figure_shell_as_one_block(archive):
    site = pelican.build_site(captioned_archive(archive))
    page = (site / "content/posts/captioned-post/index.md").read_text()
    assert ('<figure markdown="span">\n'
            '<img alt="Alt text" src="{attach}images/001-fig.gif" '
            'loading="lazy">\n'
            '<figcaption markdown="span">The caption, with a '
            "[link](https://example.com).</figcaption>\n"
            "</figure>") in page
    # python-markdown's md_in_html (span mode) renders the caption's
    # Markdown inline: no <p> wrappers around the img or the caption,
    # matching the markup Medium serves
    import markdown as md_mod
    body = page.split("\n\n", 1)[1]
    html = md_mod.markdown(body, extensions=["extra"])
    assert "<p><img" not in html and "<figcaption><p>" not in html
    assert ('<figcaption>The caption, with a '
            '<a href="https://example.com">link</a>.</figcaption>') in html


def test_link_wrapped_figures_keep_their_link():
    shell = ("<figure>\n\n[![Alt](images/a.png)](https://demo.example)\n\n"
             "<figcaption>\n\nCap.\n\n</figcaption>\n\n</figure>")
    assert hugo.figure_shortcodes(shell) == (
        '{{< figure src="images/a.png" alt="Alt" '
        'link="https://demo.example" >}}Cap.{{< /figure >}}')
    assert pelican.figure_blocks(shell) == (
        '<figure markdown="span">\n'
        '<a href="https://demo.example">'
        '<img alt="Alt" src="images/a.png" loading="lazy"></a>\n'
        '<figcaption markdown="span">Cap.</figcaption>\n</figure>')


def test_non_image_figure_shells_stay_raw_html():
    shell = ("<figure>\n\n[embed: https://u](https://u)\n\n<figcaption>\n\n"
             "Cap.\n\n</figcaption>\n\n</figure>")
    # hugo leaves them to Goldmark's unsafe renderer as they are;
    # pelican opts the tag lines into markdown so the content renders
    assert hugo.figure_shortcodes(shell) == shell
    assert pelican.figure_blocks(shell) == shell.replace(
        "<figure>", '<figure markdown="1">').replace(
        "<figcaption>", '<figcaption markdown="1">')


def test_hugo_site_config_and_front_matter(archive, capsys):
    (archive / "logo.png").write_bytes(b"IMG")
    (archive / "site.json").write_text(json.dumps(
        {"title": "Example Blog", "favicon": "missing.ico",
         "hugo": {"avatar": "logo.png", "params": {"motto": "hello"}}}))
    site = hugo.build_site(archive)
    config = (site / "hugo.toml").read_text()
    assert "theme" not in config                # always the built-in theme
    assert 'motto = "hello"' in config          # user params merge last
    assert 'avatar = "img/avatar.png"' in config
    assert (site / "static/img/avatar.png").read_bytes() == b"IMG"
    # an asset site.json names but the archive lacks is skipped, noted
    assert "favicon" not in config
    assert "favicon not found, skipped" in capsys.readouterr().err
    assert (site / "layouts/_default/baseof.html").exists()
    assert (site / "content/search.md").exists()
    assert (site / "content/archives.md").exists()
    front = json.loads((site / "content/posts/second-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    # the baked card cover doubles as og:image; junk bytes defeat Pillow
    # and are copied in unchanged
    assert front["cover"] == "images/cover.jpg"
    assert "images" not in front
    assert (site / "content/posts/second-post/images/cover.jpg"
            ).read_bytes() == b"PNG"
    assert front["authors"] == ["ada-lovelace"]
    assert "author" not in front                # the taxonomy is the byline


def test_cover_prefers_stills_falls_back_to_gifs_skips_huge(tmp_path):
    import struct
    images = tmp_path / "images"
    images.mkdir()
    png = lambda w, h: (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                        + struct.pack(">II", w, h) + b"\x00" * 8)
    gif = lambda w, h: b"GIF89a" + struct.pack("<HH", w, h)
    (images / "big.png").write_bytes(png(7532, 3464))
    (images / "small.png").write_bytes(png(800, 600))
    (images / "anim.gif").write_bytes(gif(400, 300))
    (images / "huge.gif").write_bytes(gif(5000, 4000))
    assert sites.image_size(images / "big.png") == (7532, 3464)
    assert sites.image_size(images / "anim.gif") == (400, 300)
    # a still anywhere in the post beats a gif ahead of it
    post = {"images": ["images/anim.gif", "images/big.png", "images/small.png"]}
    assert sites.pick_cover(post, tmp_path) == "images/small.png"
    # gif-only posts get their first sane-size gif (its first frame bakes)
    assert sites.pick_cover({"images": ["images/anim.gif"]}, tmp_path) == "images/anim.gif"
    assert sites.pick_cover({"images": ["images/huge.gif", "images/anim.gif"]},
                            tmp_path) == "images/anim.gif"
    assert sites.pick_cover({"images": ["images/huge.gif"]}, tmp_path) is None
    assert sites.pick_cover({"images": ["images/missing.png"]}, tmp_path) is None


def test_cover_bakes_first_gif_frame(tmp_path):
    from PIL import Image
    frames = [Image.new("RGB", (400, 225), c) for c in ("red", "blue")]
    src = tmp_path / "anim.gif"
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=100)
    dst = tmp_path / "cover.jpg"
    assert sites.make_cover_thumbnail(src, dst)
    with Image.open(dst) as im:
        assert im.format == "JPEG" and im.size == sites.COVER_SIZE
        assert im.getpixel((320, 180))[0] > 200        # frame one, red


def test_cover_skips_svgs_and_untyped_images(tmp_path):
    """The baked cover is served as cover.jpg and Hugo's card template
    rasterizes it, so an svg badge as the cover aborts the whole hugo
    build ("image: unknown format"): only raster formats qualify. A
    .bin (bytes convert could not type) is no cover either."""
    images = tmp_path / "images"
    images.mkdir()
    (images / "badge.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    (images / "blob.bin").write_bytes(b"?")
    (images / "photo.JPG").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
    post = {"images": ["images/badge.svg", "images/blob.bin", "images/photo.JPG"]}
    assert sites.pick_cover(post, tmp_path) == "images/photo.JPG"
    assert sites.pick_cover({"images": post["images"][:-1]}, tmp_path) is None


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
    # one data file names every tag; the content adapter beside the
    # posts turns it into the term pages (kind term, path = slug)
    names = hugo_site / "data/tags.json"
    assert json.loads(names.read_text()) == {"example": "Example Tag"}
    adapter = (hugo_site / "content/tags/_content.gotmpl").read_text()
    assert "hugo.Data.tags" in adapter and '"kind" "term"' in adapter
    assert not (hugo_site / "content/tags/example").exists()

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
    names = json.loads((site / "data/tags.json").read_text())
    assert names == {"open-science": "open science"}


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
    assert "Authors: ada-lovelace" in head
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
        for choice in ("sans", "system-ui", "inter", "source-sans",
                       "source-serif", "atkinson", "nunito-sans",
                       "ibm-plex-sans", "ibm-plex-serif"):
            assert f'<option value="{choice}"' in text, base
        # every family the picker offers beyond the launch stack and the
        # platform's own is a webfont: unlinked, those choices degrade to
        # their fallbacks silently, looking like a styling bug rather than
        # a missing file
        for family in ("Atkinson+Hyperlegible", "Atkinson+Hyperlegible+Mono",
                       "IBM+Plex+Mono", "IBM+Plex+Sans", "IBM+Plex+Serif",
                       "Inter", "Nunito+Sans", "Source+Serif+Pro",
                       "Source+Sans+Pro", "Source+Code+Pro"):
            assert f"family={family}" in text, (base, family)
        # the stored choices apply before the stylesheet loads, so a
        # page cannot flash the wrong scheme or font
        assert text.index("localStorage.getItem") < text.index("stylesheet")
        assert text.index('localStorage.getItem("font")') < text.index("stylesheet")
    # redirect stubs load no stylesheet, so they must paint the palette
    # themselves -- following a redirect must not flash white in dark mode
    for stub_source in ((hugo_site / "layouts/alias.html").read_text(),
                        (pelican_site / "pelicanconf.py").read_text()):
        assert "prefers-color-scheme: dark" in stub_source
        assert 'localStorage.getItem("theme")' in stub_source
    # the snippets embed verbatim, so they must carry no template syntax
    # the other engine would mangle
    for name in ("theme-init", "theme-picker", "font-init", "font-picker",
                 "term-sort", "announcement",
                 "nav-current", "image-zoom", "code-copy", "feed-icon",
                 "share-icons"):
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


def test_code_copy(archive):
    # post pages carry the code-block copy button, on both engines
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    for page in (hugo_site / "layouts/_default/single.html",
                 pelican_site / "theme/templates/article.html"):
        text = page.read_text()
        assert '<template class="code-copy-template">' in text, page
        # the button follows the article whose blocks it serves, and is
        # added only where the clipboard API can honour it
        assert text.index("</article>") < text.index("code-copy-template"), page
        assert "navigator.clipboard.writeText" in text, page
        # every pre in the article, whatever the engine wrapped it in,
        # gets a positioning box of its own and a cloned button
        assert 'article.querySelectorAll("pre")' in text, page
        assert 'block.className = "code-block"' in text, page
        assert "template.content.firstElementChild.cloneNode(true)" in text, page
        # the icons swap by attribute: an SVG element has no `hidden`
        # property to set, so assigning one would change nothing
        assert 'icon.toggleAttribute("hidden"' in text, page
        assert "icon.hidden" not in text, page
        # the copied text is the block's, without its trailing newline
        assert 'pre.textContent.replace(/\\n$/, "")' in text, page
        # a screen reader hears the copy through the live region
        assert 'role="status"' in text, page
        assert 'announce("Copied to clipboard")' in text, page
    # hugo highlights by class, never Chroma's inlined Monokai, which
    # paints a dark block on the light page; the theme colours the
    # tokens on the class names Pygments and Chroma share, per palette
    config = (hugo_site / "hugo.toml").read_text()
    assert "[markup.highlight]\nnoClasses = false" in config
    css = (hugo_site / "static/css/style.css").read_text()
    assert css.count("--syn-keyword:") == 3      # light, and dark twice
    assert ".post .highlight .k," in css
    assert ".code-block { position: relative; }" in css
    assert ".code-copy { position: absolute;" in css
    assert ".code-copy:focus-visible" in css
    # hidden until the block is hovered or the button reached by
    # keyboard, and always shown where there is no hover
    assert ".code-block:hover .code-copy, .code-copy:focus-visible { opacity: 1; }" in css
    assert "@media (hover: none) { .code-copy { opacity: 1; } }" in css
    assert css == (pelican_site / "theme/static/css/style.css").read_text()


def _contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two #rrggbb colours."""
    def luminance(hex_colour):
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_syntax_colours_contrast():
    """The syntax colours are Primer's, an AA scheme: every token clears
    WCAG AA (4.5:1) on its palette's code background, except the light
    comment grey, GitHub's own shortfall, which is held where it is."""
    import re
    # template_text splices the dark palette into card.css twice, so
    # the light set is what comes before the first splice point
    css = sites.template_text("shared/card.css")
    light = css.split(':root[data-theme="dark"]')[0]
    dark = sites.template_text("shared/dark-palette.css")
    for name, palette in (("light", light), ("dark", dark)):
        code_bg = re.search(r"--code-bg: (#[0-9a-f]{6})", palette).group(1)
        colours = re.findall(r"--syn-([a-z]+): (#[0-9a-f]{6})", palette)
        assert len(colours) == 6, name
        for token, colour in colours:
            ratio = _contrast(colour, code_bg)
            floor = 4.2 if (name, token) == ("light", "comment") else 4.5
            assert ratio >= floor, (name, token, colour, round(ratio, 2))


def test_post_share_links(archive):
    """A post carries the five share links twice -- under the byline and
    at the foot -- from one definition per engine, each mark coming from
    the shared sprite."""
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    # each engine names the same three values, so the bars keep one shape
    for bar, url, title, text in (
            (hugo_site / "layouts/partials/share.html", "{{ .Permalink }}",
             "{{ .Title }}", "{{ $text }}"),
            (pelican_site / "theme/templates/macros.html", "{{ enc_url }}",
             "{{ enc_title }}", "{{ enc_text }}")):
        source = bar.read_text()
        for network in ("linkedin", "facebook", "bluesky", "mastodon", "email"):
            assert f'<use href="#share-{network}"></use>' in source, bar
        assert '<div class="post-share" data-pagefind-ignore>' in source, bar
        # each network's own documented share URL: the page address alone
        # for LinkedIn and Facebook, which read the rest off the Open
        # Graph tags; a prefilled text for Bluesky and Mastodon. A toot
        # goes to the reader's own server, which the page cannot know,
        # so Mastodon's link is to the network's share sheet, which asks
        # for the server; the text rides in the fragment, as its own
        # instructions generate it, out of server logs and referrers
        for target in (f"linkedin.com/sharing/share-offsite/?url={url}",
                       f"facebook.com/sharer/sharer.php?u={url}",
                       f"bsky.app/intent/compose?text={text}",
                       f"share.joinmastodon.org/#text={text}",
                       f"mailto:?subject={title}&amp;body={url}"):
            assert target in source, bar
        assert "data-share-text" not in source, bar

    for page, call in ((hugo_site / "layouts/_default/single.html",
                        '{{ partial "share.html" . }}'),
                       (pelican_site / "theme/templates/article.html",
                        "{{ share(post_url, post_title) }}")):
        source = page.read_text()
        # once under the byline and once after the body, both inside the
        # post card, and the sprite they draw from ahead of the first
        head, foot = source.index(call), source.rindex(call)
        assert head != foot, page
        assert source.index("share-sprite") < head, page
        assert source.index("post-meta") < head < source.index("</article>"), page
        assert foot < source.index("</article>"), page
        # the bar is plain links: the Mastodon prompt script is gone
        # (the sprite's #share-mastodon symbol is still on the page)
        assert 'querySelectorAll(".share-mastodon")' not in source, page
        assert "mastodon-host" not in source, page

    # hugo escapes each value for its URL context on its own; pelican's
    # Jinja does not, so the theme spells the encoding out -- on each
    # value, which is what this pins: the check must fail when one of
    # them loses its encoding, not merely when the file has none left
    lines = {line.split()[2]: line for line
             in (pelican_site / "theme/templates/macros.html").read_text()
             .splitlines() if line.startswith("{% set ")}
    for name in ("enc_url", "enc_title", "enc_text"):
        assert lines[name].endswith('|urlencode|replace("/", "%2F") %}'), name

    css = (hugo_site / "static/css/style.css").read_text()
    assert ".share-sprite { display: none; }" in css
    assert ".share-icon { width: 1.05rem" in css
    # the marks are the networks' logos: a hover may deepen them, but
    # recoloring them to this site's accent is against most of those
    # networks' brand guidelines. The ring around a mark is the site's
    # own, so only the text colour (the mark's, via currentColor) is
    # held off the accent
    hover = next(line for line in css.splitlines()
                 if line.startswith(".share-link:hover"))
    colour = re.search(r"[{;]\s*color: ([^;]+);", hover).group(1)
    assert colour != "var(--accent)", hover
    assert css == (pelican_site / "theme/static/css/style.css").read_text()


def test_share_targets_get_the_open_graph_tags_they_render_from(archive):
    """LinkedIn's and Facebook's share URLs carry only the page address:
    everything their share box shows comes from the page's Open Graph
    tags, so the share links are worth no more than these."""
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    for head in (hugo_site / "layouts/_default/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        source = head.read_text()
        for prop in ("og:site_name", "og:type", "og:title", "og:url",
                     "og:description", "og:image", "article:published_time"):
            assert f'property="{prop}"' in source, (head, prop)
        assert 'rel="canonical"' in source, head
        # a post with no cover has no image to promise
        assert "summary_large_image" in source and "summary" in source, head


def test_a_title_is_plain_text_not_html(archive):
    """Pelican renders only FORMATTED_FIELDS (summary) as markdown, so a
    post's title reaches the theme as the plain text of its Title:
    header. Stripping tags from it would delete any run shaped like one
    -- "Using <script> tags safely" -> "Using tags safely" -- rather
    than escape it, losing what hugo keeps."""
    pelican_site = pelican.build_site(archive)
    article = (pelican_site / "theme/templates/article.html").read_text()
    assert "{% set post_title = article.title %}" in article
    assert "article.title|striptags" not in article
    # the page name the head renders into <title> and og:title is the
    # template's name block, and the article's is the title as it is
    assert "{% block name %}{{ article.title }}{% endblock %}" in article

    base = (pelican_site / "theme/templates/base.html").read_text()
    og_title = next(line for line in base.splitlines()
                    if 'property="og:title"' in line)
    assert 'content="{{ page_title }}' in og_title, og_title
    assert "{% set page_title = self.name() %}" in base
    assert "<title>{% block name %}{{ SITENAME }}{% endblock %}" in base
    assert "striptags" not in og_title, og_title
    # the summary, though, really is HTML -- pelican formats that one,
    # and an auto-generated summary is a fragment of the body -- so it
    # keeps the stripping, here as in the card macro
    og_desc = next(line for line in base.splitlines()
                   if 'property="og:description"' in line)
    assert "article.summary|striptags|e" in og_desc, og_desc


def test_pelican_escapes_by_default(archive):
    """Pelican's own default JINJA_ENVIRONMENT sets no autoescape and
    jinja's default is off, so a theme emits every {{ }} raw -- which
    makes a post title reading `<script>...` a running script on every
    page that renders it, and titles, tag names and authors all come
    from the archived publication. The generated config turns escaping
    on; only the rendered body is marked safe."""
    site = pelican.build_site(archive)
    config = (site / "pelicanconf.py").read_text()
    assert '"autoescape": True' in config
    # the setting replaces pelican's defaults rather than merging, so
    # the rest of them have to be restated with it
    for key in ('"trim_blocks": True', '"lstrip_blocks": True',
                '"extensions": []'):
        assert key in config, key
    # article.content is the one genuinely-HTML value in the theme
    templates = site / "theme/templates"
    safe = [(f.name, line.strip()) for f in sorted(templates.glob("*.html"))
            for line in f.read_text().splitlines() if "|safe" in line]
    assert safe == [("article.html", "{{ article.content|safe }}")], safe


def test_missing_base_url_is_not_silent(tmp_path, capsys):
    """Every absolute link -- feeds, redirect stubs, og:url, the share
    links -- is built from base_url, and a share link with the wrong one
    fails outright rather than degrading, so an unset base_url has to be
    said out loud at build time."""
    manifest = {}
    make_post(tmp_path, manifest, "post", "aaa111aaa111",
              "2020-01-05T10:00:00Z", "Hello.\n")
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    (tmp_path / "site.json").write_text(json.dumps({"title": "Example"}))
    sites.load_site_inputs(tmp_path)
    assert "no base_url" in capsys.readouterr().err
    # and stays quiet once it is set
    (tmp_path / "site.json").write_text(json.dumps(
        {"title": "Example", "base_url": "https://blog.example.org"}))
    sites.load_site_inputs(tmp_path)
    assert "base_url" not in capsys.readouterr().err


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


def test_multiple_authors_reach_both_sites(tmp_path):
    """A post's authors list, of any length, is the byline everywhere:
    hugo's authors taxonomy (front matter slugs only; the feed reads the
    same list, the card and post link each term's listing page),
    pelican's Authors: header, which it splits into
    Author objects -- on commas, so a name holding one flips the
    separator to semicolons."""
    manifest = {}
    make_post(tmp_path, manifest, "duet", "abc123abc123", "2020-01-01T00:00:00Z",
              "Hi.\n", authors=[{"name": "Ada Lovelace", "url": "https://medium.com/@ada"},
                                {"name": "yuvipanda", "url": None}])
    make_post(tmp_path, manifest, "trio", "abc123abc124", "2020-01-02T00:00:00Z",
              "Hi.\n", authors=[{"name": "Project Jupyter, Inc.", "url": None},
                                {"name": "Min RK", "url": None}])
    make_post(tmp_path, manifest, "solo", "abc123abc125", "2020-01-03T00:00:00Z",
              "Hi.\n", authors=[])
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    (tmp_path / "site.json").write_text(json.dumps({"title": "T"}))

    site = hugo.build_site(tmp_path)
    front = lambda stem: json.loads(
        (site / f"content/posts/{stem}/index.md").read_text().split("\n\n", 1)[0])
    assert front("duet")["authors"] == ["ada-lovelace", "yuvipanda"]
    assert "author" not in front("duet")
    assert "authors" not in front("solo")
    assert "capitalizeListTitles = false" in (site / "hugo.toml").read_text()
    text = (site / "layouts/_default/rss.xml").read_text()
    assert ".Params.authors" in text and ".Params.author " not in text
    # the card's byline links each author to their listing, like the
    # post page's, so both walk the taxonomy terms rather than the names
    for layout in ("layouts/partials/card.html", "layouts/_default/single.html"):
        text = (site / layout).read_text()
        assert '.GetTerms "authors"' in text and ".Params.author" not in text, layout
        assert 'href="{{ .RelPermalink }}">{{ .LinkTitle }}</a>' in text, layout

    site = pelican.build_site(tmp_path)
    head = lambda stem: (site / f"content/posts/{stem}/index.md").read_text().split("\n\n", 1)[0]
    assert "Authors: ada-lovelace, yuvipanda\n" in head("duet")
    # a slug holds no comma, so the comma split is unambiguous even for
    # a byline like "Project Jupyter, Inc." that once forced semicolons
    assert "Authors: project-jupyter-inc, min-rk\n" in head("trio")
    assert "Author" not in head("solo")
    for tpl in ("article", "macros", "base"):
        text = (site / f"theme/templates/{tpl}.html").read_text()
        assert "article.authors" in text and "article.author " not in text \
            and "article.author." not in text and "article.author|" not in text, tpl
    for tpl in ("article", "macros"):
        text = (site / f"theme/templates/{tpl}.html").read_text()
        assert 'for a in article.authors' in text \
            and '<a href="{{ SITEURL }}/{{ a.url }}">{{ a }}</a>' in text, tpl


def test_first_image_loads_eagerly(archive):
    """Every body image is lazy except the first, which is the one most
    likely on screen at load (WordPress's treatment of the first content
    image): the exporter names it, and each theme fetches it eagerly at
    high priority. A reference inside a code fence is not an image."""
    assert sites.first_image("text\n\n```\n![x](images/a.png)\n```\n"
                             "![y](images/b.png) and ![z](images/c.png)\n"
                             ) == "images/b.png"
    assert sites.first_image("no images\n") is None
    hugo_site = hugo.build_site(archive)
    front = json.loads((hugo_site / "content/posts/second-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    assert front["first_image"] == "images/001-pic.png"
    first = json.loads((hugo_site / "content/posts/first-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    assert "first_image" not in first
    partial = (hugo_site / "layouts/partials/post-image.html").read_text()
    assert ".page.Params.first_image" in partial
    assert 'fetchpriority="high"' in partial and 'loading="lazy"' in partial
    pelican_site = pelican.build_site(archive)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "_prioritize_first_images" in config
    assert 'fetchpriority="high"' in config


def test_crawl_files(archive):
    """What search engines ask for first: a sitemap and a robots.txt
    naming it (Hugo generates the sitemap itself; Pelican's plugin
    writes both), plus the redirect map as a `_redirects` file for hosts
    that turn one into HTTP 301s. The search page stays out of the
    index and the sitemap."""
    hugo_site = hugo.build_site(archive)
    assert "enableRobotsTXT = true" in (hugo_site / "hugo.toml").read_text()
    robots = (hugo_site / "layouts/robots.txt").read_text()
    assert '"sitemap.xml" | absURL' in robots and "Disallow: /" in robots
    search = json.loads((hugo_site / "content/search.md").read_text())
    assert search["noindex"] is True and search["sitemap"] == {"disable": True}
    redirects = (hugo_site / "static/_redirects").read_text().splitlines()
    assert "/first-post-aaa111aaa111 /posts/first-post/ 301" in redirects
    assert "/2015/06/01/first-post /posts/first-post/ 301" in redirects
    assert "/p/bbb222bbb222 /posts/second-post/ 301" in redirects
    assert all(line.endswith(" 301") for line in redirects)
    baseof = (hugo_site / "layouts/_default/baseof.html").read_text()
    assert 'name="robots"' in baseof and "max-image-preview:large" in baseof
    assert "site.Params.noindex" in baseof and ".Params.noindex" in baseof

    pelican_site = pelican.build_site(archive)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "NOINDEX = False" in config
    for name in ("_collect_sitemap", "_write_crawl_files", "sitemap.xml",
                 "robots.txt", '"_redirects"'):
        assert name in config, name
    base = (pelican_site / "theme/templates/base.html").read_text()
    assert 'name="robots"' in base and "max-image-preview:large" in base
    assert "NOINDEX or noindex" in base
    search = (pelican_site / "theme/templates/search.html").read_text()
    assert "{% set noindex = true %}" in search


def test_noindex_and_twitter_reach_both_sites(archive):
    """site.json's "noindex" keeps search engines off a deployment (a
    preview, which would otherwise be indexed as a copy of the real
    site); "twitter" credits the publication's handle on shared links."""
    cfg = json.loads((archive / "site.json").read_text())
    cfg["noindex"] = True
    cfg["twitter"] = "@example"
    (archive / "site.json").write_text(json.dumps(cfg))
    config = (hugo.build_site(archive) / "hugo.toml").read_text()
    assert "noindex = true" in config and 'twitter = "@example"' in config
    config = (pelican.build_site(archive) / "pelicanconf.py").read_text()
    assert "NOINDEX = True" in config and 'TWITTER = "@example"' in config


def test_page_metadata_search_engines_read(archive):
    """What Medium's and WordPress's pages carry beyond the share tags:
    the post's own description, its modified date, its author by name
    and by page, structured data (a schema.org BlogPosting), and a
    canonical address that is the page's own -- page 2 of a listing
    included, which both engines would otherwise call page one."""
    hugo_site = hugo.build_site(archive)
    pelican_site = pelican.build_site(archive)
    heads = {"hugo": (hugo_site / "layouts/_default/baseof.html").read_text(),
             "pelican": (pelican_site / "theme/templates/base.html").read_text()}
    for engine, head in heads.items():
        for prop in ("article:modified_time", "article:author"):
            assert f'property="{prop}"' in head, (engine, prop)
        assert 'name="author"' in head, engine
        assert 'name="twitter:site"' in head, engine
    # structured data: one block, a BlogPosting, with the fields that
    # matter, and every value escaped for a <script>
    ld = (hugo_site / "layouts/partials/jsonld.html").read_text()
    assert 'type="application/ld+json"' in ld
    pelican_ld = (pelican_site / "theme/templates/jsonld.html").read_text()
    assert 'type="application/ld+json"' in pelican_ld
    for key in ("BlogPosting", "headline", "datePublished", "dateModified",
                "author", "publisher", "mainEntityOfPage"):
        assert key in ld, key
    assert "jsonify | safeJS" in ld
    assert 'partial "jsonld.html"' in heads["hugo"]
    for key in ("BlogPosting", "headline", "datePublished", "dateModified",
                "author", "publisher", "mainEntityOfPage"):
        assert key in pelican_ld, key
    assert "|tojson }}" in pelican_ld
    assert '{% include "jsonld.html" %}' in heads["pelican"]
    # a post page's description is the post's, not the site's
    desc = next(line for line in heads["pelican"].splitlines()
                if 'name="description"' in line)
    assert "article.summary|striptags|e" in desc, desc
    # the address of the page being rendered: the listing's paginator
    # in hugo (one partial for the head and the list templates), the
    # output file in pelican
    assert 'partial "paginator.html"' in heads["hugo"]
    assert '<link rel="canonical" href="{{ or .Params.canonical $url }}">' in heads["hugo"]
    for layout in ("index.html", "_default/list.html"):
        assert 'partial "paginator.html"' in (hugo_site / "layouts" / layout).read_text()
    assert "output_file" in heads["pelican"]
    assert ('<link rel="canonical" href="{{ article.canonical if article '
            'and article.canonical else page_url }}">') in heads["pelican"]


def _graph_source(engine_site, engine):
    if engine == "hugo":
        return (engine_site / "layouts/partials/jsonld.html").read_text()
    return (engine_site / "theme/templates/jsonld.html").read_text()


def test_external_canonical_reaches_the_head(archive):
    """A post that declared a canonical on another host (Medium's
    "originally published at") is a copy of that page and says so, as a
    WordPress per-post canonical does; one naming the publication's own
    host (a Ghost-era slug) is the same post and is ignored. Every
    other page is its own canonical: the archive is the posts' home,
    and the Medium copy is never named as one."""
    gist = {"canonical_url": "https://gist.github.com/ada/1",
            "original_url": f"{BASE}/x-1"}
    own = {"canonical_url": f"{BASE}/old-slug", "original_url": f"{BASE}/x-1"}
    assert sites.canonical_for(gist) == "https://gist.github.com/ada/1"
    assert sites.canonical_for(own) is None
    assert sites.canonical_for({"canonical_url": None, "original_url": f"{BASE}/x-1"}) is None

    manifest = json.loads((archive / "posts.json").read_text())
    url = next(u for u in manifest if "second-post" in u)
    manifest[url]["canonical_url"] = "https://gist.github.com/ada/1"
    (archive / "posts.json").write_text(json.dumps(manifest))
    hugo_site = hugo.build_site(archive)
    second = json.loads((hugo_site / "content/posts/second-post/index.md")
                        .read_text().split("\n\n", 1)[0])
    assert second["canonical"] == "https://gist.github.com/ada/1"
    first = json.loads((hugo_site / "content/posts/first-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    assert "canonical" not in first
    baseof = (hugo_site / "layouts/_default/baseof.html").read_text()
    assert '<link rel="canonical" href="{{ or .Params.canonical $url }}">' in baseof
    pelican_site = pelican.build_site(archive)
    page = (pelican_site / "content/posts/second-post/index.md").read_text()
    assert "Canonical: https://gist.github.com/ada/1\n" in page
    assert "Canonical:" not in (pelican_site / "content/posts/first-post/index.md").read_text()
    base = (pelican_site / "theme/templates/base.html").read_text()
    assert 'href="{{ article.canonical if article and article.canonical else page_url }}"' in base
    # neither head knows the Medium address: a post without a declared
    # canonical (first-post above) is its own
    assert "original_url" not in baseof and "original_url" not in base


def test_share_image_stands_in_for_a_missing_cover(archive):
    """site.json "share_image": the og:image of every page without a
    cover of its own, so a listing or a coverless post still shares
    with a picture; both heads declare the image's dimensions, so
    Facebook renders the large card on the first share."""
    pytest.importorskip("PIL")
    from PIL import Image
    Image.new("RGB", (1200, 630)).save(archive / "share.png")
    cfg = json.loads((archive / "site.json").read_text())
    cfg["share_image"] = "share.png"
    (archive / "site.json").write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(archive)
    assert 'share_image = "img/share.png"' in (hugo_site / "hugo.toml").read_text()
    assert (hugo_site / "assets/img/share.png").is_file()   # readable dims
    baseof = (hugo_site / "layouts/_default/baseof.html").read_text()
    assert 'with site.Params.share_image }}{{ with resources.Get .' in baseof
    for prop in ("og:image:width", "og:image:height"):
        assert f'property="{prop}"' in baseof, prop
    pelican_site = pelican.build_site(archive)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert 'SHARE_IMAGE = "theme/img/share.png"' in config
    assert "SHARE_IMAGE_SIZE = [1200, 630]" in config
    assert "COVER_SIZE = [640, 360]" in config
    assert (pelican_site / "theme/static/img/share.png").is_file()
    base = (pelican_site / "theme/templates/base.html").read_text()
    assert "SHARE_IMAGE if SHARE_IMAGE" in base
    for prop in ("og:image:width", "og:image:height"):
        assert f'property="{prop}"' in base, prop
    # unset: no fallback, no size, nothing declared
    del cfg["share_image"]
    (archive / "site.json").write_text(json.dumps(cfg))
    assert "share_image" not in (hugo.build_site(archive) / "hugo.toml").read_text()
    config = (pelican.build_site(archive) / "pelicanconf.py").read_text()
    assert "SHARE_IMAGE = None" in config and "SHARE_IMAGE_SIZE = None" in config


def test_structured_data_graph(archive):
    """Every page carries one schema.org graph, as WordPress's SEO
    plugins emit it: the Organization (publisher, with its profiles
    elsewhere as sameAs) and the WebSite (with the search page as its
    SearchAction), a BreadcrumbList placing the page, the post's
    BlogPosting with each author's Medium profile as sameAs, and an
    author page as a ProfilePage of that Person. The author profiles
    come from the bylines through one data file per site."""
    assert sites.site_profiles({"twitter": "@ex", "profiles": ["https://a.b/"]}) \
        == ["https://a.b/", "https://x.com/ex"]
    assert sites.site_profiles({}) == []
    manifest = json.loads((archive / "posts.json").read_text())
    assert sites.author_links(manifest) == {"Ada Lovelace": "https://medium.com/@ada"}
    cfg = json.loads((archive / "site.json").read_text())
    cfg["twitter"] = "@example"
    cfg["profiles"] = ["https://github.com/example"]
    (archive / "site.json").write_text(json.dumps(cfg))

    hugo_site = hugo.build_site(archive)
    assert json.loads((hugo_site / "data/authors.json").read_text()) \
        == {"Ada Lovelace": "https://medium.com/@ada"}
    config = (hugo_site / "hugo.toml").read_text()
    assert 'profiles = ["https://github.com/example", "https://x.com/example"]' in config
    # the graph on every page, not only posts
    baseof = (hugo_site / "layouts/_default/baseof.html").read_text()
    assert '{{ end }}{{ partial "jsonld.html"' in baseof
    # the tag and author indexes are titled as the nav names them, which
    # the breadcrumbs repeat
    for plural, title in (("tags", "Tags"), ("authors", "Authors")):
        assert json.loads((hugo_site / "content" / plural / "_index.md").read_text()) == {"title": title}
    pelican_site = pelican.build_site(archive)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert 'PROFILES = ["https://github.com/example", "https://x.com/example"]' in config
    assert '"Ada Lovelace": "https://medium.com/@ada"' in config
    assert '{% include "jsonld.html" %}' in (pelican_site / "theme/templates/base.html").read_text()
    for engine, site in (("hugo", hugo_site), ("pelican", pelican_site)):
        src = _graph_source(site, engine)
        for key in ("@graph", "Organization", "WebSite", "SearchAction",
                    "search/?q={search_term_string}", "BreadcrumbList",
                    "ListItem", "BlogPosting", "ProfilePage", "sameAs",
                    "isPartOf", "ImageObject", "articleSection"):
            assert key in src, (engine, key)
    assert "site.Data.authors" in _graph_source(hugo_site, "hugo")
    assert "AUTHOR_LINKS" in _graph_source(pelican_site, "pelican")


def test_related_posts(archive):
    """Each post page closes with related posts, by shared tags, then
    author, then date: Hugo's related content, configured in the
    generated config; the pelican plugin scores the same way."""
    hugo_site = hugo.build_site(archive)
    config = (hugo_site / "hugo.toml").read_text()
    assert "[related]" in config and 'name = "tags"' in config
    assert 'partial "related.html"' in (hugo_site / "layouts/_default/single.html").read_text()
    related = (hugo_site / "layouts/partials/related.html").read_text()
    assert '(where site.RegularPages "Type" "posts").Related' in related and 'partial "card.html"' in related
    assert "| first 3 }}" in related     # three, the width of the home page's card rows
    pelican_site = pelican.build_site(archive)
    assert "article.related_posts" in (pelican_site / "theme/templates/article.html").read_text()
    namespace = {}
    exec(compile((pelican_site / "pelicanconf.py").read_text(), "pelicanconf.py",
                 "exec"), namespace)
    from datetime import datetime
    day = lambda n: datetime(2020, 1, n)
    tag = lambda s: SimpleNamespace(slug=s)
    author = lambda n: SimpleNamespace(name=n)
    a = SimpleNamespace(tags=[tag("x"), tag("y")], authors=[author("Ada")], date=day(1))
    b = SimpleNamespace(tags=[tag("x")], authors=[author("Bob")], date=day(2))
    c = SimpleNamespace(tags=[tag("x"), tag("y")], authors=[author("Bob")], date=day(9))
    d = SimpleNamespace(tags=[tag("z")], authors=[author("Ada")], date=day(3))
    e = SimpleNamespace(tags=[tag("z")], authors=[author("Eve")], date=day(4))
    f = SimpleNamespace(tags=[tag("y")], authors=[author("Fay")], date=day(5))
    got = namespace["related_posts"](a, [a, b, c, d, e])
    assert got == [c, b, d]          # two tags, one tag, shared author; not e
    # three at most, the width of the home page's card rows: d's shared
    # author loses its place to f's shared tag
    assert namespace["related_posts"](a, [a, b, c, d, e, f]) == [c, b, f]
    assert namespace["related_posts"](e, [a, b, c, d, e]) == [d]
    assert namespace["related_posts"](a, [a, b, c, d, e], limit=1) == [c]


def test_alt_text_falls_back_to_the_caption():
    """An image with no alt inside a captioned figure takes the
    caption's plain text as its alt in both sites: most Medium images
    carry none, while the caption describes them exactly."""
    assert sites.caption_text("The [dashboard](https://x.y) *running*, **now**") \
        == "The dashboard running, now"
    assert sites.caption_text("a * b = 5*3 and snake_case <br> x") == "a * b = 5*3 and snake_case x"
    shell = ("<figure>\n\n![](images/1.png)\n\n<figcaption>\n\nA [chart](https://x.y) of *it*"
             "\n\n</figcaption>\n\n</figure>")
    assert 'alt="A chart of it"' in hugo.figure_shortcodes(shell)
    assert 'alt="A chart of it"' in pelican.figure_blocks(shell)
    given = shell.replace("![]", "![Given]")
    assert 'alt="Given"' in hugo.figure_shortcodes(given)
    assert 'alt="Given"' in pelican.figure_blocks(given)


def test_author_slugs_are_clean_and_shared_by_both_sites(tmp_path):
    """A byline is a person's name, not a slug, so left as the term it
    would reach each generator raw: hugo puts a name's accents and
    punctuation straight into the path it builds, while pelican folds
    the same name to ASCII, and one author ends up at two addresses.
    Both exporters therefore write the slug, as they already do for
    tags, and each carries the name separately for rendering."""
    hard = [("Frédéric Collonval", "frederic-collonval"),
            ("Michał Krassowski", "michal-krassowski"),
            ("C.A.M. Gerlach", "cam-gerlach"),
            ("Matt McCormick @thewtex@fosstodon.org",
             "matt-mccormick-thewtexfosstodonorg"),
            ("Joe Lucas ", "joe-lucas")]
    for name, slug in hard:
        assert sites.author_slug(name) == slug, name
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug), slug

    manifest = {}
    for i, (name, _slug) in enumerate(hard):
        make_post(tmp_path, manifest, f"post-{i}", f"abc123abc12{i}",
                  f"2020-01-0{i + 1}T00:00:00Z", "Hi.\n",
                  authors=[{"name": name, "url": None}])
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    (tmp_path / "site.json").write_text(json.dumps({"title": "T"}))
    slugs = [slug for _name, slug in hard]

    # the map both sites are named from: slug -> the name it shows
    assert sites.author_names(manifest) == {s: n for n, s in hard}

    hugo_site = hugo.build_site(tmp_path)
    front = lambda stem: json.loads(
        (hugo_site / f"content/posts/{stem}/index.md").read_text()
        .split("\n\n", 1)[0])
    assert [front(f"post-{i}")["authors"][0] for i in range(len(hard))] == slugs
    # the term pages come from that map, so the path stays the slug
    # while the title carries the name
    names = json.loads((hugo_site / "data/authornames.json").read_text())
    assert names == {s: n for n, s in hard}
    adapter = (hugo_site / "content/authors/_content.gotmpl").read_text()
    assert "hugo.Data.authornames" in adapter and '"kind" "term"' in adapter

    pelican_site = pelican.build_site(tmp_path)
    heads = [(pelican_site / f"content/posts/post-{i}/index.md").read_text()
             for i in range(len(hard))]
    assert [h.split("Authors: ", 1)[1].split("\n", 1)[0] for h in heads] == slugs
    config = (pelican_site / "pelicanconf.py").read_text()
    namespace = {}
    exec(compile(config, "pelicanconf.py", "exec"), namespace)
    assert namespace["AUTHOR_DISPLAY"] == {s: n for n, s in hard}

    # the plugin names the Author objects, as it does the tags: one
    # object per slug, the slug untouched, the name the one shown
    articles = [SimpleNamespace(authors=[_FakeTag(s)]) for s in slugs]
    generator = SimpleNamespace(
        authors=[(a.authors[0], [a]) for a in articles], articles=articles,
        translations=[], hidden_articles=[], hidden_translations=[],
        drafts=[], drafts_translations=[])
    namespace["_name_authors"](generator)
    assert [str(a.authors[0]) for a in articles] == [n for n, _s in hard]
    assert [a.authors[0].slug for a in articles] == slugs
