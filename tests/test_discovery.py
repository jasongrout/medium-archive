"""wayback_urls CDX parsing and discover()'s merge across sources."""

from datetime import datetime, timezone

from _fakes import FakeResp, FakeSession
from medium_archive import discovery

BASE = "https://blog.example.com/"

CDX_PAGE_1 = """\
https://blog.example.com/first-post-0123456789ab 20180103120000
http://blog.example.com:80/second-post-abcdefabcdef 20180221000000
https://blog.example.com/tagged/example 20180101000000
https://blog.example.com/?gi=0123456789ab 20181215171108
https://blog.example.com/about 20190101000000

com%2Cexample%2Cblog%29%2Fresume-key+20180103120000
"""
CDX_PAGE_2 = """\
https://blog.example.com/second-post-abcdefabcdef?source=rss 20180222000000
https://blog.example.com/bad-timestamp-post-aaaabbbbcccc notadate
"""


def cdx_router(url):
    if "resumeKey=" in url:
        assert "resumeKey=com%2Cexample%2Cblog%29%2Fresume-key+20180103120000" in url, url
        return FakeResp(CDX_PAGE_2)
    return FakeResp(CDX_PAGE_1)


def test_wayback_urls_paginates_filters_and_dates():
    s = FakeSession(router=cdx_router)
    entries = discovery.wayback_urls(s, BASE)
    assert len(s.calls) == 2          # followed the resume key exactly once
    urls = dict(entries)
    assert "https://blog.example.com/first-post-0123456789ab" in urls
    # http://host:80 and ?query variants normalize onto the base scheme/host
    assert "https://blog.example.com/second-post-abcdefabcdef" in urls
    # non-post URLs (tag pages, /about, the front page) are dropped
    assert all("/tagged/" not in u and "/about" not in u and not u.endswith(".com")
               for u in urls)
    assert urls["https://blog.example.com/first-post-0123456789ab"] == \
        datetime(2018, 1, 3, 12, 0, tzinfo=timezone.utc)
    # unparseable capture timestamp -> URL kept, date None
    assert urls["https://blog.example.com/bad-timestamp-post-aaaabbbbcccc"] is None


def test_discover_merges_sources_and_dedupes_by_id(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "fetch_feed", lambda session, base, raw_dir: {
        "https://blog.example.com/new-post-111122223333": {
            "title": "t", "author": "a", "tags": [],
            "date": "Mon, 03 Aug 2026 10:00:00 GMT", "content_html": ""}})
    monkeypatch.setattr(discovery, "walk_sitemap", lambda session, url, host, seen=None: [
        ("https://blog.example.com/renamed-post-abcdefabcdef", None)])
    entries, feed = discovery.discover(FakeSession(router=cdx_router), BASE,
                                       tmp_path, wayback=True)
    d = {u: (dt, src) for u, dt, src in entries}
    # the sitemap URL wins for the shared Medium id and keeps its source;
    # the wayback first-capture date fills in the missing date
    assert d["https://blog.example.com/renamed-post-abcdefabcdef"] == \
        (datetime(2018, 2, 21, tzinfo=timezone.utc), "sitemap")
    assert "https://blog.example.com/second-post-abcdefabcdef" not in d
    assert d["https://blog.example.com/new-post-111122223333"][1] == "feed"
    assert d["https://blog.example.com/first-post-0123456789ab"][1] == "wayback"
    assert len(d) == 4
