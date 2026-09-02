"""The myst step: posts/ + posts.json -> a MyST site in site-myst/."""

import json
from pathlib import Path

import pytest

from medium_archive.myst import (LinkMap, build_site, escape_prose,
                                 myst_figures, myst_slug, page_paths,
                                 page_stems, rewrite_body)

BASE = "https://blog.example.com"
PNG_HEADER = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
              + (800).to_bytes(4, "big") + (450).to_bytes(4, "big")
              + b"\x00" * 8)


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
              f"Hello. See [the sequel]({BASE}/second-post-bbb222bbb222).\n")
    second = tmp_path / "posts/2021-03-01-second-post"
    make_post(tmp_path, manifest, "second-post", "bbb222bbb222",
              "2021-03-01T10:00:00Z",
              "An image:\n\n![pic](images/001-pic.png)\n",
              images=["images/001-pic.png"])
    (second / "images").mkdir()
    # a png header with no pixel data: a cover has to sniff as a raster
    # format, and Pillow cannot decode this, so it is copied in unchanged
    (second / "images" / "001-pic.png").write_bytes(PNG_HEADER)
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    return tmp_path, manifest


def test_pages_images_and_toc(archive):
    out, manifest = archive
    site = build_site(out)

    page = site / "posts/2021-03-01-second-post/second-post.md"
    text = page.read_text()
    assert text.startswith('---\ntitle: "Second Post"\n')
    assert 'date: "2021-03-01"' in text          # bare date, no time component
    assert 'authors:\n  - name: "Ada Lovelace"\n    url: "https://medium.com/@ada"' in text
    assert 'tags: ["example"]' in text
    assert "![pic](images/001-pic.png)" in text
    assert (page.parent / "images/001-pic.png").read_bytes() == PNG_HEADER
    # the first image becomes the page's thumbnail (its gallery card);
    # bytes that defeat the Pillow bake make cover.jpg a plain copy
    assert 'thumbnail: "images/cover.jpg"' in text
    assert (page.parent / "images/cover.jpg").read_bytes() == PNG_HEADER
    first = (site / "posts/2020-01-05-first-post/first-post.md").read_text()
    assert "thumbnail" not in first            # no images, no cover card
    # archive provenance stays out of site front matter
    assert "medium_id" not in text and "body_source" not in text

    yml = (site / "myst.yml").read_text()
    assert "template: book-theme" in yml
    # the gallery plugin, then the local cover transform (order matters)
    assert yml.index("myst-listing") < yml.index("listing-covers.mjs")
    assert (site / "listing-covers.mjs").exists()
    # years newest first, one child file per post
    assert yml.index('- title: "2021"') < yml.index('- title: "2020"')
    assert "- file: posts/2021-03-01-second-post/second-post.md" in yml
    assert "- file: posts/2020-01-05-first-post/first-post.md" in yml

    # the landing page is the gallery; the chronological list moved to
    # archive.md, which the toc lists after it
    index = (site / "index.md").read_text()
    assert ":::{listing}" in index and ":display: gallery" in index
    assert ":limit: 0" in index                 # every post, not the default 10
    assert "(archive.md)" in index
    assert yml.index("- file: index.md") < yml.index("- file: archive.md")
    archive_page = (site / "archive.md").read_text()
    assert "[Second Post](posts/2021-03-01-second-post/second-post.md)" \
        in archive_page
    assert "## 2021" in archive_page and "## 2020" in archive_page


def test_internal_links_rewritten(archive):
    out, _ = archive
    site = build_site(out)
    text = (site / "posts/2020-01-05-first-post/first-post.md").read_text()
    assert "(../2021-03-01-second-post/second-post.md)" in text
    assert "second-post-bbb222bbb222" not in text


def test_shared_slugs_keep_date_prefix(tmp_path):
    manifest = {}
    make_post(tmp_path, manifest, "workshops", "aaa111aaa111",
              "2019-06-01T00:00:00Z", "One.\n")
    make_post(tmp_path, manifest, "unique-post", "ccc333ccc333",
              "2019-07-01T00:00:00Z", "Two.\n")
    # same slug under a new id: deleted and republished
    manifest2 = {}
    make_post(tmp_path, manifest2, "workshops", "bbb222bbb222",
              "2020-06-01T00:00:00Z", "Three.\n")
    manifest.update(manifest2)
    stems = page_stems(manifest)
    assert sorted(stems.values()) == ["2019-06-01-workshops",
                                      "2020-06-01-workshops", "unique-post"]


