"""The hugo and pelican steps: archive/posts/ + posts.json -> a site."""

import json
import re
import sys

import yaml
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

from medium_archive import hugo, pelican, sites
from medium_archive.paths import archive_dir, site_config

BASE = "https://blog.example.com"


def site_json(root: Path) -> Path:
    """The project's hand-written site/site.json, its directory made on
    demand."""
    site_config(root).parent.mkdir(parents=True, exist_ok=True)
    return site_config(root)


def site_asset(root: Path, name: str) -> Path:
    """An image site.json names, which it names relative to itself."""
    return site_json(root).parent / name


def manifest_json(root: Path) -> Path:
    """The converted archive's posts.json."""
    archive_dir(root).mkdir(parents=True, exist_ok=True)
    return archive_dir(root) / "posts.json"


def make_post(root: Path, manifest: dict, slug: str, mid: str, date: str,
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
    post_dir = archive_dir(root) / d
    post_dir.mkdir(parents=True)
    (post_dir / "index.md").write_text(
        "---\n" + json.dumps({k: v for k, v in post.items() if k != "dir"})
        + "\n---\n\n" + body, encoding="utf-8")
    return url


@pytest.fixture
def project(tmp_path):
    manifest = {}
    make_post(tmp_path, manifest, "first-post", "aaa111aaa111",
              "2020-01-05T10:00:00Z",
              f"Hello. See [the sequel]({BASE}/second-post-bbb222bbb222).\n",
              ghost_url=f"{BASE}/2015/06/01/first-post")
    second = archive_dir(tmp_path) / "posts/2021-03-01-second-post"
    make_post(tmp_path, manifest, "second-post", "bbb222bbb222",
              "2021-03-01T10:00:00Z",
              "An image:\n\n![pic](images/001-pic.png)\n\n"
              "```\n![fenced](images/lit.png)\n```\n",
              images=["images/001-pic.png"])
    (second / "images").mkdir()
    (second / "images" / "001-pic.png").write_bytes(b"PNG")
    manifest_json(tmp_path).write_text(json.dumps(manifest))
    site_json(tmp_path).write_text(json.dumps(
        {"title": "Example Blog", "description": "An example.",
         "intro": "Welcome.", "base_url": "https://blog.example.org/"}))
    return tmp_path


def test_hugo_site(project):
    site_asset(project, "icon.svg").write_bytes(b"SVG")
    cfg = json.loads(site_json(project).read_text())
    cfg["favicon"] = "icon.svg"
    site_json(project).write_text(json.dumps(cfg))
    site = hugo.build_site(project)
    page = site / "content/posts/second-post/index.md"
    front = page_front(page)
    assert front["title"] == "Second Post"
    assert front["tags"] == ["example"] and front["authors"] == ["ada-lovelace"]
    assert front["aliases"] == ["/second-post-bbb222bbb222", "/p/bbb222bbb222"]
    assert (page.parent / "images/001-pic.png").read_bytes() == b"PNG"
    # the Ghost-era path becomes an alias too
    first = post_front(site, "first-post")
    assert "/2015/06/01/first-post" in first["aliases"]
    # in-publication links point at the new page URLs
    assert "](/posts/second-post/)" in (site / "content/posts/first-post/index.md").read_text()
    config = (site / "hugo.toml").read_text()
    assert 'baseURL = "https://blog.example.org/"' in config
    assert 'author = "authors"' in config
    # the tab icon lands at the site root, under its canonical name
    assert 'favicon = "favicon.svg"' in config
    assert (site / "static/favicon.svg").read_bytes() == b"SVG"
    assert 'rel="icon"' in (site / "layouts/baseof.html").read_text()
    # full-content feed, capped: announce new posts, don't ship the archive
    assert "[services.rss]\nlimit = 20" in config
    rss = (site / "layouts/rss.xml").read_text()
    assert "content:encoded" in rss and "srcset" in rss
    # a literal <?xml gets HTML-escaped by Hugo's template engine,
    # producing an invalid feed; it must go through safeHTML
    assert 'printf "<?xml' in rss and "safeHTML" in rss
    assert not rss.lstrip("{}-% \n").startswith("<?xml")
    assert (site / "layouts/page.html").exists()
    # a year-grouped archives timeline, like the pelican theme's
    assert (site / "layouts/archives.html").exists()
    assert page_front(site / "content/archives.md")["layout"] == "archives"
    assert "Welcome." in (site / "content/_index.md").read_text()
    assert (site / "redirects.csv").read_text().count("/posts/first-post/") == 3


def test_hugo_front_matter_is_yaml(project):
    """Hugo's metadata is YAML between `---` fences: the format its own
    documentation and themes are written in, and the one the pelican
    site writes, so a field is read and hand-edited the same way in
    either site. It comes from the yaml library, so a title holding a
    colon or a quote, a tag that reads as a boolean and a date that
    reads as a timestamp are quoted as the specification requires and
    read back as the strings they are."""
    site = hugo.build_site(project)
    text = (site / "content/posts/second-post/index.md").read_text()
    assert text.startswith("---\ntitle:")
    body = text.split("---\n", 2)[2]
    assert not body.lstrip().startswith("title:")
    # the site's own pages carry the same fences
    assert (site / "content/_index.md").read_text().startswith("---\n")
    assert page_front(site / "content/_index.md") == {"title": "Example Blog"}

    # what hand-written front matter gets wrong, and yaml does not
    tricky = {"title": 'Voil\u00e0: "quoted", 5 - 3', "tags": ["no", "c++"],
              "date": "2021-03-01T10:00:00.000Z", "aliases": ["/p/abc"]}
    assert yaml.safe_load(
        sites.front_matter_yaml(tricky).split("---\n")[1]) == tricky


FIGURE_BODY = ("<figure>\n\n![Alt text](images/001-fig.gif)\n\n"
               "<figcaption>\n\nThe caption, with a "
               "[link](https://example.com).\n\n</figcaption>\n\n"
               "</figure>\n")


def captioned_archive(project):
    manifest = json.loads(manifest_json(project).read_text())
    make_post(project, manifest, "captioned-post", "ccc333ccc333",
              "2022-06-01T10:00:00Z", FIGURE_BODY,
              images=["images/001-fig.gif"])
    d = archive_dir(project) / "posts/2022-06-01-captioned-post"
    (d / "images").mkdir()
    (d / "images" / "001-fig.gif").write_bytes(b"GIF")
    manifest_json(project).write_text(json.dumps(manifest))
    return project


def test_hugo_page_keeps_caption_in_its_figure(project):
    site = hugo.build_site(captioned_archive(project))
    # the shell becomes a call to the shipped figure shortcode, the
    # caption as inner content so its Markdown still renders
    page = (site / "content/posts/captioned-post/index.md").read_text()
    assert ('{{< figure src="images/001-fig.gif" alt="Alt text" >}}'
            "The caption, with a [link](https://example.com)."
            "{{< /figure >}}") in page
    # the shortcode the figure calls resolve to, and the image partial
    # it shares with the render hook
    assert (site / "layouts/_shortcodes/figure.html").exists()
    assert (site / "layouts/_partials/post-image.html").exists()


def page_front(path):
    """A page's front matter, parsed: YAML between `---` fences, the
    form both exporters write."""
    _, front, _ = Path(path).read_text().split("---\n", 2)
    return yaml.safe_load(front)


def post_front(site, stem):
    """The front matter of a site's posts/<stem>/ page -- hugo's and
    pelican's alike, which is the point of them sharing the format."""
    return page_front(site / f"content/posts/{stem}/index.md")


def config_namespace(site):
    """The generated config, executed as pelican executes it: from its
    own path, so the `data/*.json` files it reads beside itself are
    found. It is executable Python and needs neither pelican nor the
    site's own build, so its settings, its reader and the site plugin's
    functions can all be exercised from here."""
    path = site / "pelicanconf.py"
    namespace = {"__file__": str(path)}
    exec(compile(path.read_text(), "pelicanconf.py", "exec"), namespace)
    return namespace


def config_parser(site):
    """The markdown-it parser the generated config reads posts with.
    The config's reader is built where a pelican build would build it,
    so this is the same parser the site renders with -- without needing
    pelican itself installed."""
    namespace = config_namespace(site)
    return namespace, namespace["_make_md"]()


def test_pelican_page_writes_the_figure_directive(project):
    """The shell becomes the figure directive the generated config's
    reader renders -- the counterpart of the hugo exporter's figure
    shortcode. The caption is the directive's body, so it can hold
    Markdown an attribute could not, and the reader renders it with the
    site's own parser: CommonMark says the contents of an HTML block
    are raw, so a raw <figure> in the content would show the caption's
    Markdown to the reader."""
    site = pelican.build_site(captioned_archive(project))
    page = (site / "content/posts/captioned-post/index.md").read_text()
    assert ('::: figure src="{attach}images/001-fig.gif" alt="Alt text"\n'
            "The caption, with a [link](https://example.com).\n"
            ":::") in page

    _, md = config_parser(site)
    html = md.render(page.split("\n\n", 1)[1])
    # no <p> wrappers around the img or the caption, matching the
    # markup Medium serves and the hugo shortcode renders
    assert "<p><img" not in html and "<figcaption><p>" not in html
    assert ('<figcaption>The caption, with a '
            '<a href="https://example.com">link</a>.</figcaption>') in html
    # the image is the article's own body image, and keeps the {attach}
    # pelican resolves on the rendered page
    assert ('<img alt="Alt text" src="{attach}images/001-fig.gif" '
            'loading="lazy" data-body-image="">') in html


def test_the_figure_directive_escapes_what_it_renders(project):
    """The caption is Markdown, rendered by the site's parser; what it
    renders into an HTML attribute or a text node has to be escaped
    there, not left to the exporter."""
    _, md = config_parser(pelican.build_site(project))
    html = md.render('::: figure src="images/a.png" alt="R&D, 5 < 6"\n'
                     "A `code` span, R&D and 5 < 6.\n:::\n")
    assert 'alt="R&amp;D, 5 &lt; 6"' in html
    assert ("<figcaption>A <code>code</code> span, R&amp;D and 5 &lt; 6."
            "</figcaption>") in html


def test_the_front_matter_is_yaml_the_reader_reads_back(project):
    """Front matter is YAML between `---` fences, as `posts/` and the
    hugo site write it, rather than pelican's own `Key: value` headers
    that only pelican reads. It is written by the yaml library, so a
    title holding a colon or a quote is quoted as the specification
    requires, and the reader splits on the fence rather than on the
    first blank line."""
    site = pelican.build_site(project)
    namespace, _ = config_parser(site)
    text = (site / "content/posts/second-post/index.md").read_text()
    front, body = namespace["_split_front_matter"](text)
    assert yaml.safe_load(front)["title"] == "Second Post"
    assert not body.lstrip().startswith("title:")

    # what hand-written front matter gets wrong, and yaml does not
    tricky = {"title": 'Voil\u00e0: "quoted", 5 - 3', "tags": ["a", "b"],
              "date": "2021-03-01 10:00", "slug": "x"}
    parsed = yaml.safe_load(
        pelican.front_matter_yaml(tricky).split("---\n")[1])
    assert parsed == tricky

    # a horizontal rule in the body is not a front-matter fence
    front, body = namespace["_split_front_matter"]("Text.\n\n---\n\nMore.\n")
    assert front == "" and body.startswith("Text.")


def test_the_typographer_sets_prose_the_way_hugo_does(project):
    """Goldmark's typographer is on in the hugo site, so the pelican
    reader runs markdown-it's: without it the two sites set the same
    prose differently. The symbol substitutions are the one part left
    off -- markdown-it has them and goldmark does not, and "501(c)(3)"
    is a nonprofit, not a copyright sign."""
    _, md = config_parser(pelican.build_site(project))
    assert md.renderInline('He said "no", it\'s fine') == \
        "He said \u201cno\u201d, it\u2019s fine"
    assert md.renderInline("wait...") == "wait\u2026"
    assert md.renderInline("a -- b and c---d") == \
        "a \u2013 b and c\u2014d"
    # a flag is not a dash, and code is not prose
    assert md.renderInline("pip install --upgrade x") == \
        "pip install --upgrade x"
    assert md.renderInline("`\"quoted\"`") == "<code>&quot;quoted&quot;</code>"
    # the (c)/(tm)/(r) substitutions markdown-it would make and
    # goldmark does not; "+-" stays part of the rule that is called
    assert md.renderInline("a 501(c)(3) nonprofit (tm) (r)") == \
        "a 501(c)(3) nonprofit (tm) (r)"


def test_the_reader_registers_through_a_receiver_that_outlives_it(project):
    """pelican holds a signal's receivers weakly, so a receiver defined
    inside register() is collected on the way out and the reader never
    registers at all -- a build that silently falls back to
    python-markdown and renders every figure directive as text. The
    receiver has to be reachable after register() returns, which means
    the config's own module namespace holds it."""
    namespace, _ = config_parser(pelican.build_site(project))
    connected = []
    stub = ModuleType("pelican")
    stub.signals = SimpleNamespace(
        readers_init=SimpleNamespace(connect=connected.append))
    saved = sys.modules.get("pelican")
    sys.modules["pelican"] = stub
    try:
        namespace["_CommonMarkPlugin"].register()
    finally:
        if saved is None:
            del sys.modules["pelican"]
        else:
            sys.modules["pelican"] = saved
    receiver, = connected
    assert any(receiver is value for value in namespace.values())


def test_the_config_reads_commonmark(project):
    """The reader is a CommonMark parser (markdown-it-py), with the
    pieces this site needs hung off it. python-markdown, which pelican
    reads with by default, follows no specification and differs on all
    of these."""
    _, md = config_parser(pelican.build_site(project))

    # heading ids, as the search page's per-section anchors
    assert '<h2 id="voila-and-friends">' in md.render("## Voilà and friends\n")
    # code blocks on the class the shared stylesheet styles, which is
    # also the one hugo's chroma emits
    assert '<div class="highlight">' in md.render("```python\nx = 1\n```\n")
    assert '<div class="highlight">' in md.render("```\nplain\n```\n")
    # pelican's placeholders survive the parser's URL encoding, so its
    # intra-site pass still finds them on the rendered page
    assert 'src="{attach}images/a.png"' in md.render("![x]({attach}images/a.png)")
    assert 'href="{attach}notes.pdf"' in md.render("[x]({attach}notes.pdf)")
    # tables, strikethrough, footnotes and definition lists are on
    assert "<table>" in md.render("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<s>gone</s>" in md.render("~~gone~~\n")
    assert "footnote" in md.render("A[^1]\n\n[^1]: note\n")
    assert "<dl>" in md.render("term\n: meaning\n")
    # and the specification is followed where python-markdown guessed:
    # a bare <word> is text, not a dropped tag, and a list that starts
    # at 3 says so
    assert "&lt;my_package&gt;" in md.render("recipes/<my_package>\n")
    assert '<ol start="3">' in md.render("3. third\n4. fourth\n")


def test_link_wrapped_figures_keep_their_link():
    shell = ("<figure>\n\n[![Alt](images/a.png)](https://demo.example)\n\n"
             "<figcaption>\n\nCap.\n\n</figcaption>\n\n</figure>")
    assert hugo.figure_shortcodes(shell) == (
        '{{< figure src="images/a.png" alt="Alt" '
        'link="https://demo.example" >}}Cap.{{< /figure >}}')
    assert pelican.figure_directives(shell) == (
        '::: figure src="images/a.png" alt="Alt" '
        'link="https://demo.example"\nCap.\n:::')


def test_non_image_figure_shells_stay_raw_html():
    shell = ("<figure>\n\n[embed: https://u](https://u)\n\n<figcaption>\n\n"
             "Cap.\n\n</figcaption>\n\n</figure>")
    # neither exporter touches them: hugo leaves them to Goldmark's
    # unsafe renderer, and the pelican reader passes an HTML block
    # through the same way. Their lines are blank-line separated, which
    # ends the HTML block, so the Markdown between them still renders.
    assert hugo.figure_shortcodes(shell) == shell
    assert pelican.figure_directives(shell) == shell


def test_hugo_site_config_and_front_matter(project, capsys):
    site_asset(project, "logo.png").write_bytes(b"IMG")
    site_json(project).write_text(json.dumps(
        {"title": "Example Blog", "favicon": "missing.ico",
         "hugo": {"avatar": "logo.png", "params": {"motto": "hello"}}}))
    site = hugo.build_site(project)
    config = (site / "hugo.toml").read_text()
    assert "theme" not in config                # always the built-in theme
    assert 'motto = "hello"' in config          # user params merge last
    assert 'avatar = "img/avatar.png"' in config
    assert (site / "static/img/avatar.png").read_bytes() == b"IMG"
    # an asset site.json names but the archive lacks is skipped, noted
    assert "favicon" not in config
    assert "favicon not found, skipped" in capsys.readouterr().err
    assert (site / "layouts/baseof.html").exists()
    assert (site / "content/search.md").exists()
    assert (site / "content/archives.md").exists()
    front = post_front(site, "second-post")
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


def test_tag_display_names_reach_both_sites(project):
    """tags.json's display map names each tag on the rendered site while
    the tag itself -- front matter, tag URL -- stays a slug."""
    (archive_dir(project) / "tags.json").write_text(json.dumps(
        {"display": {"example": "Example Tag"}}))
    hugo_site = hugo.build_site(project)
    front = post_front(hugo_site, "second-post")
    assert front["tags"] == ["example"]           # the tag is still a slug
    # one data file names every tag; the content adapter beside the
    # posts turns it into the term pages (kind term, path = slug)
    names = hugo_site / "data/tags.json"
    assert json.loads(names.read_text()) == {"example": "Example Tag"}
    adapter = (hugo_site / "content/tags/_content.gotmpl").read_text()
    assert "hugo.Data.tags" in adapter and '"kind" "term"' in adapter
    assert not (hugo_site / "content/tags/example").exists()

    pelican_site = pelican.build_site(project)
    # the tag is still a slug
    assert post_front(pelican_site, "second-post")["tags"] == ["example"]
    # the same data file, hand-editable beside the generated config,
    # which reads it into TAG_DISPLAY at build time
    assert json.loads((pelican_site / "data/tags.json").read_text()) \
        == {"example": "Example Tag"}
    config = (pelican_site / "pelicanconf.py").read_text()
    assert 'TAG_DISPLAY = _data("tags.json")' in config
    assert config_namespace(pelican_site)["TAG_DISPLAY"] \
        == {"example": "Example Tag"}
    assert "_name_tags" in config          # names the Tag objects, so the
    assert "article_generator_finalized" in config   # feeds get it too


def test_both_sites_write_the_same_hand_editable_data_files(project):
    """The maps that are neither a post nor site.json -- tag names,
    author names, byline profiles -- are data files beside each site's
    config, the same three files with the same contents in both sites.
    Hugo reads them through hugo.Data; the pelican config reads them at
    config time, so editing one by hand renames a tag or corrects a
    profile in the built site without re-running the exporter."""
    (archive_dir(project) / "tags.json").write_text(json.dumps(
        {"display": {"example": "Example Tag"}}))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for name in ("tags.json", "authornames.json", "authors.json"):
        got = (pelican_site / "data" / name).read_bytes()
        assert got == (hugo_site / "data" / name).read_bytes(), name
        assert got.endswith(b"\n")           # a diffable, editable file
    assert json.loads((pelican_site / "data/tags.json").read_text()) \
        == {"example": "Example Tag"}
    assert json.loads((pelican_site / "data/authornames.json").read_text()) \
        == {"ada-lovelace": "Ada Lovelace"}
    assert json.loads((pelican_site / "data/authors.json").read_text()) \
        == {"Ada Lovelace": "https://medium.com/@ada"}
    # nothing of the three is baked into the generated config
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "Example Tag" not in config and "medium.com/@ada" not in config

    # a hand edit reaches the config's settings, with no rebuild
    (pelican_site / "data/tags.json").write_text(
        json.dumps({"example": "Renamed By Hand"}))
    assert config_namespace(pelican_site)["TAG_DISPLAY"] \
        == {"example": "Renamed By Hand"}
    # and a deleted file leaves a site that still builds, tags and
    # authors showing as their slugs
    for name in ("tags.json", "authornames.json", "authors.json"):
        (pelican_site / "data" / name).unlink()
    namespace = config_namespace(pelican_site)
    assert namespace["TAG_DISPLAY"] == namespace["AUTHOR_DISPLAY"] == {}
    assert namespace["AUTHOR_LINKS"] == {}


def test_tags_display_as_slugs_with_spaces_by_default(project):
    """No tags.json at all: a tag still shows with its hyphens as spaces."""
    manifest = json.loads(manifest_json(project).read_text())
    for post in manifest.values():
        post["tags"] = ["open-science"]
    manifest_json(project).write_text(json.dumps(manifest))
    site = hugo.build_site(project)
    names = json.loads((site / "data/tags.json").read_text())
    assert names == {"open-science": "open science"}


def test_feed_links_carry_the_rss_mark(project):
    """The header's feed link and the per-term ones on a tag's and an
    author's page are the shared RSS mark, pointing at that term's own
    feed."""
    hugo_site = hugo.build_site(project)
    nav = (hugo_site / "layouts/baseof.html").read_text()
    assert '<a class="feed-link" href="{{ "index.xml" | relURL }}"' in nav
    assert 'aria-label="RSS"' in nav and "feed-icon" in nav
    term = (hugo_site / "layouts/section.html").read_text()
    assert '.OutputFormats.Get "rss"' in term    # only where a feed exists
    assert 'aria-label="RSS feed for {{ $.Title }}"' in term

    pelican_site = pelican.build_site(project)
    # the tag and author pages are one template, over the feed setting
    # the page it was reached through named
    term = (pelican_site / "theme/templates/term.html").read_text()
    assert "term_feed.format(slug=term.slug)" in term
    assert 'aria-label="RSS feed for {{ term }}"' in term
    assert "feed-icon" in term
    for page, setting, var in (("tag.html", "TAG_FEED_ATOM", "tag"),
                               ("author.html", "AUTHOR_FEED_ATOM", "author")):
        text = (pelican_site / "theme/templates" / page).read_text()
        assert f"{{% set term, term_feed = {var}, {setting} %}}" in text
        assert '{% include "term.html" %}' in text
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


def test_every_article_gets_the_named_tag_object(project):
    """Pelican builds a Tag object per article and keys generator.tags on
    the slug, so it holds one object per tag while every other article
    keeps its own. Naming only the dict's keys named a tag on its own
    page and on one article's card, and left it a slug on the rest."""
    (archive_dir(project) / "tags.json").write_text(json.dumps(
        {"display": {"example": "Example Tag"}}))
    site = pelican.build_site(project)
    namespace = config_namespace(site)

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


def test_pelican_site(project):
    site_asset(project, "logo.png").write_bytes(b"IMG")
    site_asset(project, "icon.svg").write_bytes(b"SVG")
    cfg = json.loads(site_json(project).read_text())
    cfg["avatar"] = "logo.png"
    cfg["favicon"] = "icon.svg"
    site_json(project).write_text(json.dumps(cfg))
    site = pelican.build_site(project)
    text = (site / "content/posts/second-post/index.md").read_text()
    front = post_front(site, "second-post")
    assert front["title"] == "Second Post"
    assert front["date"] == "2021-03-01 10:00"
    assert front["authors"] == ["ada-lovelace"]
    assert front["tags"] == ["example"] and front["slug"] == "second-post"
    assert front["cover"].startswith("images/")   # summary-card cover
    # colocated images become {attach} links -- but not inside fences
    assert "]({attach}images/001-pic.png)" in text
    assert "![fenced](images/lit.png)" in text
    config = (site / "pelicanconf.py").read_text()
    assert 'SITENAME = "Example Blog"' in config
    assert 'ARTICLE_URL = "posts/{slug}/"' in config
    assert "FEED_MAX_ITEMS = 20" in config
    assert 'THEME = "theme"' in config
    assert '"search.html": "search/index.html"' in config
    # the CommonMark reader replaces pelican's python-markdown one, and
    # takes its settings with it
    assert "_CommonMarkReader" in config and "MARKDOWN = {" not in config
    assert 'AVATAR = "theme/img/avatar.png"' in config
    assert (site / "theme/static/img/avatar.png").read_bytes() == b"IMG"
    assert 'FAVICON = "theme/favicon.svg"' in config
    assert (site / "theme/static/favicon.svg").read_bytes() == b"SVG"
    assert 'rel="icon"' in (site / "theme/templates/base.html").read_text()
    for tpl in ("base", "index", "article", "term", "tag", "author",
                "terms", "tags", "authors", "archives", "search", "macros",
                "pagination"):
        assert (site / f"theme/templates/{tpl}.html").exists(), tpl
    assert "card-grid" in (site / "theme/static/css/style.css").read_text()
    assert (site / "redirects.csv").exists()
    # the embedded plugin turns redirects.csv into redirect stubs and
    # rewrites body images into responsive webp variants
    assert "PLUGINS = [_CommonMarkPlugin, _SitePlugins]" in config
    assert "signals.finalized" in config and "redirects.csv" in config
    assert "_optimize_article_images" in config
    assert "VARIANT_WIDTHS = (480, 736, 1104)" in config


def test_theme_picker_and_dark_scheme(project):
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    css = (hugo_site / "static/css/style.css").read_text()
    # dark palette under both routes: an explicit picker choice pins
    # data-theme; with none stored, the system scheme decides
    assert ':root[data-theme="dark"]' in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root:not([data-theme="light"])' in css
    assert ".theme-picker" in css
    assert (pelican_site / "theme/static/css/style.css").read_text() == css
    for base in (hugo_site / "layouts/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        for choice in ("light", "system", "dark"):
            assert f'data-set-theme="{choice}"' in text, base
        for choice in ("sans", "system-ui", "inter", "source-sans",
                       "source-serif", "atkinson", "nunito-sans",
                       "ibm-plex-sans", "ibm-plex-serif"):
            assert f'<option value="{choice}"' in text, base
        for choice in ("ink", "petrol-aaa", "link-blue", "browser"):
            assert f'<option value="{choice}"' in text, base
        # the link picker rides above the font one, so it is spliced in
        # first (the stack grows upwards from the corner)
        assert text.index("link-picker") < text.index("font-picker"), base
        # every family the picker offers beyond the launch stack and the
        # platform's own is a webfont: unlinked, those choices degrade to
        # their fallbacks silently, looking like a styling bug rather than
        # a missing file
        for family in ("Atkinson+Hyperlegible", "Atkinson+Hyperlegible+Mono",
                       "IBM+Plex+Mono", "IBM+Plex+Sans", "IBM+Plex+Serif",
                       "Inter", "Nunito+Sans", "Source+Serif+4",
                       "Source+Sans+3", "Source+Code+Pro"):
            assert f"family={family}" in text, (base, family)
        # the stored choices apply before the stylesheet loads, so a
        # page cannot flash the wrong scheme or font
        assert text.index("localStorage.getItem") < text.index("stylesheet")
        assert text.index('localStorage.getItem("font")') < text.index("stylesheet")
        assert text.index('localStorage.getItem("link")') < text.index("stylesheet")
    # redirect stubs load no stylesheet, so they must paint the palette
    # themselves -- following a redirect must not flash white in dark mode
    for stub_source in ((hugo_site / "layouts/alias.html").read_text(),
                        (pelican_site / "pelicanconf.py").read_text()):
        assert "prefers-color-scheme: dark" in stub_source
        assert 'localStorage.getItem("theme")' in stub_source
    # the snippets embed verbatim, so they must carry no template syntax
    # the other engine would mangle
    for name in ("theme-init", "theme-picker", "font-init", "font-picker",
                 "link-init", "link-picker", "term-sort", "announcement",
                 "nav-current", "image-zoom", "code-copy",
                 "heading-anchor", "feed-icon", "share-icons",
                 "newsletter"):
        snippet = sites.template_text(f"shared/{name}.html")
        assert "{{" not in snippet and "{%" not in snippet
    # without an avatar or announcement the config must still be valid
    # Python (json.dumps(None) would emit a NameError-raising `null`)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "AVATAR = None" in config
    assert "FAVICON = None" in config
    assert "ANNOUNCEMENT = None" in config


def test_announcement_banner(project):
    banner_url = "https://jupyter.org/assets/banner.html"
    cfg = json.loads(site_json(project).read_text())
    cfg["announcement"] = banner_url
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert f'announcement = "{banner_url}"' in (hugo_site / "hugo.toml").read_text()
    assert f'ANNOUNCEMENT = "{banner_url}"' in (pelican_site / "pelicanconf.py").read_text()
    for base in (hugo_site / "layouts/baseof.html",
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


def test_newsletter_band(project):
    # jupyter.org's signup band at the foot of every page: the heading
    # from site.json, the HubSpot form's ids on the section the snippet
    # reads them off, and the band hidden until that form is on its way
    cfg = json.loads(site_json(project).read_text())
    cfg["newsletter"] = {
        "heading": "Subscribe for updates",
        "hubspot_portal": "8112310",
        "hubspot_form": "3a79d744-5260-4a98-b069-39defccc8f42",
    }
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    hugo_config = (hugo_site / "hugo.toml").read_text()
    assert "[params.newsletter]" in hugo_config
    assert 'hubspot_portal = "8112310"' in hugo_config
    # the region is optional: HubSpot's own default stands in
    assert 'hubspot_region = "na1"' in hugo_config
    pelican_config = (pelican_site / "pelicanconf.py").read_text()
    assert '"hubspot_form": "3a79d744-5260-4a98-b069-39defccc8f42"' in pelican_config
    for base in (hugo_site / "layouts/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        assert 'class="newsletter"' in text, base
        for attr in ("data-hs-portal", "data-hs-form", "data-hs-region"):
            assert attr in text, (base, attr)
        assert 'class="newsletter-form"' in text, base
        # the band closes the page: after the article, before the
        # footer line, as it is on jupyter.org
        assert text.index("</main>") < text.index('class="newsletter"'), base
        assert text.index('class="newsletter"') < text.index("site-footer"), base
        # hidden markup, revealed only once the embed has loaded, so a
        # blocked script leaves no heading promising a form
        assert re.search(r'class="newsletter"[^>]*hidden', text), base
        assert "band.hidden = false" in text, base
        assert "js.hsforms.net" in text and "hbspt.forms.create" in text, base
        # the form renders in an iframe the page's CSS cannot reach, so
        # its look is passed to the embed -- with this site's accent on
        # the button, not the colour jupyter.org hard-codes
        assert "--accent" in text and ".hs-button" in text, base
        # and jupyter.org's layout: the fields on one row, then the
        # consent copy, then the button, each of the last two on a
        # full-width basis so the order holds at any field count
        assert '".hs-richtext { flex: 1 0 100%;' in text, base
        assert '".hs-submit { flex: 1 0 100%; }"' in text, base
        # and neither the copy nor the heading is held to a measure of
        # its own: both run the width of the band
        assert "max-width" not in text.split(".hs-richtext")[1][:200], base
    css = (hugo_site / "static/css/style.css").read_text()
    assert ".newsletter " in css and ".newsletter h2" in css
    assert css == (pelican_site / "theme/static/css/style.css").read_text()


def test_newsletter_band_absent_or_incomplete(project, capsys):
    # no "newsletter" at all: no band, and configs that are still valid
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert "[params.newsletter]" not in (hugo_site / "hugo.toml").read_text()
    assert "NEWSLETTER = None" in (pelican_site / "pelicanconf.py").read_text()
    # the band's markup is guarded by that setting, so an archive that
    # configures no newsletter renders no empty band
    assert ("{{ with site.Params.newsletter }}<section class=\"newsletter\""
            in (hugo_site / "layouts/baseof.html").read_text())
    assert ("{% if NEWSLETTER %}<section class=\"newsletter\""
            in (pelican_site / "theme/templates/base.html").read_text())
    # a half-filled entry is a mistake worth hearing about, not a band
    # quietly missing from the built site
    cfg = json.loads(site_json(project).read_text())
    cfg["newsletter"] = {"heading": "Subscribe for updates"}
    site_json(project).write_text(json.dumps(cfg))
    hugo.build_site(project)
    err = capsys.readouterr().err
    assert "hubspot_portal" in err and "hubspot_form" in err


def test_footer_line(project):
    # site.json's "footer" is the line under every page, Markdown, with
    # {year} the year of the build -- jupyter.org's trademark notice,
    # which carries a link and a copyright year, is the shape of it
    cfg = json.loads(site_json(project).read_text())
    cfg["footer"] = ("Trademarks are registered by "
                     "[LF Charities](https://lf-charities.org/). \u00a9 {year}")
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert "[LF Charities](https://lf-charities.org/)" in (
        hugo_site / "hugo.toml").read_text()
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "_FOOTER_MD = " in config
    # the year is substituted where the site is built, not baked into
    # the generated source, which stays the same from one build to the
    # next (and from one year to the next)
    assert '{year}' in config
    assert "_FOOTER_MD.replace(\"{year}\"" in config
    for base, render in ((hugo_site / "layouts/baseof.html",
                          'replace . "{year}"'),
                         (pelican_site / "theme/templates/base.html",
                          "FOOTER|safe")):
        text = base.read_text()
        assert render in text, base
        assert "site-footer" in text, base
    # the line is a paragraph of Markdown, so the footer spaces itself
    assert ".site-footer p { margin: 0; }" in (
        hugo_site / "static/css/style.css").read_text()


def test_footer_falls_back_to_the_description(project):
    # no "footer": the site's description, as the footer has always
    # carried, and a config that is still valid Python
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert "footer = " not in (hugo_site / "hugo.toml").read_text()
    assert "_FOOTER_MD = None" in (pelican_site / "pelicanconf.py").read_text()
    assert "{{ site.Params.description }}" in (
        hugo_site / "layouts/baseof.html").read_text()
    assert "{{ SITESUBTITLE }}" in (
        pelican_site / "theme/templates/base.html").read_text()


def test_masthead_logo(project):
    # site.json's "logo": a wordmark standing in for the site's name in
    # the header, the way jupyter.org's navbar carries its rectangle
    # logo, with "logo_dark" the same mark for the dark palette
    site_asset(project, "logo.svg").write_bytes(b"<svg/>")
    site_asset(project, "logo-dark.svg").write_bytes(b"<svg dark/>")
    cfg = json.loads(site_json(project).read_text())
    cfg["logo"], cfg["logo_dark"] = "logo.svg", "logo-dark.svg"
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert 'logo = "img/logo.svg"' in (hugo_site / "hugo.toml").read_text()
    assert 'logo_dark = "img/logo-dark.svg"' in (hugo_site / "hugo.toml").read_text()
    assert (hugo_site / "static/img/logo.svg").read_bytes() == b"<svg/>"
    assert (pelican_site / "theme/static/img/logo-dark.svg").read_bytes() == b"<svg dark/>"
    config = (pelican_site / "pelicanconf.py").read_text()
    assert 'LOGO = "theme/img/logo.svg"' in config
    assert 'LOGO_DARK = "theme/img/logo-dark.svg"' in config
    for base in (hugo_site / "layouts/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        assert "site-logo-light" in text and "site-logo-dark" in text, base
        # the pair carries no alt text of its own -- either image would
        # name the link twice over -- so the link is named once, on the
        # anchor, and reads the same whichever one is showing
        assert "aria-label" in text, base
    # the palettes pick between the two, like every other value that
    # differs between them
    css = (hugo_site / "static/css/style.css").read_text()
    assert "--logo-light: block" in css and "--logo-dark: block" in css
    assert "display: var(--logo-light)" in css


def test_masthead_logo_link(project):
    # site.json's "logo_link": a mark that stands for something larger
    # than the blog (the Jupyter mark over a Jupyter blog) links there
    # instead of to the site's home, and the link reads under that
    # address's host rather than the site's own title
    site_asset(project, "logo.svg").write_bytes(b"<svg/>")
    cfg = json.loads(site_json(project).read_text())
    cfg["logo"], cfg["logo_link"] = "logo.svg", "https://jupyter.org"
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    toml = (hugo_site / "hugo.toml").read_text()
    assert "[params.logo_link]" in toml
    assert 'url = "https://jupyter.org"' in toml
    assert 'label = "jupyter.org"' in toml
    assert ('LOGO_LINK = {"url": "https://jupyter.org", '
            '"label": "jupyter.org"}') in (
        pelican_site / "pelicanconf.py").read_text()
    # the nav still carries the way home, so the site is not left
    # without a link to its own landing page
    for base, home in ((hugo_site / "layouts/baseof.html",
                        '<a href="{{ site.Home.RelPermalink }}">Blog</a>'),
                       (pelican_site / "theme/templates/base.html",
                        '<a href="{{ SITEURL }}/">Blog</a>')):
        assert home in base.read_text(), base


def test_masthead_link_defaults_home(project):
    # no "logo_link": the masthead links to the site's own home, named
    # by the site's title, as it always has
    site_asset(project, "logo.svg").write_bytes(b"<svg/>")
    cfg = json.loads(site_json(project).read_text())
    cfg["logo"] = "logo.svg"
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert "logo_link" not in (hugo_site / "hugo.toml").read_text()
    assert "LOGO_LINK = None" in (
        pelican_site / "pelicanconf.py").read_text()
    # and with no logo to carry it the link is not read at all: the
    # masthead is then the site's own name, which cannot lead off-site
    del cfg["logo"]
    cfg["logo_link"] = "https://jupyter.org"
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert "logo_link" not in (hugo_site / "hugo.toml").read_text()
    assert "LOGO_LINK = None" in (
        pelican_site / "pelicanconf.py").read_text()


def test_nav_current_highlight(project):
    # the nav link whose path prefixes the current page's gets
    # aria-current, which the stylesheet paints in the accent
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for base in (hugo_site / "layouts/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        text = base.read_text()
        assert 'setAttribute("aria-current", "page")' in text, base
        # the script follows the nav it marks
        assert text.index("</header>") < text.index("aria-current"), base
    assert 'a[aria-current="page"]' in (hugo_site / "static/css/style.css").read_text()


def test_nav_wraps_without_overlapping_itself(project):
    # A phone-width screen wraps the nav, and each item is pulled
    # .9375rem down the header to land its tab bar on the header's
    # border. Laid out as inline-blocks the two together overlapped:
    # a line box is sized to the pulled-in margin box, so a wrapped
    # row was laid that .9375rem short and the row above printed its
    # accent bar through the words below it. The rows are flex rows
    # now, and the row-gap gives that space back with room to spare.
    css = (hugo.build_site(project) / "static/css/style.css").read_text()
    nav = css[css.index(".site-header nav {"):]
    nav = nav[:nav.index("}")]
    assert "flex-wrap: wrap" in nav and "row-gap: 1.25rem" in nav
    item = css[css.index(".site-header nav a {"):css.index(".site-header nav a:hover")]
    assert "margin-bottom: -.9375rem" in item
    # the row's own gaps space the items, so no item carries a margin
    # that would indent the start of a wrapped row
    assert "margin-left" not in item


def test_term_sort_control(project):
    # the tag/author chip indexes carry the name/count sort control,
    # placed above the chip list it reorders
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for page in (hugo_site / "layouts/taxonomy.html",
                 pelican_site / "theme/templates/terms.html"):
        text = page.read_text()
        for order in ("name", "count"):
            assert f'data-sort="{order}"' in text, page
        assert text.index("term-sort") < text.index("term-list"), page
    for page, terms in (("tags.html", "tags"), ("authors.html", "authors")):
        text = (pelican_site / "theme/templates" / page).read_text()
        assert f"{{% set terms, terms_title = {terms}," in text
        assert '{% include "terms.html" %}' in text
    css = (hugo_site / "static/css/style.css").read_text()
    assert ".term-sort" in css
    assert css == (pelican_site / "theme/static/css/style.css").read_text()


SITE_URL = "https://blog.example.org"


class _Term(str):
    """A pelican Tag or Author as the theme sees one: it renders as its
    name and carries the slug and URL the theme builds links from."""

    def __new__(cls, name, kind):
        term = super().__new__(cls, name)
        term.name = name
        term.slug = name.lower().replace(" ", "-")
        term.url = f"{kind}/{term.slug}/"
        return term


def render_pelican_page(site, template, **context):
    """One page of the generated theme, rendered with the jinja settings
    the generated config gives pelican, over the values that page reads."""
    env = Environment(loader=FileSystemLoader(site / "theme/templates"),
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    article = SimpleNamespace(
        title="First Post", url="posts/first-post/", cover=None,
        summary="Hello.", locale_date="2020-01-05",
        tags=[_Term("example", "tags")],
        authors=[_Term("Ada Lovelace", "authors")])
    values = dict(
        SITEURL=SITE_URL, SITENAME="Example Blog", SITESUBTITLE="An example.",
        DEFAULT_LANG="en", THEME_STATIC_DIR="theme", AUTHOR_LINKS={},
        FEED_ALL_ATOM="feeds/all.atom.xml",
        TAG_FEED_ATOM="feeds/tag-{slug}.atom.xml",
        AUTHOR_FEED_ATOM="feeds/author-{slug}.atom.xml",
        TAGS_URL="tags/", AUTHORS_URL="authors/",
        articles_page=SimpleNamespace(object_list=[article], number=1,
                                      has_other_pages=lambda: False))
    values.update(context)
    return env.get_template(template).render(**values)


def test_taxonomy_pages_render_through_the_shared_templates(project):
    """A tag page and an author page are one template (term.html) handed
    the page's own term, and their chip indexes another (terms.html):
    the two pages of each pair differed in nothing but the variable's
    name, so a change to one had to be made twice. Rendered here because
    the delegation is only right or wrong at render time, and pelican
    itself is not a dependency of these tests."""
    site = pelican.build_site(project)
    tag = _Term("example", "tags")
    author = _Term("Ada Lovelace", "authors")

    for page, var, term, feed, index in (
            ("tag.html", "tag", tag, "feeds/tag-example.atom.xml", "Tags"),
            ("author.html", "author", author,
             "feeds/author-ada-lovelace.atom.xml", "Authors")):
        html = render_pelican_page(site, page, **{var: term},
                                   output_file=term.url + "index.html")
        assert f"<title>{term} \u00b7 Example Blog</title>" in html
        # the term's own heading, with the feed link beside it, and that
        # same feed declared in the head
        assert (f'<h1 class="page-title">{term}<a class="feed-link" '
                f'href="{SITE_URL}/{feed}"') in html
        assert (f'<link rel="alternate" type="application/atom+xml" '
                f'href="{SITE_URL}/{feed}"') in html
        # base.html and jsonld.html still read the page's own tag or
        # author: the crumbs place it under that taxonomy's index
        assert f'"name": "{index}"' in html
        # and the term's posts are there as cards
        assert (f'<h2 class="card-title"><a href="{SITE_URL}/'
                f'posts/first-post/">First Post</a></h2>') in html

    # the chip indexes, each over its own taxonomy, in name order
    beta = _Term("beta", "tags")
    chips = ('<a class="chip" href="%s/%s">%s <span>%d</span></a>'
             % (SITE_URL, t.url, t, n) for t, n in ((beta, 2), (tag, 1)))
    html = render_pelican_page(site, "tags.html", articles_page=None,
                               output_file="tags/index.html",
                               tags=[(tag, [1]), (beta, [1, 2])])
    assert "<title>Tags \u00b7 Example Blog</title>" in html
    assert '<h1 class="page-title">Tags</h1>' in html
    assert "\n".join(chips) in html
    html = render_pelican_page(site, "authors.html", articles_page=None,
                               output_file="authors/index.html",
                               authors=[(author, [1])])
    assert "<title>Authors \u00b7 Example Blog</title>" in html
    assert '<h1 class="page-title">Authors</h1>' in html
    assert ('<a class="chip" href="%s/%s">%s <span>1</span></a>'
            % (SITE_URL, author.url, author)) in html


def test_image_zoom(project):
    # post pages carry the click-to-zoom modal, on both engines
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for page in (hugo_site / "layouts/page.html",
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


def test_code_copy(project):
    # post pages carry the code-block copy button, on both engines
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for page in (hugo_site / "layouts/page.html",
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


def test_heading_anchor(project):
    # post pages carry the per-heading link mark, on both engines
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for page in (hugo_site / "layouts/page.html",
                 pelican_site / "theme/templates/article.html"):
        text = page.read_text()
        assert '<template class="heading-anchor-template">' in text, page
        # the mark follows the article whose headings it serves
        assert text.index("</article>") < text.index("heading-anchor-template"), page
        # every body heading that has an id gets one, cloned from the
        # template; the ids are the readers' own, so the script makes none
        assert 'article.querySelectorAll(' in text, page
        assert '"h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]"' in text, page
        assert "template.content.firstElementChild.cloneNode(true)" in text, page
        assert 'link.setAttribute("href", "#" + heading.id)' in text, page
        # an SVG is not a label, so the link carries its own
        assert 'aria-label="Link to this heading"' in text, page
    # a plain link, so the browser's own handling applies: the snippet
    # binds no click of its own, and sets no id the readers didn't give
    snippet = sites.template_text("shared/heading-anchor.html")
    assert "addEventListener(\"click\"" not in snippet
    assert "preventDefault" not in snippet
    assert "heading.id =" not in snippet
    css = (hugo_site / "static/css/style.css").read_text()
    # hidden until its heading is hovered or the mark reached by
    # keyboard, and always shown where there is no hover; by opacity,
    # so revealing it never re-wraps the heading
    assert ".heading-anchor { margin-left: .3em; color: var(--muted); opacity: 0; }" in css
    assert (".post :hover > .heading-anchor,\n"
            ".heading-anchor:focus-visible { opacity: 1; }") in css
    assert "@media (hover: none) { .heading-anchor { opacity: 1; } }" in css
    # a mark, not words: no rule under it, and the accent only under
    # the pointer, where the copy button takes it too
    assert ".heading-anchor, .heading-anchor:hover { text-decoration-line: none; }" in css
    assert (".heading-anchor:hover, .heading-anchor:focus-visible"
            " { color: var(--accent); }") in css
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


def test_post_share_links(project):
    """A post carries the five share links twice -- under the byline and
    at the foot -- from one definition per engine, each mark coming from
    the shared sprite."""
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    # each engine names the same three values, so the bars keep one shape
    for bar, url, title, text in (
            (hugo_site / "layouts/_partials/share.html", "{{ .Permalink }}",
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

    for page, call in ((hugo_site / "layouts/page.html",
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


def test_share_targets_get_the_open_graph_tags_they_render_from(project):
    """LinkedIn's and Facebook's share URLs carry only the page address:
    everything their share box shows comes from the page's Open Graph
    tags, so the share links are worth no more than these."""
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    for head in (hugo_site / "layouts/baseof.html",
                 pelican_site / "theme/templates/base.html"):
        source = head.read_text()
        for prop in ("og:site_name", "og:type", "og:title", "og:url",
                     "og:description", "og:image", "article:published_time"):
            assert f'property="{prop}"' in source, (head, prop)
        assert 'rel="canonical"' in source, head
        # a post with no cover has no image to promise
        assert "summary_large_image" in source and "summary" in source, head


def test_a_title_is_plain_text_not_html(project):
    """Pelican renders only FORMATTED_FIELDS (summary) as markdown, so a
    post's title reaches the theme as the plain text of its Title:
    header. Stripping tags from it would delete any run shaped like one
    -- "Using <script> tags safely" -> "Using tags safely" -- rather
    than escape it, losing what hugo keeps."""
    pelican_site = pelican.build_site(project)
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


def test_pelican_escapes_by_default(project):
    """Pelican's own default JINJA_ENVIRONMENT sets no autoescape and
    jinja's default is off, so a theme emits every {{ }} raw -- which
    makes a post title reading `<script>...` a running script on every
    page that renders it, and titles, tag names and authors all come
    from the archived publication. The generated config turns escaping
    on; only the rendered body is marked safe."""
    site = pelican.build_site(project)
    config = (site / "pelicanconf.py").read_text()
    assert '"autoescape": True' in config
    # the setting replaces pelican's defaults rather than merging, so
    # the rest of them have to be restated with it
    for key in ('"trim_blocks": True', '"lstrip_blocks": True',
                '"extensions": []'):
        assert key in config, key
    # the genuinely-HTML values in the theme, and the only ones: the
    # rendered body, and the landing-page intro and footer line the
    # config renders from site.json's Markdown. Both of those are
    # hand-written and versioned with the archive, unlike a title or a
    # tag name, which come from whoever wrote the post -- that is what
    # makes them safe to mark safe.
    templates = site / "theme/templates"
    safe = [(f.name, line.strip()) for f in sorted(templates.glob("*.html"))
            for line in f.read_text().splitlines() if "|safe" in line]
    assert safe == [
        # a FORMATTED_FIELD: the rendered HTML of the subtitle's own
        # Markdown, like article.content below it
        ("article.html",
         '{% if article.subtitle %}<div class="post-subtitle">'
         "{{ article.subtitle|safe }}</div>{% endif %}"),
        ("article.html", "{{ article.content|safe }}"),
        ("base.html",
         '<footer class="wrap site-footer">{% if FOOTER %}{{ FOOTER|safe }}'
         '{% else %}{{ SITESUBTITLE }}{% endif %}</footer>'),
        ("index.html",
         '{% if INTRO %}<div class="intro">{{ INTRO|safe }}</div>{% endif %}'),
    ], safe


def test_the_subtitle_reaches_every_post_page(tmp_path):
    """The post's subtitle line is front matter, not body, and each
    site's post template renders it under the title -- with the links
    the plain-text description lost, and with a link to another post of
    the publication rewritten to its page, as a body link would be."""
    manifest = {}
    make_post(tmp_path, manifest, "first-post", "aaa111aaa111",
              "2020-01-05T10:00:00Z", "Body.\n",
              subtitle=f"Read [the sequel]({BASE}/second-post-bbb222bbb222) "
                       "and [the docs](https://example.org/docs).")
    make_post(tmp_path, manifest, "second-post", "bbb222bbb222",
              "2021-03-01T10:00:00Z", "Body.\n")
    manifest_json(tmp_path).write_text(json.dumps(manifest))
    site_json(tmp_path).write_text(json.dumps(
        {"title": "Example Blog", "base_url": "https://blog.example.org/"}))

    for build in (hugo.build_site, pelican.build_site):
        site = build(tmp_path)
        page = (site / "content/posts/first-post/index.md").read_text()
        line = next(l for l in page.split("\n") if l.startswith("subtitle:"))
        # the links survive, and the in-publication one points at its page
        assert "[the sequel](/posts/second-post/)" in line
        assert "[the docs](https://example.org/docs)" in line
        # and the body is the body alone
        assert page.split("\n---\n", 1)[1].strip() == "Body."

    # both post templates render it in the element the shared CSS styles
    for tpl in ("hugo/layouts/page.html",
                "pelican/theme/templates/article.html"):
        assert 'class="post-subtitle"' in sites.template_text(tpl)
    assert ".post-subtitle {" in sites.template_text("shared/card.css")


def test_missing_base_url_is_not_silent(tmp_path, capsys):
    """Every absolute link -- feeds, redirect stubs, og:url, the share
    links -- is built from base_url, and a share link with the wrong one
    fails outright rather than degrading, so an unset base_url has to be
    said out loud at build time."""
    manifest = {}
    make_post(tmp_path, manifest, "post", "aaa111aaa111",
              "2020-01-05T10:00:00Z", "Hello.\n")
    manifest_json(tmp_path).write_text(json.dumps(manifest))
    site_json(tmp_path).write_text(json.dumps({"title": "Example"}))
    sites.load_site_inputs(tmp_path)
    assert "no base_url" in capsys.readouterr().err
    # and stays quiet once it is set
    site_json(tmp_path).write_text(json.dumps(
        {"title": "Example", "base_url": "https://blog.example.org"}))
    sites.load_site_inputs(tmp_path)
    assert "base_url" not in capsys.readouterr().err


def test_build_output_survives_regeneration(project):
    for module, kept in ((hugo, "public"), (pelican, "output")):
        site = module.build_site(project)
        (site / kept).mkdir()
        (site / kept / "index.html").write_text("built")
        module.build_site(project)
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
    img_dir = archive_dir(tmp_path) / "posts/2022-06-01-picture-post/images"
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
    manifest_json(tmp_path).write_text(json.dumps(manifest))
    site_json(tmp_path).write_text(json.dumps({"title": "Pics"}))
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
    site_json(tmp_path).write_text(json.dumps(
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
    manifest_json(tmp_path).write_text(json.dumps(manifest))
    site_json(tmp_path).write_text(json.dumps({"title": "T"}))

    site = hugo.build_site(tmp_path)
    front = lambda stem: post_front(site, stem)
    assert front("duet")["authors"] == ["ada-lovelace", "yuvipanda"]
    assert "author" not in front("duet")
    assert "authors" not in front("solo")
    assert "capitalizeListTitles = false" in (site / "hugo.toml").read_text()
    text = (site / "layouts/rss.xml").read_text()
    assert ".Params.authors" in text and ".Params.author " not in text
    # the card's byline links each author to their listing, like the
    # post page's, so both walk the taxonomy terms rather than the names
    for layout in ("layouts/_partials/card.html", "layouts/page.html"):
        text = (site / layout).read_text()
        assert '.GetTerms "authors"' in text and ".Params.author" not in text, layout
        assert 'href="{{ .RelPermalink }}">{{ .LinkTitle }}</a>' in text, layout

    site = pelican.build_site(tmp_path)
    assert post_front(site, "duet")["authors"] == ["ada-lovelace",
                                                   "yuvipanda"]
    # a slug holds no comma, so the reader's comma split is unambiguous
    # even for a byline like "Project Jupyter, Inc." that once forced
    # pelican's semicolon separator
    assert post_front(site, "trio")["authors"] == ["project-jupyter-inc",
                                                   "min-rk"]
    assert "authors" not in post_front(site, "solo")
    for tpl in ("article", "macros", "base"):
        text = (site / f"theme/templates/{tpl}.html").read_text()
        assert "article.authors" in text and "article.author " not in text \
            and "article.author." not in text and "article.author|" not in text, tpl
    for tpl in ("article", "macros"):
        text = (site / f"theme/templates/{tpl}.html").read_text()
        assert 'for a in article.authors' in text \
            and '<a href="{{ SITEURL }}/{{ a.url }}">{{ a }}</a>' in text, tpl


def test_first_image_loads_eagerly(project):
    """Every body image is lazy except the first, which is the one most
    likely on screen at load (WordPress's treatment of the first content
    image): the exporter names it, and each theme fetches it eagerly at
    high priority. A reference inside a code fence is not an image."""
    assert sites.first_image("text\n\n```\n![x](images/a.png)\n```\n"
                             "![y](images/b.png) and ![z](images/c.png)\n"
                             ) == "images/b.png"
    assert sites.first_image("no images\n") is None
    hugo_site = hugo.build_site(project)
    front = post_front(hugo_site, "second-post")
    assert front["first_image"] == "images/001-pic.png"
    first = post_front(hugo_site, "first-post")
    assert "first_image" not in first
    partial = (hugo_site / "layouts/_partials/post-image.html").read_text()
    assert ".page.Params.first_image" in partial
    assert 'fetchpriority="high"' in partial and 'loading="lazy"' in partial
    pelican_site = pelican.build_site(project)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert "_prioritize_first_images" in config
    assert 'fetchpriority="high"' in config


def test_crawl_files(project):
    """What search engines ask for first: a sitemap and a robots.txt
    naming it (Hugo generates the sitemap itself; Pelican's plugin
    writes both), plus the redirect map as a `_redirects` file for hosts
    that turn one into HTTP 301s. The search page stays out of the
    index and the sitemap."""
    hugo_site = hugo.build_site(project)
    assert "enableRobotsTXT = true" in (hugo_site / "hugo.toml").read_text()
    robots = (hugo_site / "layouts/robots.txt").read_text()
    assert '"sitemap.xml" | absURL' in robots and "Disallow: /" in robots
    search = page_front(hugo_site / "content/search.md")
    assert search["noindex"] is True and search["sitemap"] == {"disable": True}
    redirects = (hugo_site / "static/_redirects").read_text().splitlines()
    assert "/first-post-aaa111aaa111 /posts/first-post/ 301" in redirects
    assert "/2015/06/01/first-post /posts/first-post/ 301" in redirects
    assert "/p/bbb222bbb222 /posts/second-post/ 301" in redirects
    assert all(line.endswith(" 301") for line in redirects)
    baseof = (hugo_site / "layouts/baseof.html").read_text()
    assert 'name="robots"' in baseof and "max-image-preview:large" in baseof
    assert "site.Params.noindex" in baseof and ".Params.noindex" in baseof

    pelican_site = pelican.build_site(project)
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


def test_noindex_and_twitter_reach_both_sites(project):
    """site.json's "noindex" keeps search engines off a deployment (a
    preview, which would otherwise be indexed as a copy of the real
    site); "twitter" credits the publication's handle on shared links."""
    cfg = json.loads(site_json(project).read_text())
    cfg["noindex"] = True
    cfg["twitter"] = "@example"
    site_json(project).write_text(json.dumps(cfg))
    config = (hugo.build_site(project) / "hugo.toml").read_text()
    assert "noindex = true" in config and 'twitter = "@example"' in config
    config = (pelican.build_site(project) / "pelicanconf.py").read_text()
    assert "NOINDEX = True" in config and 'TWITTER = "@example"' in config


def test_page_metadata_search_engines_read(project):
    """What Medium's and WordPress's pages carry beyond the share tags:
    the post's own description, its modified date, its author by name
    and by page, structured data (a schema.org BlogPosting), and a
    canonical address that is the page's own -- page 2 of a listing
    included, which both engines would otherwise call page one."""
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    heads = {"hugo": (hugo_site / "layouts/baseof.html").read_text(),
             "pelican": (pelican_site / "theme/templates/base.html").read_text()}
    for engine, head in heads.items():
        for prop in ("article:modified_time", "article:author"):
            assert f'property="{prop}"' in head, (engine, prop)
        assert 'name="author"' in head, engine
        assert 'name="twitter:site"' in head, engine
    # structured data: one block, a BlogPosting, with the fields that
    # matter, and every value escaped for a <script>
    ld = (hugo_site / "layouts/_partials/jsonld.html").read_text()
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
    for layout in ("home.html", "section.html"):
        assert 'partial "paginator.html"' in (hugo_site / "layouts" / layout).read_text()
    assert "output_file" in heads["pelican"]
    assert ('<link rel="canonical" href="{{ article.canonical if article '
            'and article.canonical else page_url }}">') in heads["pelican"]


def _graph_source(engine_site, engine):
    if engine == "hugo":
        return (engine_site / "layouts/_partials/jsonld.html").read_text()
    return (engine_site / "theme/templates/jsonld.html").read_text()


def test_external_canonical_reaches_the_head(project):
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

    manifest = json.loads(manifest_json(project).read_text())
    url = next(u for u in manifest if "second-post" in u)
    manifest[url]["canonical_url"] = "https://gist.github.com/ada/1"
    manifest_json(project).write_text(json.dumps(manifest))
    hugo_site = hugo.build_site(project)
    second = post_front(hugo_site, "second-post")
    assert second["canonical"] == "https://gist.github.com/ada/1"
    first = post_front(hugo_site, "first-post")
    assert "canonical" not in first
    baseof = (hugo_site / "layouts/baseof.html").read_text()
    assert '<link rel="canonical" href="{{ or .Params.canonical $url }}">' in baseof
    pelican_site = pelican.build_site(project)
    assert post_front(pelican_site, "second-post")["canonical"] == \
        "https://gist.github.com/ada/1"
    assert "canonical" not in post_front(pelican_site, "first-post")
    base = (pelican_site / "theme/templates/base.html").read_text()
    assert 'href="{{ article.canonical if article and article.canonical else page_url }}"' in base
    # neither head knows the Medium address: a post without a declared
    # canonical (first-post above) is its own
    assert "original_url" not in baseof and "original_url" not in base


def test_share_image_stands_in_for_a_missing_cover(project):
    """site.json "share_image": the og:image of every page without a
    cover of its own, so a listing or a coverless post still shares
    with a picture; both heads declare the image's dimensions, so
    Facebook renders the large card on the first share."""
    pytest.importorskip("PIL")
    from PIL import Image
    Image.new("RGB", (1200, 630)).save(site_asset(project, "share.png"))
    cfg = json.loads(site_json(project).read_text())
    cfg["share_image"] = "share.png"
    site_json(project).write_text(json.dumps(cfg))
    hugo_site = hugo.build_site(project)
    assert 'share_image = "img/share.png"' in (hugo_site / "hugo.toml").read_text()
    assert (hugo_site / "assets/img/share.png").is_file()   # readable dims
    baseof = (hugo_site / "layouts/baseof.html").read_text()
    assert 'with site.Params.share_image }}{{ with resources.Get .' in baseof
    for prop in ("og:image:width", "og:image:height"):
        assert f'property="{prop}"' in baseof, prop
    pelican_site = pelican.build_site(project)
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
    site_json(project).write_text(json.dumps(cfg))
    assert "share_image" not in (hugo.build_site(project) / "hugo.toml").read_text()
    config = (pelican.build_site(project) / "pelicanconf.py").read_text()
    assert "SHARE_IMAGE = None" in config and "SHARE_IMAGE_SIZE = None" in config


def test_structured_data_graph(project):
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
    manifest = json.loads(manifest_json(project).read_text())
    assert sites.author_links(manifest) == {"Ada Lovelace": "https://medium.com/@ada"}
    cfg = json.loads(site_json(project).read_text())
    cfg["twitter"] = "@example"
    cfg["profiles"] = ["https://github.com/example"]
    site_json(project).write_text(json.dumps(cfg))

    hugo_site = hugo.build_site(project)
    assert json.loads((hugo_site / "data/authors.json").read_text()) \
        == {"Ada Lovelace": "https://medium.com/@ada"}
    config = (hugo_site / "hugo.toml").read_text()
    assert 'profiles = ["https://github.com/example", "https://x.com/example"]' in config
    # the graph on every page, not only posts
    baseof = (hugo_site / "layouts/baseof.html").read_text()
    assert '{{ end }}{{ partial "jsonld.html"' in baseof
    # the tag and author indexes are titled as the nav names them, which
    # the breadcrumbs repeat
    for plural, title in (("tags", "Tags"), ("authors", "Authors")):
        assert page_front(hugo_site / "content" / plural / "_index.md") \
            == {"title": title}
    pelican_site = pelican.build_site(project)
    config = (pelican_site / "pelicanconf.py").read_text()
    assert 'PROFILES = ["https://github.com/example", "https://x.com/example"]' in config
    # the byline profiles are the same data file in both sites, read
    # into the pelican config as AUTHOR_LINKS
    assert json.loads((pelican_site / "data/authors.json").read_text()) \
        == {"Ada Lovelace": "https://medium.com/@ada"}
    assert config_namespace(pelican_site)["AUTHOR_LINKS"] \
        == {"Ada Lovelace": "https://medium.com/@ada"}
    assert '{% include "jsonld.html" %}' in (pelican_site / "theme/templates/base.html").read_text()
    for engine, site in (("hugo", hugo_site), ("pelican", pelican_site)):
        src = _graph_source(site, engine)
        for key in ("@graph", "Organization", "WebSite", "SearchAction",
                    "search/?q={search_term_string}", "BreadcrumbList",
                    "ListItem", "BlogPosting", "ProfilePage", "sameAs",
                    "isPartOf", "ImageObject", "articleSection"):
            assert key in src, (engine, key)
    assert "hugo.Data.authors" in _graph_source(hugo_site, "hugo")
    assert "AUTHOR_LINKS" in _graph_source(pelican_site, "pelican")


def test_related_posts(project):
    """Each post page closes with more posts, by shared tags, then
    author, then date: Hugo's related content, configured in the
    generated config; the pelican plugin scores the same way. The
    block is headed "More posts" in both sites -- the scoring guesses
    at a kinship from tags and bylines, so the heading claims none."""
    hugo_site = hugo.build_site(project)
    config = (hugo_site / "hugo.toml").read_text()
    assert "[related]" in config and 'name = "tags"' in config
    assert 'partial "related.html"' in (hugo_site / "layouts/page.html").read_text()
    related = (hugo_site / "layouts/_partials/related.html").read_text()
    assert '(where site.RegularPages "Type" "posts").Related' in related and 'partial "card.html"' in related
    assert "| first 3 }}" in related     # three, the width of the home page's card rows
    pelican_site = pelican.build_site(project)
    article = (pelican_site / "theme/templates/article.html").read_text()
    assert "article.related_posts" in article
    # the same neutral heading in both sites: the scoring only guesses
    # at a kinship, so the heading does not head them "Related posts"
    for markup in (related, article):
        assert '<h2 class="page-title">More posts</h2>' in markup
        assert '"page-title">Related posts' not in markup
    namespace = config_namespace(pelican_site)
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
    assert 'alt="A chart of it"' in pelican.figure_directives(shell)
    given = shell.replace("![]", "![Given]")
    assert 'alt="Given"' in hugo.figure_shortcodes(given)
    assert 'alt="Given"' in pelican.figure_directives(given)


def test_intro_reaches_both_landing_pages(project):
    """site.json's "intro" is the landing-page blurb, and belongs on
    both preferred targets. Hugo renders it from content/_index.md; the
    pelican config renders the same Markdown (jinja has no Markdown
    filter of its own) and index.html emits it into the same .intro
    block the shared stylesheet already styles."""
    hugo_site = hugo.build_site(project)
    pelican_site = pelican.build_site(project)
    assert "Welcome." in (hugo_site / "content" / "_index.md").read_text()
    assert '_INTRO_MD = "Welcome."' in (
        pelican_site / "pelicanconf.py").read_text()
    index = (pelican_site / "theme/templates/index.html").read_text()
    assert 'class="intro"' in index and "INTRO" in index


def test_intro_absent_leaves_a_valid_config(project):
    """No intro must leave the config valid Python, the way the avatar
    and announcement keys do -- json.dumps(None) would emit a
    NameError-raising `null`."""
    cfg = json.loads(site_json(project).read_text())
    del cfg["intro"]
    site_json(project).write_text(json.dumps(cfg))
    config = (pelican.build_site(project) / "pelicanconf.py").read_text()
    assert "_INTRO_MD = None" in config


def test_hugo_cards_show_the_curated_description(project):
    """A card's excerpt is the description convert writes, which is what
    the pelican card renders. Hugo's .Summary is its own auto-summary of
    the body, so leaving it first would show a post's opening sentence
    on the card while the other engine showed the subtitle."""
    card = (hugo.build_site(project)
            / "layouts/_partials/card.html").read_text()
    assert "or .Description .Summary" in card


def test_body_images_are_marked_where_only_a_body_image_can_be(project):
    """The post-build pass has to run on the finished HTML: it needs
    output paths to encode variants beside, and pelican leaves {attach}
    unresolved until then (and never resolves it inside a srcset). By
    then a body image and one the theme rendered are the same markup,
    and no path rule separates them -- a related-post card points into
    another post's own images/ directory, exactly where that post's
    body images live. So the distinction is recorded upstream, in the
    reader, which is the counterpart of the hugo theme's render hook:
    every image the reader renders is in an article's body, and a card
    the theme renders never passes through it. The pass keys off the
    mark and strips it, so no reader sees it."""
    site = pelican.build_site(project)
    namespace, md = config_parser(site)
    assert namespace["BODY_IMAGE_ATTR"] == "data-body-image"
    # the path rule this replaced must not creep back: it is what took
    # a card's cover.jpg for a body image
    assert "ARTICLE_IMG" not in namespace and "VARIANT_IMG" not in namespace

    # one definition of the marker in the generated file, which the
    # reader half takes from the plugin half appended after it
    config = (site / "pelicanconf.py").read_text()
    assert config.count("BODY_IMAGE_ATTR = ") == 1

    # the reader really marks what an article's body holds, both the
    # images written as Markdown and the one a figure directive names
    html = md.render("Text.\n\n![pic](images/001-pic.png)\n")
    assert 'data-body-image=""' in html and 'loading="lazy"' in html
    figure = md.render('::: figure src="images/a.png" alt="A"\nCap.\n:::\n')
    assert 'data-body-image=""' in figure and 'loading="lazy"' in figure

    # and the pass takes the mark off whichever way it returns a tag
    # exactly one way out keeps the tag as it stands -- the one for a
    # tag with no mark, which is the theme's; every other return is of
    # the marker-stripped `bare`
    assert "bare = marker_re.sub(" in config
    assert config.count("return tag") == 1

    # an alt holding a ">" (a caption naming a <code> span) must not cut
    # the tag short: that would leave the image unprocessed, its mark on
    tag_re = re.compile(namespace["IMG_TAG"])
    tricky = ('<img alt="a <code>x</code> span" src="/posts/p/images/1.jpg"'
              ' loading="lazy" data-body-image="">')
    assert tag_re.search(tricky).group(0) == tricky


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
    manifest_json(tmp_path).write_text(json.dumps(manifest))
    site_json(tmp_path).write_text(json.dumps({"title": "T"}))
    slugs = [slug for _name, slug in hard]

    # the map both sites are named from: slug -> the name it shows
    assert sites.author_names(manifest) == {s: n for n, s in hard}

    hugo_site = hugo.build_site(tmp_path)
    front = lambda stem: post_front(hugo_site, stem)
    assert [front(f"post-{i}")["authors"][0] for i in range(len(hard))] == slugs
    # the term pages come from that map, so the path stays the slug
    # while the title carries the name
    names = json.loads((hugo_site / "data/authornames.json").read_text())
    assert names == {s: n for n, s in hard}
    adapter = (hugo_site / "content/authors/_content.gotmpl").read_text()
    assert "hugo.Data.authornames" in adapter and '"kind" "term"' in adapter

    pelican_site = pelican.build_site(tmp_path)
    assert [post_front(pelican_site, f"post-{i}")["authors"][0]
            for i in range(len(hard))] == slugs
    # the same map, as the same data file the hugo site got, read back
    # by the config
    assert json.loads((pelican_site / "data/authornames.json").read_text()) \
        == {s: n for n, s in hard}
    namespace = config_namespace(pelican_site)
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


def test_hugo_does_not_publish_the_posts_section_page(project):
    """content/posts/ is a Hugo section, so Hugo would publish a list
    page and a feed for it unasked: /posts/ is the home listing over
    again, pagination and all, canonical to itself and in the sitemap
    while nothing links to it. Pelican has no sections -- posts/<slug>/
    is only a URL pattern there -- so dropping the page is also what
    keeps the two sites' address spaces the same. The posts themselves
    stay exactly where they were."""
    site = hugo.build_site(project)
    section = page_front(site / "content/posts/_index.md")
    assert section["build"] == {"render": "never", "list": "never"}
    # the posts are untouched: the section's own page is all that goes
    assert (site / "content/posts/second-post/index.md").exists()
    assert (site / "content/posts/first-post/index.md").exists()


def test_figure_alt_text_cannot_end_its_own_tag(project):
    """An alt is prose, and prose holds characters that end an HTML tag
    for anything reading it with a regex: a literal ">" ("File -> Hub
    Control Panel"), seen in the archive, ends the img tag early for
    pelican's own intra-site link pass, which then leaves the {attach}
    in src unresolved and the image broken on the page. A Markdown code
    span in an alt is the same problem arrived at from the other
    direction, so both exporters carry the caption's plain text.

    The alt now crosses two boundaries, and each escapes for its own:
    the exporter quotes it for the directive's argument line (the same
    quoting the hugo shortcode call uses, undone by the reader's
    shlex), and the reader escapes it for the attribute it writes."""
    arrow = ("<figure>\n\n![File -> Hub Control Panel](images/a.png)\n\n"
             "<figcaption>\n\nCap.\n\n</figcaption>\n\n</figure>")
    directive = pelican.figure_directives(arrow)
    assert 'alt="File -> Hub Control Panel"' in directive

    code = ("<figure>\n\n![a `p5.js` kernel](images/a.png)\n\n"
            "<figcaption>\n\nCap.\n\n</figcaption>\n\n</figure>")
    assert 'alt="a p5.js kernel"' in pelican.figure_directives(code)
    assert 'alt="a p5.js kernel"' in hugo.figure_shortcodes(code)

    # a quote in an alt would end the argument, so it is escaped for the
    # directive line and comes back whole from the reader's parse
    quoted = ("<figure>\n\n![the \"run\" button](images/a.png)\n\n"
              "<figcaption>\n\nCap.\n\n</figcaption>\n\n</figure>")
    assert r'alt="the \"run\" button"' in pelican.figure_directives(quoted)

    namespace, md = config_parser(pelican.build_site(project))
    tag_re = re.compile(namespace["IMG_TAG"])
    for shell in (arrow, quoted):
        html = md.render(pelican.figure_directives(shell))
        alt = re.search(r'alt="([^"]*)"', html).group(1)
        assert ">" not in alt and "<" not in alt
        img = tag_re.search(html)
        # the tag the post-build pass will read is the whole tag
        assert img.group(0).endswith('data-body-image="">')


def set_redirects(project, mode):
    """site.json's "redirects" set to one mode, for the exporters to read."""
    cfg = json.loads(site_json(project).read_text())
    if mode is None:
        cfg.pop("redirects", None)
    else:
        cfg["redirects"] = mode
    site_json(project).write_text(json.dumps(cfg))


def run_pelican_redirects(site, tmp_path):
    """The generated config's redirect pass, run as a build runs it:
    the site's own redirects.csv into an empty output directory. The
    file it wrote (or None) and the stub paths it wrote."""
    namespace = config_namespace(site)
    output = tmp_path / "output"
    output.mkdir()
    namespace["_write_redirects"](SimpleNamespace(output_path=str(output)))
    stubs = sorted(str(p.parent.relative_to(output))
                   for p in output.rglob("index.html"))
    rules = (output / "_redirects")
    return (rules.read_text() if rules.exists() else None), stubs


def test_redirects_default_to_both_mechanisms(project, tmp_path):
    """Unset, "redirects" leaves both mechanisms in place: the stub
    pages every static host serves, and the `_redirects` file the hosts
    that read one answer with a real 301. That is the default because
    it is the only setting that redirects an old link on a host nobody
    has chosen yet."""
    set_redirects(project, None)
    hugo_site = hugo.build_site(project)
    assert post_front(hugo_site, "first-post")["aliases"] == [
        "/first-post-aaa111aaa111", "/p/aaa111aaa111", "/2015/06/01/first-post"]
    assert (hugo_site / "static/_redirects").exists()

    pelican_site = pelican.build_site(project)
    rules, stubs = run_pelican_redirects(pelican_site, tmp_path)
    assert "/p/aaa111aaa111 /posts/first-post/ 301" in rules
    assert "p/aaa111aaa111" in stubs


def test_redirects_stubs_only_leaves_no_redirects_file(project, tmp_path):
    """"stubs" is what a GitHub Pages deployment wants: it never reads
    `_redirects`, so the file is inert weight there and the stub pages
    are the whole mechanism."""
    set_redirects(project, "stubs")
    hugo_site = hugo.build_site(project)
    assert "aliases" in post_front(hugo_site, "first-post")
    assert not (hugo_site / "static/_redirects").exists()

    pelican_site = pelican.build_site(project)
    assert "REDIRECT_FILE = False" in (pelican_site / "pelicanconf.py").read_text()
    rules, stubs = run_pelican_redirects(pelican_site, tmp_path)
    assert rules is None
    assert "p/aaa111aaa111" in stubs


def test_redirects_file_only_leaves_no_stub_pages(project, tmp_path):
    """"file" is what a Netlify or Cloudflare Pages deployment wants: a
    real HTTP 301 from one text file, and none of the hundreds of stub
    directories the site root would otherwise carry -- which on Netlify
    would shadow the rules and answer in their place."""
    set_redirects(project, "file")
    hugo_site = hugo.build_site(project)
    assert "aliases" not in post_front(hugo_site, "first-post")
    assert "/p/aaa111aaa111 /posts/first-post/ 301" in (
        hugo_site / "static/_redirects").read_text()

    pelican_site = pelican.build_site(project)
    assert "REDIRECT_STUBS = False" in (pelican_site / "pelicanconf.py").read_text()
    rules, stubs = run_pelican_redirects(pelican_site, tmp_path)
    assert "/p/aaa111aaa111 /posts/first-post/ 301" in rules
    assert stubs == []


def test_redirects_none_still_writes_the_map(project, tmp_path):
    """"none" leaves the redirects to a rule set kept somewhere else --
    and still writes redirects.csv, which is what such a rule set is
    built from."""
    set_redirects(project, "none")
    hugo_site = hugo.build_site(project)
    assert "aliases" not in post_front(hugo_site, "first-post")
    assert not (hugo_site / "static/_redirects").exists()
    assert (hugo_site / "redirects.csv").exists()

    pelican_site = pelican.build_site(project)
    assert (pelican_site / "redirects.csv").exists()
    rules, stubs = run_pelican_redirects(pelican_site, tmp_path)
    assert rules is None and stubs == []


def test_an_unknown_redirects_value_is_reported_and_ignored(project, capsys):
    """A typo must not silently drop every redirect the site serves."""
    set_redirects(project, "netlify")
    hugo_site = hugo.build_site(project)
    assert "'netlify' is not one of" in capsys.readouterr().err
    assert "aliases" in post_front(hugo_site, "first-post")
    assert (hugo_site / "static/_redirects").exists()
