"""net.fetch: permanent 4xx errors fail fast; transient statuses retry."""

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