def test_link_map_matches_url_variants():
    manifest = {f"{BASE}/a-post-abc123abc123": {
        "dir": "posts/2020-01-01-a-post", "slug": "a-post",
        "original_url": f"{BASE}/a-post-abc123abc123",
        "ghost_url": f"{BASE}/2015/06/01/a-post",
        "canonical_url": None, "medium_id": "abc123abc123",
        "date": "2020-01-01T00:00:00Z"}}
    links = LinkMap(manifest, page_stems(manifest))
    page = ("2020-01-01-a-post", "a-post")
    for url in (f"{BASE}/a-post-abc123abc123",           # canonical
                f"{BASE}/a-post-abc123abc123/",          # trailing slash
                BASE.replace("https", "http") + "/a-post-abc123abc123",
                f"{BASE}/p/abc123abc123",                # short form
                "https://medium.com/blog/a-post-abc123abc123",  # other host, same id
                f"{BASE}/2015/06/01/a-post"):            # Ghost era
        assert links.page_for(url) == (*page, ""), url
    assert links.page_for(f"{BASE}/a-post-abc123abc123#notes") == (*page, "notes")
    assert links.page_for("https://example.org/elsewhere") is None


def test_rewrite_leaves_fences_and_autolinks_external(archive):
    out, manifest = archive
    links = LinkMap(manifest, page_stems(manifest))
    md = (f"See <{BASE}/first-post-aaa111aaa111>\n"
          "```\n"
          f"[in a fence]({BASE}/first-post-aaa111aaa111)\n"
          "```\n"
          "[outside](https://example.org/other)\n")
    got = rewrite_body(md, links, "../")
    # the autolink keeps its visible URL but points at the site page
    assert (f"[{BASE}/first-post-aaa111aaa111]"
            "(../2020-01-05-first-post/first-post.md)") in got
    assert f"[in a fence]({BASE}/first-post-aaa111aaa111)" in got
    assert "[outside](https://example.org/other)" in got


def test_redirects_and_site_json(archive):
    out, _ = archive
    (out / "site.json").write_text(json.dumps(
        {"title": "Example Blog", "description": "An example.",
         "intro": "Welcome to the archive."}))
    site = build_site(out)
    yml = (site / "myst.yml").read_text()
    assert 'title: "Example Blog"' in yml and 'description: "An example."' in yml
    assert "Welcome to the archive." in (site / "index.md").read_text()
    rows = (site / "redirects.csv").read_text().splitlines()
    assert rows[0] == "old_path,new_path,original_url"
    assert f"/first-post-aaa111aaa111,/first-post,{BASE}/first-post-aaa111aaa111" in rows
    assert f"/p/aaa111aaa111,/first-post,{BASE}/first-post-aaa111aaa111" in rows


def test_figure_shell_becomes_a_figure_directive():
    md = ("Intro.\n\n<figure>\n\n![Alt text](images/001-a.gif)\n\n"
          "<figcaption>\n\n*A caption with a [link](https://e.com).*\n\n"
          "</figcaption>\n\n</figure>\n\nAfter.\n")
    assert myst_figures(md) == (
        "Intro.\n\n:::{figure} images/001-a.gif\n:alt: Alt text\n\n"
        "*A caption with a [link](https://e.com).*\n:::\n\nAfter.\n")
    # no alt, no :alt: option line
    md = ("<figure>\n\n![](images/a.png)\n\n<figcaption>\n\n*Cap.*\n\n"
          "</figcaption>\n\n</figure>\n")
    assert myst_figures(md) == ":::{figure} images/a.png\n\n*Cap.*\n:::\n"


def test_non_image_figure_shell_is_dropped_for_myst():
    # mystmd is not guaranteed to render raw HTML: a shell that is not a
    # single captioned image loses the tags but keeps what they wrapped
    md = ("<figure>\n\n[embed: https://u](https://u)\n\n<figcaption>\n\n"
          "*Cap.*\n\n</figcaption>\n\n</figure>\n")
    out = myst_figures(md)
    assert "<" not in out
    assert "[embed: https://u](https://u)\n\n*Cap.*" in out


