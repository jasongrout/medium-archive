"""HTTP session and retrying GET."""

import sys
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlsplit

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# What that browser sends on every request. Medium sits behind
# Cloudflare, which reads the headers a client sends as much as the
# user-agent string it claims: a Chrome user-agent arriving without
# Chrome's client hints is one of the cheapest bot signatures there is.
# Accept-Encoding is deliberately not here -- requests advertises the
# encodings it can actually decode, and claiming Chrome's (br, zstd)
# without the libraries to read them returns compressed bytes as text.
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
}

# ...and what it adds when the request is a page the reader navigated
# to, rather than a subresource: `fetch` uses these for post pages, the
# requests Medium guards most closely.
NAV_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def load_cookies(session: requests.Session, path) -> int:
    """Put a browser's cookies on the session, from a Netscape cookie
    jar (what the browser extensions that export them write) or from a
    file holding one `Cookie:` header line copied out of devtools.
    Returns how many cookies were loaded.

    This is the way past a bot wall that has decided this client is not
    a browser: the cookies a real browser earned carry the decision.
    Cloudflare binds them to the browser that earned them, so pass
    --user-agent with that browser's string alongside them."""
    text = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
    jar = MozillaCookieJar()
    try:
        jar.load(str(Path(path).expanduser()), ignore_discard=True, ignore_expires=True)
    except OSError:          # http.cookiejar.LoadError is an OSError
        jar = None
    if jar is not None and len(jar):
        session.cookies.update(jar)
        return len(jar)
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("cookie:"):
            line = line.split(":", 1)[1].strip()
        for part in line.split(";"):
            name, sep, value = part.partition("=")
            if sep and name.strip():
                session.cookies.set(name.strip(), value.strip())
                n += 1
    if not n:
        raise ValueError(f"no cookies in {path}: expected a Netscape cookie "
                         f"jar or a 'name=value; name=value' header line")
    return n


def make_session(cookies=None, user_agent: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    if user_agent:
        s.headers["User-Agent"] = user_agent
    if cookies:
        n = load_cookies(s, cookies)
        print(f"loaded {n} cookie(s) from {cookies}", file=sys.stderr)
    return s


TRANSIENT_STATUSES = (500, 502, 503, 504)


class BotWall(requests.HTTPError):
    """Medium's edge refused the request with 403. The post is not gone
    and the archive is not at fault: the client did not look like a
    browser to Cloudflare, or this address is walled for the moment."""


def wall_hint(r: requests.Response) -> str:
    """What a 403 says about itself, for the run's log: which edge
    answered, its request id (what Medium support would ask for), and
    whether the body is a challenge page rather than a refusal."""
    bits = [b for b in (r.headers.get("Server"),
                        f"cf-ray {r.headers['CF-Ray']}" if r.headers.get("CF-Ray") else None,
                        r.headers.get("cf-mitigated")) if b]
    try:
        body = r.text[:4000]
    except Exception:
        body = ""
    if any(s in body for s in ("Just a moment", "cf-chl", "challenge-platform",
                               "Enable JavaScript and cookies")):
        bits.append("interactive challenge page")
    elif "Attention Required" in body or "Sorry, you have been blocked" in body:
        bits.append("blocked by the site's security rules")
    return "; ".join(bits)


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
            if r.status_code == 403:
                # A bot wall, not a verdict on this URL: the edge
                # refused the request before Medium saw it. Retrying
                # the same request behind the same wall only spends
                # requests against it, so this raises like the 429 does
                # and the caller decides (fetch falls back to the RSS
                # body, and stops the run when the wall is systemic).
                hint = wall_hint(r)
                # fetch asks several hosts for a post's material, and a
                # 403 from any of them lands here: name the one that
                # refused rather than blaming Medium for a gists API
                # rate limit or an oEmbed endpoint's refusal.
                host = urlsplit(url).netloc or "the server"
                raise BotWall(f"403 for {url} -- refused by {host}'s bot wall"
                              + (f" ({hint})" if hint else ""), response=r)
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
