"""The hugo, zola, and pelican steps: posts/ + posts.json -> a site."""

import json
from pathlib import Path

import pytest

from medium_archive import hugo, pelican, zola

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
    assert (site / "layouts/_default/single.html").exists()
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
    # the theme brings its own layouts; Dream's extra pages are created
    assert not (site / "layouts").exists()
    assert (site / "content/search/_index.md").exists()
    assert "Archives" in (site / "content/posts/_index.md").read_text()
    front = json.loads((site / "content/posts/second-post/index.md")
                       .read_text().split("\n\n", 1)[0])
    assert front["cover"] == "images/001-pic.png"
    assert front["images"] == ["images/001-pic.png"]
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


def test_zola_site(archive):
    site = zola.build_site(archive)
    text = (site / "content/posts/second-post/index.md").read_text()
    assert text.startswith('+++\ntitle = "Second Post"\n'
                           'slug = "second-post"\n')
    assert "date = 2021-03-01T10:00:00Z" in text        # TOML datetime
    assert '[taxonomies]\ntags = ["example"]\nauthors = ["Ada Lovelace"]' in text
    assert 'aliases = ["/second-post-bbb222bbb222", "/p/bbb222bbb222"]' in text
    config = (site / "config.toml").read_text()
    assert 'base_url = "https://blog.example.org"' in config   # no trailing /
    assert "build_search_index = true" in config
    assert '{ name = "authors", feed = true }' in config
    assert (site / "templates/page.html").exists()
    assert (site / "content/posts/_index.md").read_text().count("sort_by")


def test_pelican_site(archive):
    (archive / "logo.png").write_bytes(b"IMG")
    cfg = json.loads((archive / "site.json").read_text())
    cfg["avatar"] = "logo.png"
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
    assert 'THEME = "theme"' in config
    assert '"search.html": "search/index.html"' in config
    assert "_LazyImages" in config           # body images load lazily
    assert 'AVATAR = "theme/img/avatar.png"' in config
    assert (site / "theme/static/img/avatar.png").read_bytes() == b"IMG"
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


def test_build_output_survives_regeneration(archive):
    for module, kept in ((hugo, "public"), (zola, "public"),
                         (pelican, "output")):
        site = module.build_site(archive)
        (site / kept).mkdir()
        (site / kept / "index.html").write_text("built")
        module.build_site(archive)
        assert (site / kept / "index.html").read_text() == "built"