def test_escape_prose_for_myst():
    # @handles would parse as MyST citations, $...$ as dollar math
    assert escape_prose("Thanks @jtpio and [@SylvainCorlay]!") == \
        "Thanks \\@jtpio and [\\@SylvainCorlay]!"
    assert escape_prose("grants of $10,000 to $20,000") == \
        "grants of \\$10,000 to \\$20,000"
    # but not inside inline code, link destinations, or autolinks --
    # and an email's @ is not a mention
    for line in ("run `pip install $PKG` for @{sign}".replace("@{sign}", "x"),
                 "[profile](https://medium.com/@ada)",
                 "<https://example.com/$x>",
                 "mail jupyter@googlegroups.com"):
        assert escape_prose(line) == line
    assert escape_prose("`@jtpio` and @jtpio") == "`@jtpio` and \\@jtpio"
    # a doubled @@ still hides its handle from the citation parser
    assert escape_prose("**@@cell** sentinels") == "**@\\@cell** sentinels"


def test_mononym_author_is_literal(tmp_path):
    manifest = {}
    make_post(tmp_path, manifest, "solo", "abc123abc123",
              "2020-01-01T00:00:00Z", "Hi.\n", author="yuvipanda")
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    site = build_site(tmp_path)
    text = (site / "posts/2020-01-01-solo/solo.md").read_text()
    assert 'authors:\n  - name:\n      literal: "yuvipanda"\n' in text


def test_myst_slug_mirrors_mystmd():
    # unchanged: already a short [a-z0-9-] slug
    assert myst_slug("first-post") == "first-post"
    # non-ascii collapses to '-', like mystmd's createSlug
    assert myst_slug("voilà-0-5-0-homecoming") == "voil-0-5-0-homecoming"
    # a leading enumeration is stripped, but a year is kept
    assert myst_slug("700-jupyterlab-4-extensions") == "jupyterlab-4-extensions"
    assert myst_slug("2026-06-24-congratulations-post") == \
        "2026-06-24-congratulations-post"
    # capped at 50 characters after the trim, so a '-' can survive at the end
    long = "a-users-journey-with-plugin-playground-from-first-idea"
    assert myst_slug(long) == long[:50] and myst_slug(long).endswith("-")


def test_page_paths_number_collisions_in_toc_order(tmp_path):
    manifest = {}
    # both truncate to the same 50-character slug; mystmd numbers the one
    # it loads second -- the older post, in the newest-first toc
    base = "join-us-for-the-jupyter-accessibility-workshops-part"
    make_post(tmp_path, manifest, base + "-1", "aaa111aaa111",
              "2022-08-01T00:00:00Z", "One.\n")
    make_post(tmp_path, manifest, base + "-2", "bbb222bbb222",
              "2022-11-01T00:00:00Z", "Two.\n")
    # a post literally named archive collides with the archive page
    make_post(tmp_path, manifest, "archive", "ccc333ccc333",
              "2023-01-01T00:00:00Z", "Three.\n")
    stems = page_stems(manifest)
    paths = page_paths(manifest, stems)
    trunc = myst_slug(base + "-2")
    assert trunc == myst_slug(base + "-1")     # they do collide
    assert paths[base + "-2"] == f"/{trunc}"
    assert paths[base + "-1"] == f"/{trunc}-1"
    assert paths["archive"] == "/archive-1"


def test_redirects_use_served_urls(tmp_path):
    manifest = {}
    slug = "announcing-jupyter-builder-a-standalone-build-system"
    make_post(tmp_path, manifest, slug, "aaa111aaa111",
              "2026-06-19T00:00:00Z", "Hi.\n")
    (tmp_path / "posts.json").write_text(json.dumps(manifest))
    site = build_site(tmp_path)
    rows = (site / "redirects.csv").read_text()
    # the page file keeps the full slug; the redirect target is the
    # 50-character URL mystmd will actually serve
    assert (site / f"posts/2026-06-19-{slug}/{slug}.md").exists()
    assert f",/{slug[:50]}," in rows and f",/{slug}," not in rows


def test_missing_manifest_exits(tmp_path):
    with pytest.raises(SystemExit):
        build_site(tmp_path)


def test_tags_carry_their_display_names(archive):
    """MyST has no tag pages, so nothing derives a URL from a tag and the
    front matter carries the name a reader would see."""
    out, manifest = archive
    (out / "tags.json").write_text(json.dumps(
        {"display": {"example": "Example Tag"}}), encoding="utf-8")
    site = build_site(out)
    text = (site / "posts/2021-03-01-second-post/second-post.md").read_text()
    assert 'tags: ["Example Tag"]' in text
