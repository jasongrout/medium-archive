"""Canned HTTP stand-ins for requests.Session, so tests never touch the network."""

import requests


class FakeResp:
    def __init__(self, text="", status=200, content=None):
        self.text = text
        self.status_code = status
        self.content = text.encode() if content is None else content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def iter_content(self, chunk_size):
        yield self.content


class FakeSession:
    """Returns `resp` for every GET, or routes each URL through `router`."""

    def __init__(self, resp=None, router=None):
        self.calls = []
        self.resp = resp
        self.router = router

    def get(self, url, **kw):
        self.calls.append(url)
        if self.router is not None:
            return self.router(url)
        return self.resp
