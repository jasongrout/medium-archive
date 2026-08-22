"""Medium URL and post-identifier helpers."""

import re
from urllib.parse import unquote, urlparse

POST_ID_RE = re.compile(r"-([0-9a-f]{8,12})/?$")   # Medium post slugs end in a hex id


def canonical_url(url: str) -> str:
    return url.split("?")[0].split("#")[0].rstrip("/")


def norm_key(url: str) -> str:
    """Last path segment, percent-decoded, lowercased, hyphens removed.
    The Wayback crawl index contains mangled variants of real post URLs --
    the id truncated by a character or two, or a hyphen inserted mid-slug
    or mid-id -- and these keys let a variant be matched to its real URL."""
    last = unquote(urlparse(url).path).strip("/").split("/")[-1]
    return last.replace("-", "").lower()


def medium_id(url: str) -> str | None:
    m = POST_ID_RE.search(urlparse(url).path)
    return m.group(1) if m else None


def slug_of(url: str) -> str:
    last = urlparse(url).path.strip("/").split("/")[-1]
    return POST_ID_RE.sub("", last)[:80] or "post"


def is_post_url(url: str, base_host: str) -> bool:
    p = urlparse(url)
    if p.netloc != base_host:
        return False
    if p.path.startswith(("/tagged/", "/search", "/archive", "/about", "/sitemap")):
        return False
    return bool(POST_ID_RE.search(p.path))
