"""net.fetch: permanent 4xx errors fail fast; transient statuses retry;
403 is a bot wall, not a verdict on the URL."""

import pytest
import requests

from _fakes import FakeResp, FakeSession
from medium_archive import net


def test_permanent_4xx_fails_fast():
    s = FakeSession(FakeResp(status=404))
    with pytest.raises(requests.HTTPError) as e:
        net.fetch(s, "https://blog.example.com/x", retries=4)
    assert e.value.response.status_code == 404
    assert len(s.calls) == 1


def test_transient_5xx_retries(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    s = FakeSession(FakeResp(status=503))
    with pytest.raises(requests.HTTPError):
        net.fetch(s, "https://blog.example.com/x", retries=3)
    assert len(s.calls) == 3


def test_403_raises_botwall_without_retrying():
    s = FakeSession(FakeResp(status=403, headers={"CF-Ray": "abc-DFW"}))
    with pytest.raises(net.BotWall) as e:
        net.fetch(s, "https://blog.example.com/x", retries=4)
    assert e.value.response.status_code == 403
    assert "cf-ray abc-DFW" in str(e.value)
    assert len(s.calls) == 1          # not retried like a transient status


def test_wall_hint_names_a_challenge_page():
    r = FakeResp(status=403, text="<html>Just a moment...<div class=cf-chl></div></html>")
    assert "challenge" in net.wall_hint(r)


def test_load_cookies_from_header_line(tmp_path):
    p = tmp_path / "cookies.txt"
    p.write_text("Cookie: sid=abc123; uid=42\n")
    s = requests.Session()
    assert net.load_cookies(s, p) == 2
    assert s.cookies.get("sid") == "abc123"
    assert s.cookies.get("uid") == "42"


def test_load_cookies_from_netscape_jar(tmp_path):
    p = tmp_path / "cookies.txt"
    p.write_text("# Netscape HTTP Cookie File\n"
                 ".blog.example.com\tTRUE\t/\tFALSE\t0\tsid\txyz789\n")
    s = requests.Session()
    assert net.load_cookies(s, p) == 1
    assert s.cookies.get("sid") == "xyz789"


def test_load_cookies_rejects_empty_file(tmp_path):
    p = tmp_path / "cookies.txt"
    p.write_text("\n")
    with pytest.raises(ValueError):
        net.load_cookies(requests.Session(), p)
