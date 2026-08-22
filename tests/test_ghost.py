"""import-ghost: Wayback discovery, Ghost page detection, twin attachment,
and conversion."""

import json
from types import SimpleNamespace

from bs4 import BeautifulSoup

from _fakes import FakeResp, FakeSession
from medium_archive import compare as comparemod
from medium_archive import convert as convertmod
from medium_archive import ghost as ghostmod
from medium_archive.pages import ghost_body, ghost_metadata, is_ghost_page

BASE = "http://blog.example.com/"

GHOST_POST = """<html><head>
<title>Hello World</title>
<link rel="canonical" href="http://blog.example.com/2015/03/04/hello-world/" />
<meta property="og:site_name" content="Example" />
<meta property="og:type" content="article" />
<meta property="og:title" content="Hello World" />
<meta property="og:description" content="A first post" />
<meta property="article:published_time" content="2015-03-04T10:00:00.000Z" />
<meta name="generator" content="Ghost 0.5" />
</head><body><main><article class="post tag-news">
<header class="post-header"><h1 class="post-title">Hello World</h1>
<section class="post-meta"><time class="post-date" datetime="2015-03-04">04 March 2015</time></section>
</header>
<section class="post-content"><p>Body text with an
<img src="/content/images/2015/03/pic.png" alt="pic" />.</p>
<script>tracker()</script></section>
<footer class="post-footer">
<section class="author"><h4><a href="/author/ann/">Ann Author</a></h4>
<p>Read <a href="/author/ann/">more posts</a> by this author.</p></section>
<section class="share"><a href="#">Share</a></section></footer>
</article></main></body></html>"""

MIGRATED_POST = """<html><head>
<meta property="og:type" content="article" />
<meta property="og:title" content="Migrated Post" />
<meta property="article:published_time" content="2015-05-05T09:00:00.000Z" />
<meta name="generator" content="Ghost 0.5" />
</head><body><article class="post">
<section class="post-content"><p>Original Ghost body with proper code.</p></section>
</article></body></html>"""

OLD_SLUG_POST = """<html><head>
<meta property="og:type" content="article" />
<meta property="og:title" content="A Retitled Post" />
<meta name="generator" content="Ghost 0.5" />
</head><body><article class="post">
<section class="post-content"><p>Old slug body.</p></section>
</article></body></html>"""

# a Medium rendering of the migrated post, for the twin's page.html
MEDIUM_PAGE = """<html><head><script type="application/ld+json">
{"@type": "NewsArticle", "headline": "Migrated Post",
 "author": {"name": "Ann Author"}, "datePublished": "2015-05-05T00:00:00Z"}
</script></head><body><article><p>Mangled Medium body.</p></article></body></html>"""

# what a Ghost-era path looks like once the domain serves Medium
MEDIUM_404 = "<html><head><title>Not found</title></head><body>gone</body></html>"

CDX = """\
http://blog.example.com:80/2015/03/04/hello-world/ 20150401000000
http://blog.example.com/2015/03/04/hello-world/ 20180101000000
http://blog.example.com/2015/05/05/migrated/ 20150601000000
http://blog.example.com/2015/06/06/old-slug/ 20150701000000
http://blog.example.com/tag/news/ 20150401000000
http://blog.example.com/assets/css/screen.css 20150401000000
http://blog.example.com/2015/03/04/hello-world/amp 20170801000000
http://blog.example.com/some-medium-post-0123456789ab 20180101000000
http://blog.example.com/ 20150401000000
"""

SNAPSHOTS = {
    # newest capture of the post is Medium-era junk; the older one is Ghost
    "20180101000000id_/http://blog.example.com/2015/03/04/hello-world": MEDIUM_404,
    "20150401000000id_/http://blog.example.com/2015/03/04/hello-world": GHOST_POST,
    "20150601000000id_/http://blog.example.com/2015/05/05/migrated": MIGRATED_POST,
    "20150701000000id_/http://blog.example.com/2015/06/06/old-slug": OLD_SLUG_POST,
}


def router(url):
    if "cdx/search/cdx" in url:
        return FakeResp(CDX)
    if "im_/" in url:
        return FakeResp(content=b"PNG")
    for key, html in SNAPSHOTS.items():
        if key in url:
            return FakeResp(html)
    return FakeResp(status=404)


def test_may_be_post():
    assert ghostmod.may_be_post("/2015/03/04/hello-world/")
    assert ghostmod.may_be_post("/plain-slug/")
    for path in ("/", "/tag/news/", "/author/ann/", "/assets/css/screen.css",
                 "/2015/03/04/hello-world/amp", "/rss/", "/sitemap.xml",
                 "/some-medium-post-0123456789ab", "/content/images/x.png",
                 "/p/0123456789ab", "/@someuser/some-post"):
        assert not ghostmod.may_be_post(path), path


def test_ghost_page_parsing():
    soup = BeautifulSoup(GHOST_POST, "html.parser")
    assert is_ghost_page(soup)
    assert ghostmod.is_ghost_post(soup)
    info = ghost_metadata(soup, "http://x/")
    assert info["title"] == "Hello World"
    assert info["date"] == "2015-03-04T10:00:00.000Z"
    assert info["author"] == "Ann Author"
    assert info["author_url"] == "http://blog.example.com/author/ann/"
    assert info["tags"] == ["news"]
    assert info["description"] == "A first post"
    body = ghost_body(soup)
    text = body.get_text()
    assert "Body text" in text
    assert "tracker" not in text and "Share" not in text and "Hello World" not in text
    # non-post Ghost pages (front page, tag pages) are rejected
    front = BeautifulSoup('<meta name="generator" content="Ghost 0.5" />', "html.parser")
    assert is_ghost_page(front) and not ghostmod.is_ghost_post(front)
    assert not is_ghost_page(BeautifulSoup(MEDIUM_404, "html.parser"))


