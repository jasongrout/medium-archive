"""HTTP session and retrying GET."""

import sys
import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


TRANSIENT_STATUSES = (500, 502, 503, 504)


def fetch(session: requests.Session, url: str, retries: int = 4, **kw) -> requests.Response:
    backoff = 2.0
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30, **kw)
        except requests.RequestException as e:
            err = e
        else:
            if r.status_code == 429:
                # Rate limited: retrying immediately just digs the hole
                # deeper. Surface the server's hint and give up; fetch is
                # resumable, so re-run with a higher --delay.
                after = r.headers.get("Retry-After")
                if after:
                    print(f"  429 rate limited; server says retry after {after}"
                          f"{'s' if after.isdigit() else ''}", file=sys.stderr)
                raise requests.HTTPError(f"429 for {url} -- raise --delay and re-run",
                                         response=r)
            if r.status_code in TRANSIENT_STATUSES:
                err = requests.HTTPError(f"{r.status_code} for {url}", response=r)
            else:
                r.raise_for_status()   # permanent 4xx: raises with r attached, no retry
                return r
        if attempt == retries - 1:
            raise err
        print(f"  retry {attempt + 1}/{retries - 1} after error: {err}", file=sys.stderr)
        time.sleep(backoff)
        backoff *= 2
    raise RuntimeError("unreachable")
