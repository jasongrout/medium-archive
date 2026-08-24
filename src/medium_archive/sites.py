"""Machinery shared by the site exporters (myst, hugo, zola, pelican).

Each exporter derives a ready-to-render site from the converted archive --
posts.json and <out>/posts/ -- so every site is as reproducible as the
posts are: raw/ + fixups/ -> convert -> posts/ -> exporter -> site dir.
None of them touch the network; rendering is the site generator's job.

Common to all of them: page URL slugs chosen from the Medium slug
(date-prefixed only when several posts share one), links between posts of
the publication rewritten from Medium URLs to site pages, images
hard-linked from posts/, a redirect map from every old inbound path to
its page URL, and site-wide text (title, description, landing-page
intro, optional base_url) from a hand-written <out>/site.json.
"""

import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .lint import split_post
from .urls import medium_id

# Covers above this are skipped in favor of the post's next image: themes
# and exporters thumbnail or encode each cover, and Medium archives carry
# the odd 25-megapixel screenshot, which is slow to process (or, past an
# encoder's memory, fails the build).
MAX_COVER_PIXELS = 12_000_000

P_PATH_RE = re.compile(r"^/p/([0-9a-f]{8,12})$")   # Medium's short post URL
LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")  # inline [text](url)
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")  # autolink <url>


def load_site_inputs(out: Path):
    """(manifest, site.json config) for an exporter, or exit."""
    manifest_path = out / "posts.json"
    if not manifest_path.exists():
        sys.exit(f"nothing to build: {manifest_path} missing (run convert first)")
    manifest = json.loads(manifest_path.read_text())
    if not manifest:
        sys.exit("nothing to build: posts.json is empty (run convert first)")
    config = {"title": "Blog archive", "description": "", "intro": ""}
    if (out / "site.json").exists():
        config.update(json.loads((out / "site.json").read_text()))
    return manifest, config


def page_stems(manifest: dict) -> dict:
    """url -> page name, which becomes the page's URL slug. The Medium
    slug alone, unless several posts share it (deleted-and-republished
    announcements, yearly series); those keep their date prefix so every
    page URL is distinct and stable."""
    counts = {}
    for p in manifest.values():
        counts[p["slug"]] = counts.get(p["slug"], 0) + 1
    return {url: p["slug"] if counts[p["slug"]] == 1
            else f"{(p['date'] or '')[:10] or 'undated'}-{p['slug']}"
            for url, p in manifest.items()}


