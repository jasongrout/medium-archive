"""The myst step: posts/ + posts.json -> a MyST site in site/."""

import json
from pathlib import Path

import pytest

from medium_archive.myst import (LinkMap, build_site, escape_prose,
                                 page_stems, rewrite_body)

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
              f"Hello. See [the sequel]({BASE}/second-post-bbb222bbb222).\n")
    second = tmp_path / "posts/2021-03-01-second-post"
    make_post(tmp_path, manifest, "second-post", "bbb222bbb222",
              "2021-03-01T10:00:00Z",
              "An image:\n\n![pic](images/001-pic.png)\n")
    (second / "images").mkdir()
    (second / "images" / "001-pic.png").write_bytes(b"PNG")
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
    assert (page.parent / "images/001-pic.png").read_bytes() == b"PNG"
    # archive provenance stays out of site front matter
    assert "medium_id" not in text and "body_source" not in text

    yml = (site / "myst.yml").read_text()
    assert "template: book-theme" in yml
    # years newest first, one child file per post
    assert yml.index('- title: "2021"') < yml.index('- title: "2020"')
    assert "- file: posts/2021-03-01-second-post/second-post.md" in yml
    assert "- file: posts/2020-01-05-first-post/first-post.md" in yml

    index = (site / "index.md").read_text()
    assert "[Second Post](posts/2021-03-01-second-post/second-post.md)" in index
    assert "## 2021" in index and "## 2020" in index


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


def test_missing_manifest_exits(tmp_path):
    with pytest.raises(SystemExit):
        build_site(tmp_path)