def run_import(out, monkeypatch, **overrides):
    session = FakeSession(router=router)
    monkeypatch.setattr(ghostmod, "make_session", lambda: session)
    args = dict(out=out, base=BASE, urls=None, limit=0, force=False,
                delay=0, no_images=False)
    ghostmod.cmd_import_ghost(SimpleNamespace(**{**args, **overrides}))
    return session


MIGRATED_URL = "http://blog.example.com/migrated-post-abcdef123456"
OLD_SLUG_URL = "http://blog.example.com/old-slug-abcdefabcdef"


def seed_index(out):
    (out / "raw").mkdir(parents=True)
    (out / "raw" / "index.json").write_text(json.dumps({
        MIGRATED_URL: {"medium_id": "abcdef123456", "title": "Migrated Post"},
        OLD_SLUG_URL: {"medium_id": "abcdefabcdef", "title": "A Retitled Post"},
    }))
    (out / "raw" / "abcdef123456").mkdir()
    (out / "raw" / "abcdef123456" / "page.html").write_text(MEDIUM_PAGE)


def test_import_ghost_attach_and_convert(tmp_path, monkeypatch):
    seed_index(tmp_path)
    session = run_import(tmp_path, monkeypatch)

    index = json.loads((tmp_path / "raw" / "index.json").read_text())
    url = "http://blog.example.com/2015/03/04/hello-world"

    # a post with no archived counterpart becomes a post of its own
    entry = index[url]
    assert entry["medium_id"] == "ghost-hello-world"
    assert entry["found_via"] == "ghost-wayback"
    assert entry["published"] == "2015-03-04T10:00:00.000Z"
    assert entry["wayback_url"] == f"https://web.archive.org/web/20150401000000/{url}"
    assert entry["images"] == 1
    raw = tmp_path / "raw" / "ghost-hello-world"
    assert "Ghost 0.5" in (raw / "page.html").read_text()
    assert json.loads((raw / "ghost.json").read_text())["generator"] == "Ghost 0.5"
    img_map = json.loads((raw / "images.json").read_text())
    fname = img_map["/content/images/2015/03/pic.png"]
    assert (raw / "images" / fname).read_bytes() == b"PNG"

    # twins (matched by title or slug) get the capture attached to the
    # archived post's directory, not imported as separate posts
    for ghost_url, medium_url in [
            ("http://blog.example.com/2015/05/05/migrated", MIGRATED_URL),
            ("http://blog.example.com/2015/06/06/old-slug", OLD_SLUG_URL)]:
        assert ghost_url not in index
        twin = index[medium_url]
        assert twin["in_ghost"] is True and twin["ghost_url"] == ghost_url
        twin_raw = tmp_path / "raw" / twin["medium_id"]
        assert "Ghost 0.5" in (twin_raw / "ghost.html").read_text()
        assert json.loads((twin_raw / "ghost.json").read_text())["original_url"] == ghost_url

    # non-post URLs (tag, asset, amp, front page, Medium-era) never requested
    snapshot_calls = [c for c in session.calls if "id_/" in c]
    assert not any("/tag/" in c or "/assets/" in c or "/amp" in c
                   or "0123456789ab" in c for c in snapshot_calls)

    # standalone ghost posts convert as before
    convertmod.cmd_convert(SimpleNamespace(out=tmp_path, prefer_page=False,
                                           prefer_ghost=False, only=[url],
                                           clean=False, base=None))
    md = (tmp_path / "posts" / "2015-03-04-hello-world" / "index.md").read_text()
    assert "Body text" in md and f"images/{fname}" in md
    assert '"body_source": "ghost"' in md
    assert '"ghost_url": null' in md    # original_url IS the ghost URL

    # a twin converts from the Medium page by default...
    convertmod.cmd_convert(SimpleNamespace(out=tmp_path, prefer_page=False,
                                           prefer_ghost=False, only=[MIGRATED_URL],
                                           clean=False, base=None))
    md = (tmp_path / "posts" / "2015-05-05-migrated-post" / "index.md").read_text()
    assert "Mangled Medium body" in md and '"body_source": "page"' in md
    assert '"ghost_url": "http://blog.example.com/2015/05/05/migrated"' in md

    # ...and from the attached Ghost capture with --prefer-ghost
    convertmod.cmd_convert(SimpleNamespace(out=tmp_path, prefer_page=False,
                                           prefer_ghost=True, only=[MIGRATED_URL],
                                           clean=False, base=None))
    md = (tmp_path / "posts" / "2015-05-05-migrated-post" / "index.md").read_text()
    assert "Original Ghost body" in md and '"body_source": "ghost"' in md

    # redirects.csv carries a second row for the Ghost path
    redirects = (tmp_path / "redirects.csv").read_text()
    assert "/2015/05/05/migrated,abcdef123456," in redirects
    assert "/migrated-post-abcdef123456,abcdef123456," in redirects

    # compare --ghost reports the difference without gating (no SystemExit)
    comparemod.cmd_compare(SimpleNamespace(out=tmp_path, only=None, ghost=True))


def test_import_ghost_rerun_is_idempotent(tmp_path, monkeypatch):
    seed_index(tmp_path)
    run_import(tmp_path, monkeypatch)
    before = (tmp_path / "raw" / "index.json").read_text()
    session = run_import(tmp_path, monkeypatch)
    assert (tmp_path / "raw" / "index.json").read_text() == before
    assert not any("id_/" in c for c in session.calls)   # nothing re-fetched