class LinkMap:
    """Resolve URLs that point at posts of this publication -- by exact
    host+path (Medium, Ghost-era, or /p/<id> form, http or https, with or
    without a trailing slash or percent-encoding) or by the Medium id a
    slug ends in -- to the post's site page."""

    def __init__(self, manifest: dict, stems: dict):
        self.by_path, self.by_id = {}, {}
        for url, p in manifest.items():
            page = (Path(p["dir"]).name, stems[url])   # (post dir, page name)
            for u in (p["original_url"], p.get("ghost_url"),
                      p.get("canonical_url")):
                if u:
                    parts = urlsplit(u)
                    self.by_path[(parts.netloc.lower(),
                                  unquote(parts.path).rstrip("/"))] = page
            if p.get("medium_id"):
                self.by_id[p["medium_id"]] = page

    def page_for(self, url: str):
        """(post dir, page name, fragment) or None."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return None
        path = unquote(parts.path).rstrip("/")
        hit = self.by_path.get((parts.netloc.lower(), path))
        if hit is None:
            m = P_PATH_RE.match(path)
            mid = m.group(1) if m else medium_id(url)
            hit = self.by_id.get(mid) if mid else None
        return (*hit, parts.fragment) if hit else None


def rewrite_body(markdown: str, target_for, escape=None) -> str:
    """Rewrite inline links and autolinks whose URL target_for() resolves
    (a post of this publication) to the returned site target, and run
    each prose line through escape() when given. Fenced code is left
    alone: a URL there is content."""
    def inline(m):
        return f"]({target_for(m.group(1)) or m.group(1)})"

    def auto(m):
        target = target_for(m.group(1))
        return f"[{m.group(1)}]({target})" if target else m.group(0)

    out, fence = [], False
    for line in markdown.split("\n"):
        if re.match(r"^`{3,}", line):
            fence = not fence
        elif not fence:
            line = LINK_RE.sub(inline, line)
            line = AUTOLINK_RE.sub(auto, line)
            if escape is not None:
                line = escape(line)
        out.append(line)
    return "\n".join(out)


def image_size(path):
    """(width, height) read from a PNG/GIF/JPEG header, or None."""
    with open(path, "rb") as fh:
        head = fh.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:3] == b"GIF":
            return struct.unpack("<HH", head[6:10])
        if head[:2] == b"\xff\xd8":              # JPEG: find an SOF marker
            fh.seek(2)
            while True:
                marker = fh.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                length = struct.unpack(">H", fh.read(2))[0]
                if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", fh.read(5)[1:])
                    return w, h
                fh.seek(length - 2, 1)
    return None


def pick_cover(post: dict, post_dir) -> str | None:
    """The post's first still image of sane size, for its summary card:
    an animated gif is busy in a card grid (and costs an animated encode
    per build), an enormous still is slow or worse (see
    MAX_COVER_PIXELS); an unreadable one is left to the generator."""
    for image in post.get("images", ()):
        if image.lower().endswith(".gif"):
            continue
        try:
            size = image_size(post_dir / image)
        except OSError:
            continue
        if size is None or size[0] * size[1] <= MAX_COVER_PIXELS:
            return image
    return None


def link_or_copy(src: Path, dst: Path):
    try:
        os.link(src, dst)                  # posts/ already holds the bytes
    except OSError:
        shutil.copy2(src, dst)


def by_year(manifest: dict) -> list:
    """[(year, [(url, post), newest first]), newest year first]."""
    posts = sorted(manifest.items(),
                   key=lambda kv: (kv[1].get("date") or "", kv[0]),
                   reverse=True)
    years = {}
    for url, p in posts:
        years.setdefault((p.get("date") or "")[:4] or "undated",
                         []).append((url, p))
    return sorted(years.items(), reverse=True)


def old_paths(post: dict, url: str):
    """Every site-relative path an old inbound link to this post may
    carry, as (path, the URL it belonged to) pairs: the Medium slug+id
    path, Medium's /p/<id> short form, and the Ghost-era path when there
    is one."""
    pairs = [(post["original_path"], url)]
    if post.get("medium_id"):
        pairs.append((f"/p/{post['medium_id']}", url))
    if post.get("ghost_url"):
        ghost_path = urlsplit(post["ghost_url"]).path
        if ghost_path != post["original_path"]:
            pairs.append((ghost_path, post["ghost_url"]))
    return pairs


def write_redirects_csv(site: Path, manifest: dict, stems: dict, new_path):
    """old inbound path -> new page URL (new_path(stem) chooses the URL
    scheme). The archive-root redirects.csv maps to posts/ directories;
    this one maps to the URLs the exported site actually serves."""
    def q(v):
        v = "" if v is None else str(v)
        return '"' + v.replace('"', '""') + '"' if any(c in v for c in ',"\n') else v
    rows = ["old_path,new_path,original_url"]
    for url, p in sorted(manifest.items(), key=lambda kv: kv[1].get("date") or ""):
        for old, original in old_paths(p, url):
            rows.append(",".join(q(x) for x in (old, new_path(stems[url]), original)))
    (site / "redirects.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def clean_site(site: Path, keep=()):
    """Delete a site directory's generated content, keeping the
    generator's own build output and caches (cheap to keep, expensive or
    network-bound to recreate)."""
    if site.exists():
        for child in site.iterdir():
            if child.name not in keep:
                shutil.rmtree(child) if child.is_dir() else child.unlink()


def read_post_body(src: Path):
    """The converted body of posts/<dir>/, without its front matter, or
    None when index.md is missing (re-run convert)."""
    if not (src / "index.md").exists():
        return None
    _, body = split_post((src / "index.md").read_text(encoding="utf-8"))
    return body


def export_content(out: Path, site: Path, manifest: dict, stems: dict,
                   front_matter, escape=None) -> int:
    """The shared page loop for the /posts/<stem>/ exporters (hugo, zola,
    pelican): one content/posts/<stem>/index.md per post -- front matter
    from front_matter(url, post), body with in-publication links rewritten
    to /posts/<stem>/ -- plus the post's images beside it. Returns the
    page count."""
    links = LinkMap(manifest, stems)

    def target_for(url):
        hit = links.page_for(url)
        if hit is None:
            return None
        _, stem, frag = hit
        return f"/posts/{stem}/" + (f"#{frag}" if frag else "")

    pages = 0
    for url, p in manifest.items():
        body = read_post_body(out / p["dir"])
        if body is None:
            print(f"skipping (no index.md; re-run convert): {p['dir']}",
                  file=sys.stderr)
            continue
        body = rewrite_body(body, target_for, escape)
        page_dir = site / "content" / "posts" / stems[url]
        page_dir.mkdir(parents=True)
        (page_dir / "index.md").write_text(front_matter(url, p) + body,
                                           encoding="utf-8")
        images = out / p["dir"] / "images"
        if images.is_dir():
            (page_dir / "images").mkdir()
            for img in sorted(images.iterdir()):
                link_or_copy(img, page_dir / "images" / img.name)
        pages += 1
    return pages
