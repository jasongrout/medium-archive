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


MEDIUM_CDN_HOSTS = {"miro.medium.com", "cdn-images-1.medium.com",
                    "cdn-images-2.medium.com"}


def same_medium_asset(url: str) -> bool:
    """Whether url is a Medium CDN image, which the same asset appears
    as under more than one host (miro.medium.com/v2/<id> and
    cdn-images-1.medium.com/<id>), so one download serves both names.
    Files elsewhere are told apart by their full URL: every Giphy file
    is called giphy.gif or giphy.mp4."""
    return urlsplit(url).netloc.lower() in MEDIUM_CDN_HOSTS


def safe_filename(url: str, index: int) -> str:
    path = Path(unquote(urlsplit(url).path))
    name = path.name or "image"
    # a Giphy file is named for its format only; the id is the parent
    # segment, and two clips in one post must not share a filename
    if name.split(".")[0] == "giphy" and path.parent.name:
        name = f"{path.parent.name}-{name}"
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


SVG_HEAD_RE = re.compile(
    rb"\s*(?:<\?xml[^>]*\?>\s*|<!DOCTYPE[^>]*>\s*|<!--.*?-->\s*)*<svg[\s>]",
    re.DOTALL)


def sniff_image_ext(path) -> str | None:
    """The extension the file's magic bytes call for -- for images
    fetched from an extensionless URL and stored as .bin, so the derived
    layers can carry a usable name. None if unrecognized."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if head[:3] == b"GIF":
        return ".gif"
    if head[:2] == b"\xff\xd8":
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    # SVG is text: an <svg> root, possibly behind an XML declaration,
    # a DOCTYPE, comments and a UTF-8 BOM (Medium re-hosts badge images
    # from shields.io and the like this way)
    if SVG_HEAD_RE.match(head.removeprefix(b"\xef\xbb\xbf")):
        return ".svg"
    return None


# A Giphy embed's target: the media file itself (media.giphy.com, with
# or without the newer v1.<token> path segment), or the gif's page or
# embed URL, which names the id the media URL is built from
GIPHY_FILE_RE = re.compile(
    r"^https?://(?:media\d*|i)\.giphy\.com/media/(?:v\d\.[^/]+/)?"
    r"([A-Za-z0-9]+)/[^/?#]+\.(?:gif|mp4|webp)(?:[?#].*)?$")
GIPHY_PAGE_RE = re.compile(
    r"^https?://(?:www\.)?giphy\.com/(?:embed/|gifs/(?:[^/?#]*-)?)([A-Za-z0-9]+)")


def giphy_media(url: str) -> str | None:
    """The direct media URL behind a Giphy embed -- the file the archive
    can fetch and serve itself -- or None for any other URL. A media URL
    is kept as it is (Medium's embeds name the gif or the mp4); a page
    or embed URL becomes the gif, which every Giphy id serves."""
    if not url:
        return None
    m = GIPHY_FILE_RE.match(url)
    if m:
        return url.split("#")[0].split("?")[0]
    m = GIPHY_PAGE_RE.match(url)
    return f"https://media.giphy.com/media/{m.group(1)}/giphy.gif" if m else None
