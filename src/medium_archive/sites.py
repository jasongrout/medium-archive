"""Machinery shared by the site exporters (myst, hugo, zola, pelican).

Each exporter derives a ready-to-render site from the converted archive --
posts.json and <out>/posts/ -- so every site is as reproducible as the
posts are: raw/ + fixups/ -> convert -> posts/ -> exporter -> site dir.
None of them touch the network; rendering is the site generator's job.

Common to all of them: page URL slugs chosen from the Medium slug
(date-prefixed only when several posts share one), links between posts of
the publication rewritten from Medium URLs to site pages, images placed
from posts/ (hard-linked as-is when small enough, resized display copies
past the caps below -- see ImagePlacer), a redirect map from every old
inbound path to its page URL, and site-wide text (title, description,
landing-page intro, optional base_url) from a hand-written
<out>/site.json.
"""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
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


# Sites carry display copies of the archive's images, not the archival
# originals -- raw/ and posts/ keep those at full resolution -- so
# anything past these caps is resized down to them (longest edge) as it
# is placed into a site. 1600 px keeps stills sharp past the card
# themes' widest srcset variant (1104 px); animated gifs get no srcset
# variants, render in the ~736 px body column, and dominate the built
# sites byte-wise, so they are capped tighter. site.json overrides
# either cap ("images": {"still_max_edge": N, "animated_max_edge": N},
# 0 = leave that kind untouched).
STILL_MAX_EDGE = 1600
ANIMATED_MAX_EDGE = 1104
STILL_EXTS = (".png", ".jpg", ".jpeg", ".webp")


