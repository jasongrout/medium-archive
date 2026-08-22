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
