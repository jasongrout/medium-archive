"""cmd_fetch: flagging gone posts in raw/missing.json, and looks_gone."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import requests

from _fakes import FakeResp, FakeSession
from medium_archive import fetch as fetchmod

BASE = "https://blog.example.com/"
GOOD = "https://blog.example.com/good-post-111122223333"
GONE = "https://blog.example.com/gone-post-0123456789ab"
SOFT = "https://blog.example.com/soft-gone-post-aaaabbbbcccc"
APPROX = datetime(2018, 5, 1, tzinfo=timezone.utc)


def run_fetch(out, gone_now, monkeypatch):
    monkeypatch.setattr(fetchmod, "discover", lambda session, base, raw_dir, wayback=True: (
        [(GOOD, None, "sitemap"), (GONE, APPROX, "wayback"), (SOFT, None, "wayback")], {}))

    def fake_fetch_post(session, url, dest, feed_item, delay, images):
        if url == GONE and gone_now:
            raise requests.HTTPError("404 error", response=FakeResp(status=404))
        if url == SOFT:
            raise fetchmod.PostGone("soft-404")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "page.html").write_text("<html></html>")
        return {"published": "2018-05-01T00:00:00Z", "title": "T", "image_count": 0}

    monkeypatch.setattr(fetchmod, "fetch_post", fake_fetch_post)
    monkeypatch.setattr(fetchmod, "make_session", lambda: FakeSession())
    fetchmod.cmd_fetch(SimpleNamespace(
        out=out, base=BASE, urls=None, no_wayback=False, start=None, end=None,
        oldest_first=False, limit=0, existing=None, force=False, delay=0,
        no_images=True))


def test_gone_posts_flagged_then_unflagged(tmp_path, monkeypatch):
    run_fetch(tmp_path, gone_now=True, monkeypatch=monkeypatch)
    missing = json.loads((tmp_path / "raw" / "missing.json").read_text())
    assert set(missing) == {GONE, SOFT}
    assert missing[GONE]["status"] == 404
    assert missing[GONE]["medium_id"] == "0123456789ab"
    assert missing[GONE]["found_via"] == "wayback"
    assert missing[GONE]["wayback_url"] == \
        f"https://web.archive.org/web/20180501000000/{GONE}"
    assert missing[SOFT]["status"] == "soft-404"
    index = json.loads((tmp_path / "raw" / "index.json").read_text())
    assert index[GOOD]["found_via"] == "sitemap"
    assert GONE not in index and SOFT not in index

    # the 404 post reappears on a later run: unflagged and archived; the
    # soft-404 one is still gone and stays flagged
    run_fetch(tmp_path, gone_now=False, monkeypatch=monkeypatch)
    missing = json.loads((tmp_path / "raw" / "missing.json").read_text())
    assert set(missing) == {SOFT}
    index = json.loads((tmp_path / "raw" / "index.json").read_text())
    assert index[GONE]["found_via"] == "wayback"


def test_looks_gone():
    assert fetchmod.looks_gone("<html><h1>PAGE NOT FOUND</h1></html>")
    # a real post always carries an ld+json metadata block...
    assert not fetchmod.looks_gone('<script type="application/ld+json">{}</script><p>body</p>')
    # ...so even a body mentioning the phrase is not a false positive
    assert not fetchmod.looks_gone('<script type="application/ld+json">{}</script>PAGE NOT FOUND')


def gist_page(mid):
    """A page whose state has a gist embed: an IFRAME media resource
    with an empty iframeSrc."""
    state = {
        f"Post:{mid}": {"id": mid, 'content({"a":1})': {"bodyModel": {
            "paragraphs": [{"__ref": "Paragraph:p0"}]}}},
        "Paragraph:p0": {"type": "IFRAME", "text": "", "markups": [],
                         "iframe": {"mediaResource": {"__ref": "MediaResource:m1"}}},
        "MediaResource:m1": {"id": "cafe01", "iframeSrc": "", "title": "a.py"},
    }
    return "<script>window.__APOLLO_STATE__ = " + json.dumps(state) + "</script>"


def media_router(url):
    if url == fetchmod.MEDIA_URL.format(id="cafe01"):
        return FakeResp("])}while(1);</x>" + json.dumps(
            {"payload": {"value": {"gist": {"gistId": "g123"}}}}))
    if url == fetchmod.GIST_API_URL.format(id="g123"):
        return FakeResp(json.dumps(
            {"files": {"a.py": {"language": "Python", "content": "x = 1"}}}))
    raise AssertionError(f"unexpected fetch: {url}")


def test_fetch_media_archives_gist_embeds(tmp_path):
    mid = "111122223333"
    session = FakeSession(router=media_router)
    dest = tmp_path / mid
    assert fetchmod.fetch_media(session, gist_page(mid), mid, dest, 0) == 2
    payload = json.loads((dest / "media" / "cafe01.json").read_text())
    assert payload["payload"]["value"]["gist"]["gistId"] == "g123"
    gist = json.loads((dest / "media" / "cafe01.gist.json").read_text())
    assert gist["files"]["a.py"]["content"] == "x = 1"
    # incremental: a second run touches neither endpoint again
    assert fetchmod.fetch_media(session, gist_page(mid), mid, dest, 0) == 0
    assert len(session.calls) == 2


def test_fetch_backfills_media_for_archived_posts(tmp_path, monkeypatch):
    # the post was archived before embed media existed; a re-run fetches
    # just the media, without re-fetching the post
    run_fetch(tmp_path, gone_now=True, monkeypatch=monkeypatch)
    pid = "111122223333"
    (tmp_path / "raw" / pid / "page.html").write_text(gist_page(pid))

    monkeypatch.setattr(fetchmod, "discover",
                        lambda session, base, raw_dir, wayback=True: (
                            [(GOOD, None, "sitemap")], {}))
    monkeypatch.setattr(fetchmod, "make_session",
                        lambda: FakeSession(router=media_router))

    def fail_fetch_post(*a, **kw):
        raise AssertionError("archived post must not be re-fetched")

    monkeypatch.setattr(fetchmod, "fetch_post", fail_fetch_post)
    fetchmod.cmd_fetch(SimpleNamespace(
        out=tmp_path, base=BASE, urls=None, no_wayback=False, start=None,
        end=None, oldest_first=False, limit=0, existing=None, force=False,
        delay=0, no_images=True))
    assert (tmp_path / "raw" / pid / "media" / "cafe01.json").exists()
    assert (tmp_path / "raw" / pid / "media" / "cafe01.gist.json").exists()


GIPHY = "https://media.giphy.com/media/fWgAW7WZtPMBjmpa3V/giphy.gif"


def giphy_page(mid):
    """A page whose state has a Giphy embed (an embedly wrapper naming
    the gif) and a YouTube one, which is not an asset."""
    state = {
        f"Post:{mid}": {"id": mid, 'content({"a":1})': {"bodyModel": {
            "paragraphs": [{"__ref": "Paragraph:p0"}, {"__ref": "Paragraph:p1"}]}}},
        "Paragraph:p0": {"type": "IFRAME", "text": "", "markups": [],
                         "iframe": {"mediaResource": {"__ref": "MediaResource:m1"}}},
        "Paragraph:p1": {"type": "IFRAME", "text": "", "markups": [],
                         "iframe": {"mediaResource": {"__ref": "MediaResource:m2"}}},
        "MediaResource:m1": {"id": "a1", "title": "A gif", "iframeSrc":
                             "https://cdn.embedly.com/widgets/media.html?src=https%3A%2F%2F"
                             "giphy.com%2Fembed%2FfWgAW7WZtPMBjmpa3V%2Ftwitter%2Fiframe&url="
                             "https%3A%2F%2Fmedia.giphy.com%2Fmedia%2FfWgAW7WZtPMBjmpa3V%2Fgiphy.gif"},
        "MediaResource:m2": {"id": "a2", "title": "A talk", "iframeSrc":
                             "https://cdn.embedly.com/widgets/media.html?url="
                             "https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabcdefghijk"},
    }
    return "<script>window.__APOLLO_STATE__ = " + json.dumps(state) + "</script>"


def test_embed_assets_are_fetched_with_the_images_and_backfilled(tmp_path):
    mid = "111122223333"
    assert fetchmod.embed_asset_urls(giphy_page(mid), mid) == [GIPHY]
    session = FakeSession(router=lambda url: FakeResp(content=b"GIF89a")
                          if url == GIPHY else (_ for _ in ()).throw(AssertionError(url)))
    dest = tmp_path / mid
    dest.mkdir()
    (dest / "images.json").write_text(json.dumps({"https://x/a.png": "001-a.png"}))
    # a post archived before embed assets existed: the gif joins images/
    # and images.json after what is already there
    assert fetchmod.backfill_embed_assets(session, giphy_page(mid), mid, dest, 0) == 1
    assert json.loads((dest / "images.json").read_text()) == {
        "https://x/a.png": "001-a.png", GIPHY: "002-fWgAW7WZtPMBjmpa3V-giphy.gif"}
    assert (dest / "images" / "002-fWgAW7WZtPMBjmpa3V-giphy.gif").read_bytes() == b"GIF89a"
    # incremental: nothing to do the second time
    assert fetchmod.backfill_embed_assets(session, giphy_page(mid), mid, dest, 0) == 0
    assert session.calls == [GIPHY]


def test_urls_file_may_name_archived_posts(tmp_path):
    # a Medium id or a converted post's directory name (what lint prints)
    # resolves to the archived URL, so one post can be re-fetched or
    # backfilled without knowing its Medium URL; URLs pass through
    index = {GOOD: {"medium_id": "111122223333"}}
    d = tmp_path / "posts" / "2018-05-01-good-post"
    d.mkdir(parents=True)
    (d / "index.md").write_text('---\n{"original_url": "%s", "medium_id": '
                                '"111122223333"}\n---\n\nBody.\n' % GOOD)
    for ref in ("111122223333", "2018-05-01-good-post", "posts/2018-05-01-good-post/",
                GOOD, GOOD + "?source=x"):
        assert fetchmod.resolve_post_ref(ref, tmp_path, index).startswith(GOOD), ref
    assert fetchmod.resolve_post_ref("2019-01-01-unknown", tmp_path, index) == "2019-01-01-unknown"
    assert fetchmod.resolve_post_ref("deadbeef", tmp_path, index) == "deadbeef"


def test_two_giphy_clips_in_one_post_get_two_files(tmp_path):
    # every Giphy file is giphy.mp4: the basename de-duplication that
    # merges one Medium asset's two CDN hosts must not merge them
    a = "https://media.giphy.com/media/Ri327iDKuC4pnExM4L/giphy.mp4"
    b = "https://media.giphy.com/media/fSqNQ06Ujnuu8juH2t/giphy.mp4"
    same = ("https://miro.medium.com/v2/1*abc.png",
            "https://cdn-images-1.medium.com/1*abc.png")
    session = FakeSession(router=lambda url: FakeResp(content=url.encode()))
    img_map = {}
    n = fetchmod.fetch_images(session, [a, b, *same], tmp_path / "images", img_map, 0)
    assert n == 3 and session.calls == [a, b, same[0]]
    assert img_map == {a: "001-Ri327iDKuC4pnExM4L-giphy.mp4",
                       b: "002-fSqNQ06Ujnuu8juH2t-giphy.mp4",
                       same[0]: "003-1_abc.png", same[1]: "003-1_abc.png"}
    assert (tmp_path / "images" / img_map[b]).read_bytes() == b.encode()


def tweet_page(mid):
    state = {
        f"Post:{mid}": {"id": mid, 'content({"a":1})': {"bodyModel": {
            "paragraphs": [{"__ref": "Paragraph:p0"}]}}},
        "Paragraph:p0": {"type": "IFRAME", "text": "", "markups": [],
                         "iframe": {"mediaResource": {"__ref": "MediaResource:m1"}}},
        "MediaResource:m1": {"id": "t1", "title": "Ann on Twitter", "iframeSrc":
                             "https://cdn.embedly.com/widgets/media.html?url="
                             "https%3A%2F%2Ftwitter.com%2Fann%2Fstatus%2F12345"},
    }
    return "<script>window.__APOLLO_STATE__ = " + json.dumps(state) + "</script>"


def test_fetch_media_archives_tweets(tmp_path):
    mid = "111122223333"
    oembed = fetchmod.TWEET_OEMBED_URL.format(url="https://twitter.com/ann/status/12345")
    session = FakeSession(router=lambda url: FakeResp(json.dumps({"author_name": "Ann"}))
                          if url == oembed else (_ for _ in ()).throw(AssertionError(url)))
    dest = tmp_path / mid
    assert fetchmod.fetch_media(session, tweet_page(mid), mid, dest, 0) == 1
    assert json.loads((dest / "media" / "tweet-12345.json").read_text()) == {"author_name": "Ann"}
    assert fetchmod.fetch_media(session, tweet_page(mid), mid, dest, 0) == 0
    assert session.calls == [oembed]


CARBON_PAGE = '<html><body><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"snippet":{"userId":"u","createdAt":1627625663,"language":"python","code":"class ExampleWidget(DOMWidget):\\n    value = 1","id":"PaDDn2ZszZUVmuhvRP52"}},"__N_SSP":true},"page":"/embed/[id]"}</script></body></html>'


def carbon_page(mid):
    state = {
        f"Post:{mid}": {"id": mid, 'content({"a":1})': {"bodyModel": {
            "paragraphs": [{"__ref": "Paragraph:p0"}]}}},
        "Paragraph:p0": {"type": "IFRAME", "text": "", "markups": [],
                         "iframe": {"mediaResource": {"__ref": "MediaResource:m1"}}},
        "MediaResource:m1": {"id": "c1", "title": "Carbon snippet", "iframeSrc":
                             "https://cdn.embedly.com/widgets/media.html?src=https%3A%2F%2F"
                             "carbon.now.sh%2Fembed%2FPaDDn2ZszZUVmuhvRP52%3F&url="
                             "https%3A%2F%2Fcarbon.now.sh%2FPaDDn2ZszZUVmuhvRP52"},
    }
    return "<script>window.__APOLLO_STATE__ = " + json.dumps(state) + "</script>"


def test_fetch_media_archives_carbon_snippets(tmp_path):
    mid = "111122223333"
    embed = fetchmod.CARBON_EMBED_URL.format(id="PaDDn2ZszZUVmuhvRP52")
    session = FakeSession(router=lambda url: FakeResp(CARBON_PAGE) if url == embed
                          else (_ for _ in ()).throw(AssertionError(url)))
    dest = tmp_path / mid
    assert fetchmod.fetch_media(session, carbon_page(mid), mid, dest, 0) == 1
    snippet = json.loads((dest / "media" / "carbon-PaDDn2ZszZUVmuhvRP52.json").read_text())
    assert snippet["language"] == "python" and snippet["code"].startswith("class ExampleWidget")
    assert fetchmod.fetch_media(session, carbon_page(mid), mid, dest, 0) == 0
    assert session.calls == [embed]
    # a page without the snippet data archives nothing
    assert fetchmod.carbon_snippet("<html>gone</html>") is None


SYNDICATION = {"id_str": "12345", "text": "Hello pic", "mediaDetails": [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/CnW7DC6VUAE7NaZ.jpg",
         "url": "https://t.co/BSxjRlMomu"},
        {"type": "video", "media_url_https": "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/abc.jpg",
         "url": "https://t.co/vid"}],
    "photos": [{"url": "https://pbs.twimg.com/media/CnW7DC6VUAE7NaZ.jpg", "width": 2048, "height": 1537}]}


def test_tweet_token_matches_react_tweet():
    # the value the live endpoint accepted for this id
    assert fetchmod.tweet_token("753714190599151616") == "1trv2egapj3oifu"


def test_fetch_media_archives_a_tweets_pictures(tmp_path):
    mid = "111122223333"
    oembed = fetchmod.TWEET_OEMBED_URL.format(url="https://twitter.com/ann/status/12345")
    synd = fetchmod.TWEET_MEDIA_URL.format(id="12345", token=fetchmod.tweet_token("12345"))
    with_pic = {"author_name": "Ann", "html": '<blockquote><p>Hello <a href="https://t.co/x">'
                'pic.twitter.com/x</a></p></blockquote>'}
    def router(url):
        if url == oembed:
            return FakeResp(json.dumps(with_pic))
        if url == synd:
            return FakeResp(json.dumps(SYNDICATION))
        raise AssertionError(url)
    session = FakeSession(router=router)
    dest = tmp_path / mid
    # the oEmbed payload and, since it links a picture, the syndication one
    assert fetchmod.fetch_media(session, tweet_page(mid), mid, dest, 0) == 2
    assert json.loads((dest / "media" / "tweet-12345.media.json").read_text())["photos"]
    assert fetchmod.fetch_media(session, tweet_page(mid), mid, dest, 0) == 0
    assert session.calls == [oembed, synd]
    # the photo (full size) and the video's poster join the post's images
    assert fetchmod.embed_asset_urls(tweet_page(mid), mid, dest) == [
        "https://pbs.twimg.com/media/CnW7DC6VUAE7NaZ.jpg",
        "https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/abc.jpg"]
    assert fetchmod.embed_asset_urls(tweet_page(mid), mid, None) == []
    # a tweet without a picture never touches the syndication endpoint
    plain = {"author_name": "Ann", "html": "<blockquote><p>Hello</p></blockquote>"}
    session = FakeSession(router=lambda url: FakeResp(json.dumps(plain)) if url == oembed
                          else (_ for _ in ()).throw(AssertionError(url)))
    dest2 = tmp_path / "two" / mid
    assert fetchmod.fetch_media(session, tweet_page(mid), mid, dest2, 0) == 1
    assert not (dest2 / "media" / "tweet-12345.media.json").exists()


def test_deleted_tweet_is_recorded(tmp_path):
    mid = "111122223333"
    gone = FakeSession(router=lambda url: FakeResp("", status=404))
    dest = tmp_path / mid
    assert fetchmod.fetch_media(gone, tweet_page(mid), mid, dest, 0) == 1
    record = json.loads((dest / "media" / "tweet-12345.json").read_text())
    assert record["deleted"] is True and record["status"] == 404
    assert record["url"] == "https://twitter.com/ann/status/12345"
    # recorded: not asked again; any other failure records nothing
    assert fetchmod.fetch_media(gone, tweet_page(mid), mid, dest, 0) == 0
    broken = FakeSession(router=lambda url: FakeResp("", status=503))
    dest2 = tmp_path / "two" / mid
    assert fetchmod.fetch_media(broken, tweet_page(mid), mid, dest2, 0) == 0
    assert not (dest2 / "media").exists()
