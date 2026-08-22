"""Image source extraction and filenames."""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

MIRO_RESIZE_RE = re.compile(r"/v2/(?:(?:resize|format|fill)[^/]*/)+")
MIRO_MAX_RE = re.compile(r"/max/\d+/")


def original_image_url(url: str) -> str:
    """Strip Medium's resize/format path segments -> full-resolution asset."""
    url = url.split("?")[0]
    url = MIRO_RESIZE_RE.sub("/v2/", url)
    url = MIRO_MAX_RE.sub("/", url)
    return url


def largest_from_srcset(srcset: str) -> str | None:
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") else 0
        if w > best_w:
            best, best_w = bits[0], w
    return best


def image_source(img_tag) -> str | None:
    """Best source URL for an <img>, considering sibling <source> tags."""
    picture = img_tag.find_parent("picture")
    if picture:
        for src in picture.find_all("source"):
            if src.get("srcset"):
                u = largest_from_srcset(src["srcset"])
                if u:
                    return original_image_url(u)
    for attr in ("srcset", "data-srcset"):
        if img_tag.get(attr):
            u = largest_from_srcset(img_tag[attr])
            if u:
                return original_image_url(u)
    for attr in ("src", "data-src"):
        if img_tag.get(attr) and not img_tag[attr].startswith("data:"):
            return original_image_url(img_tag[attr])
    return None


def is_tracking_pixel(src: str) -> bool:
    return "medium.com/_/stat" in src or "/_/stat?" in src


AVATAR_RESIZE_RE = re.compile(r"/resize:fill:(\d+):(\d+)[:/]")


def is_avatar(img_tag) -> bool:
    """Avatars are served with a small square fill resize; content images
    use fit resizes."""
    raw = " ".join(filter(None, (img_tag.get(a) for a in ("src", "srcset", "data-src"))))
    m = AVATAR_RESIZE_RE.search(raw)
    return bool(m) and int(m.group(1)) <= 176 and int(m.group(2)) <= 176


def safe_filename(url: str, index: int) -> str:
    name = unquote(Path(urlsplit(url).path).name) or "image"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
    if name.endswith("."):      # extension-less asset ids can end in "."
        name += "bin"
    elif "." not in name:
        name += ".bin"
    return f"{index:03d}-{name}"


def collect_image_urls(page_html: str, feed_item: dict | None) -> list:
    """All image URLs a conversion might need, from both the page body and
    the feed body, deduplicated in order of appearance."""
    urls = []
    sources = [BeautifulSoup(page_html, "html.parser")]
    if feed_item and feed_item.get("content_html"):
        sources.append(BeautifulSoup(feed_item["content_html"], "html.parser"))
    for soup in sources:
        root = soup.find("article") or soup
        for img in root.find_all("img"):
            if is_avatar(img):
                continue
            src = image_source(img)
            if src and not is_tracking_pixel(src) and src not in urls:
                urls.append(src)
    return urls