class ImagePlacer:
    """Place a post's images into a site: hard-link each unchanged when
    it is within the caps (or nothing available can resize it), else
    place a resized display copy. Copies are built once into
    <out>/.image-cache/<caps>/ and hard-linked into every site that
    wants them, so the four exporters (and re-runs) share the work.
    Stills resize through Pillow, animated gifs through gifsicle; when
    either is missing the affected images are placed unchanged, with a
    note in the summary."""

    def __init__(self, out: Path, config: dict):
        images = config.get("images", {})
        self.still_cap = images.get("still_max_edge", STILL_MAX_EDGE) or 0
        self.gif_cap = images.get("animated_max_edge", ANIMATED_MAX_EDGE) or 0
        self.cache = out / ".image-cache" / f"{self.still_cap}-{self.gif_cap}"
        self.gifsicle = shutil.which("gifsicle")
        try:
            from PIL import Image
            self.pillow = Image
        except ImportError:
            self.pillow = None
        self.resized = self.unchanged = 0
        self.bytes_in = self.bytes_out = 0
        self.notes = []

    def place(self, src: Path, dst: Path):
        copy = self._display_copy(src)
        if copy is None:
            self.unchanged += 1
            link_or_copy(src, dst)
        else:
            self.resized += 1
            self.bytes_in += src.stat().st_size
            self.bytes_out += copy.stat().st_size
            link_or_copy(copy, dst)

    def warm(self, out: Path, manifest: dict):
        """Build the display copies for every post image up front, in
        parallel -- gifsicle runs and Pillow encodes hold no GIL, and
        the big animated gifs take tens of seconds each, so this is
        where a cold cache earns its build time back. place() then
        just hard-links the results."""
        from concurrent.futures import ThreadPoolExecutor
        paths = [img for p in manifest.values()
                 if (d := out / p["dir"] / "images").is_dir()
                 for img in d.iterdir()]
        with ThreadPoolExecutor(min(8, os.cpu_count() or 1)) as pool:
            for _ in pool.map(self._display_copy, paths):
                pass

    def report(self):
        if self.resized:
            mb = 1e6
            print(f"display-copy images: {self.resized} resized "
                  f"({self.bytes_in / mb:.0f} MB -> "
                  f"{self.bytes_out / mb:.0f} MB), "
                  f"{self.unchanged} within caps", file=sys.stderr)
        for note in self.notes:
            print(note, file=sys.stderr)

    def _note(self, text: str):
        if text not in self.notes:
            self.notes.append(text)

    def _display_copy(self, src: Path):
        """The cached resized copy for src, built on first sight; None
        when src should be placed as it is. Cache entries are named by
        source content hash, so reuse survives regeneration and fresh
        checkouts (mtimes carry no meaning there) and identical images
        shared between posts resize once."""
        ext = src.suffix.lower()
        if ext == ".gif":
            cap, build = self.gif_cap, self._resize_gif
            if cap and not self.gifsicle:
                self._note("gifsicle not installed: animated gifs keep "
                           "their full size")
                return None
        elif ext in STILL_EXTS:
            cap, build = self.still_cap, self._resize_still
            if cap and not self.pillow:
                self._note("pillow not installed: still images keep "
                           "their full size")
                return None
        else:
            return None                    # svg and friends pass through
        size = self._probe(src)
        if not cap or size is None or max(size) <= cap:
            return None
        digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
        cached = self.cache / f"{digest}{ext}"
        if not cached.exists():
            self.cache.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.cache, suffix=ext)
            os.close(fd)
            if not build(src, tmp, cap):
                os.remove(tmp)
                return None
            if os.path.getsize(tmp) >= src.stat().st_size:
                os.remove(tmp)             # the resize did not pay off
                link_or_copy(src, cached)  # cache the verdict all the same
            else:
                os.replace(tmp, cached)
        return cached if cached.stat().st_size < src.stat().st_size else None

    def _probe(self, src: Path):
        """(width, height), by header sniff or Pillow, else None."""
        try:
            size = image_size(src)
        except OSError:
            return None
        if size is None and self.pillow:
            try:
                with self.pillow.open(src) as im:
                    size = im.size
            except Exception:
                return None
        return size

    def _resize_gif(self, src: Path, tmp: str, cap: int) -> bool:
        # -O2 re-optimizes frames after the resize (2/3 the bytes of a
        # bare resize on the reference archive); --lossy measured slower
        # for no further gain, and --no-conserve-memory avoids a slow
        # low-memory mode that huge gifs otherwise trip.
        run = subprocess.run(
            [self.gifsicle, "--no-conserve-memory", "-O2",
             "--resize-fit", f"{cap}x{cap}", str(src), "-o", tmp],
            capture_output=True, text=True)
        if run.returncode or not os.path.getsize(tmp):
            detail = (run.stderr or "").strip().splitlines()
            self._note(f"gifsicle failed on {src.name}"
                       + (f": {detail[-1]}" if detail else "")
                       + "; placed at full size")
            return False
        return True

    def _resize_still(self, src: Path, tmp: str, cap: int) -> bool:
        Image = self.pillow
        try:
            with Image.open(src) as im:
                if getattr(im, "n_frames", 1) > 1:
                    return False           # animated: not ours to flatten
                icc = im.info.get("icc_profile")
                if im.mode == "P":
                    im = im.convert(
                        "RGBA" if "transparency" in im.info else "RGB")
                im.thumbnail((cap, cap), Image.Resampling.LANCZOS)
                kwargs = {"icc_profile": icc} if icc else {}
                if src.suffix.lower() in (".jpg", ".jpeg"):
                    kwargs |= {"quality": 85, "optimize": True,
                               "progressive": True}
                elif src.suffix.lower() == ".webp":
                    kwargs |= {"quality": 85, "method": 4}
                else:
                    kwargs |= {"optimize": True}
                im.save(tmp, **kwargs)
        except Exception as e:
            self._note(f"resize failed on {src.name} ({e}); "
                       "placed at full size")
            return False
        return True


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
                   front_matter, escape=None, placer=None) -> int:
    """The shared page loop for the /posts/<stem>/ exporters (hugo, zola,
    pelican): one content/posts/<stem>/index.md per post -- front matter
    from front_matter(url, post), body with in-publication links rewritten
    to /posts/<stem>/ -- plus the post's images beside it (through
    placer, when given -- see ImagePlacer). Returns the page count."""
    links = LinkMap(manifest, stems)
    if placer:
        placer.warm(out, manifest)

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
            place = placer.place if placer else link_or_copy
            for img in sorted(images.iterdir()):
                place(img, page_dir / "images" / img.name)
        pages += 1
    if placer:
        placer.report()
    return pages
