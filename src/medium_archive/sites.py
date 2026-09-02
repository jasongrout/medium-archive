"""Machinery shared by the site exporters (myst, hugo, pelican).

Each exporter derives a ready-to-render site from the converted archive --
posts.json and <out>/posts/ -- so every site is as reproducible as the
posts are: raw/ + fixups/ -> convert -> posts/ -> exporter -> site dir.
None of them touch the network; rendering is the site generator's job.

Common to all of them: page URL slugs chosen from the Medium slug
(date-prefixed only when several posts share one), links between posts of
the publication rewritten from Medium URLs to site pages, images placed
from posts/ (hard-linked as they are when nothing is to be gained,
else display copies -- see ImagePlacer), a redirect map from every old
inbound path to its page URL, tag names from <out>/tags.json's `display`
map (the tags themselves stay slugs -- spaces and capitals are a display
concern, so nothing a URL is built from moves), and site-wide text
(title, description, landing-page intro, optional base_url) from a
hand-written <out>/site.json.
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
from importlib import resources
from pathlib import Path
from string import Template
from urllib.parse import unquote, urlsplit

from .lint import split_post
from .tags import display_name, load_tag_display
from .urls import medium_id

# The site scaffolding -- generator configs, themes, CSS, and the JS
# snippets shared between generators -- lives as real files under
# templates/ (see templates/README.md), copied into each site as it is
# built. An `@include <path>` marker line (HTML- or CSS-comment form)
# splices a templates/-relative file into the one that carries it, which
# is how the hugo and pelican themes share their snippets. *.tmpl files
# take config values through string.Template, whose $placeholders cannot
# collide with the braces the generators' own template languages use.
TEMPLATE_DIR = resources.files(__package__) / "templates"
_INCLUDE_RE = re.compile(r"(?:<!--|/\*) @include ([\w./-]+) (?:-->|\*/)\n")


def template_text(rel: str) -> str:
    """templates/<rel>, with @include markers expanded."""
    text = (TEMPLATE_DIR / rel).read_text(encoding="utf-8")
    return _INCLUDE_RE.sub(lambda m: template_text(m.group(1)), text)


def fill_template(rel: str, **values) -> str:
    """templates/<rel> (a .tmpl) with its $placeholders substituted;
    every value must arrive already serialized for the config's format."""
    return Template(template_text(rel)).substitute(values)

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
    # Absolute links -- feed URLs, redirect stubs, the Open Graph tags
    # and the share links a reader hands to LinkedIn or Facebook -- are
    # built from base_url. Without it each exporter falls back to a
    # placeholder, which every one of those silently points at someone
    # else's domain, so say so once here rather than let the build look
    # clean until a share link is clicked in the wild.
    if not config.get("base_url"):
        print("site.json has no base_url: absolute links (feeds, redirect "
              "stubs, Open Graph tags, share links) will not point at this "
              "site. Set it to the domain the site is served from and "
              "re-run.", file=sys.stderr)
    return manifest, config


def tag_names(manifest: dict, out: Path) -> dict:
    """Every tag the archive uses -> the name a site shows it under.
    Tags stay slugs through posts.json and into each site's tag URLs;
    tags.json's `display` map is what gives them their spaces and
    capitals at the point they are rendered."""
    display = load_tag_display(out)
    return {tag: display_name(tag, display) for p in manifest.values()
            for tag in p.get("tags") or []}


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


def retarget_images(text: str, renames: dict) -> str:
    """A page's text with its images/<name> references pointed at the
    names actually placed beside it -- a display copy that changed
    format (see ImagePlacer.place) lands under a new extension."""
    if not renames:
        return text
    pattern = re.compile(r"images/(%s)\b"
                         % "|".join(re.escape(n) for n in renames))
    return pattern.sub(lambda m: "images/" + renames[m.group(1)], text)


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


# What a summary-card cover may be: the raster formats every card
# template and Pillow decode. Not gif (animated ones are busy in a card
# grid and cost an animated encode per build), not svg (a badge from
# shields.io re-hosted by Medium is the usual one), not the .bin of
# unrecognized bytes. Names are trusted: convert already typed the
# extensionless downloads by their bytes.
COVER_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def pick_cover(post: dict, post_dir) -> str | None:
    """The post's first raster still of sane size, for its summary card
    -- see COVER_EXTS; an enormous still is passed over too (slow or
    worse, see MAX_COVER_PIXELS). Only decodable formats qualify: the
    baked cover is served as cover.jpg whatever it was, and Hugo's card
    template rasterizes it (.Fill), which aborts the whole build on an
    svg it cannot decode."""
    for image in post.get("images", ()):
        if not image.lower().endswith(COVER_EXTS):
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


# Card covers render in a 640x360 (16:9) frame on both card themes (hugo,
# pelican). A center crop composes photos and screenshots well, but the
# archives are full of logo covers -- wordmarks up to 7:1, square project
# logos -- whose meaning spans edge to edge, and a crop guts those. So
# sources near 16:9 are cropped and sources far from it are letterboxed
# instead: scaled to fit the frame (tiny logos at most 2x, not pixelated
# to fill) over the image's own border color when the border is uniform
# (a logo on white pads invisibly), else over a blurred cover-crop of the
# image itself.
COVER_SIZE = (640, 360)
COVER_CROP_ASPECTS = (1.3, 2.4)   # crop within this band, letterbox outside
COVER_MAX_UPSCALE = 2.0


def _flatten_rgb(im):
    """RGB, any transparency composited onto white: convert()'s default
    is black, which turns a dark-on-transparent logo into an illegible
    dark-on-dark card."""
    from PIL import Image
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    if im.mode in ("RGBA", "LA"):
        flat = Image.new("RGB", im.size, "white")
        flat.paste(im, mask=im.getchannel("A"))
        return flat
    return im.convert("RGB")


def _border_color(im):
    """The single color the image's 1px border is close to, or None.
    Uniformity tolerates compression noise and antialiased content
    touching the edge."""
    w, h = im.size
    raw = b"".join(im.crop(box).tobytes() for box in
                   ((0, 0, w, 1), (0, h - 1, w, h),
                    (0, 0, 1, h), (w - 1, 0, w, h)))
    edges = [raw[i:i + 3] for i in range(0, len(raw), 3)]
    n = len(edges)
    median = tuple(sorted(p[c] for p in edges)[n // 2] for c in range(3))
    near = sum(all(abs(p[c] - median[c]) <= 16 for c in range(3))
               for p in edges)
    return median if near >= n * 0.9 else None


def _letterbox(im):
    """im centered in the 640x360 frame: on its border color when the
    border is uniform, else on a blurred cover-crop of itself."""
    from PIL import Image, ImageFilter, ImageOps
    tw, th = COVER_SIZE
    color = _border_color(im)
    if color is None:
        canvas = ImageOps.fit(im, COVER_SIZE, Image.Resampling.LANCZOS)
        canvas = canvas.filter(ImageFilter.GaussianBlur(20))
    else:
        canvas = Image.new("RGB", COVER_SIZE, color)
    scale = min(tw / im.width, th / im.height, COVER_MAX_UPSCALE)
    fg = im.resize((max(1, round(im.width * scale)),
                    max(1, round(im.height * scale))),
                   Image.Resampling.LANCZOS)
    canvas.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
    return canvas


def make_cover_thumbnail(src, dst) -> bool:
    """640x360 JPEG for a post's summary card, a fraction of the archived
    full-resolution original: center-cropped when the source is near
    16:9, letterboxed when far from it (see COVER_SIZE and friends)."""
    from PIL import Image, ImageOps
    try:
        with Image.open(src) as im:
            im = _flatten_rgb(im)
            lo, hi = COVER_CROP_ASPECTS
            if lo <= im.width / im.height <= hi:
                thumb = ImageOps.fit(im, COVER_SIZE, Image.Resampling.LANCZOS)
            else:
                thumb = _letterbox(im)
            thumb.save(dst, "JPEG", quality=80, optimize=True,
                       progressive=True)
        return True
    except OSError as e:
        print(f"cover thumbnail failed ({e}); using original: {src}",
              file=sys.stderr)
        return False


def bake_cover_thumbnails(out: Path, site: Path, manifest: dict,
                          stems: dict, covers: dict):
    """Each covered post's baked images/cover.jpg, beside the page that
    export_content wrote. An image that defeats Pillow is copied in
    unchanged -- the extension is cosmetic."""
    for url, cover in covers.items():
        src = out / manifest[url]["dir"] / cover
        dst = site / "content" / "posts" / stems[url] / "images" / "cover.jpg"
        if dst.parent.is_dir() and not make_cover_thumbnail(src, dst):
            shutil.copy2(src, dst)


# Sites carry display copies of the archive's images, not the archival
# originals -- raw/ and posts/ keep those at full resolution -- so
# photographs past these caps are resized down to them (longest edge) as
# they are placed into a site. 1600 px keeps them sharp past the card
# themes' widest srcset variant (1104 px); animated gifs get no srcset
# variants, render in the ~736 px body column, and dominate the built
# sites byte-wise, so they are capped tighter. site.json overrides
# either cap ("images": {"still_max_edge": N, "animated_max_edge": N},
# 0 = leave that kind untouched).
#
# Line art -- the charts, screenshots and diagrams that most of this
# archive's PNGs are -- is exempt from the still cap and never encoded
# lossily. Its meaning sits in 9 px text and single-pixel strokes, which
# downscaling destroys: on a survey chart, ink contrast measured 3.4:1
# at the source's 1430 px but 2.3:1 at the 736 px variant a phone picks,
# well under the 3:1 that small text needs. Nor does downscaling buy
# much, since flat color compresses by run length rather than by pixel
# count -- lossless encodes of most of this archive's line art come out
# *larger* downscaled, as antialiasing invents intermediate colors.
# Lossless webp of the full-resolution original instead is pixel-exact
# and still ~60% smaller than the source PNG.
STILL_MAX_EDGE = 1600
ANIMATED_MAX_EDGE = 1104
STILL_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# A still is line art when it holds few enough distinct colors and
# enough flat runs. The two classes separate cleanly on that pair --
# this archive's line art runs 200-8000 colors at 0.55-0.98 flat, its
# photographs past 14000 colors at under 0.5 -- and it costs ~8 ms an
# image. Only PNGs are classified: a photograph saved as PNG re-encodes
# down the photo path, while a screenshot already in JPEG has taken its
# lossy hit and is left alone.
LINE_ART_MAX_COLORS = 8192
LINE_ART_MIN_FLAT = 0.55
# Full resolution is kept within this byte budget: a lossless encode
# over it retries lossy at a quality that leaves text crisp, and only an
# outlier -- a panorama tens of thousands of pixels wide -- is finally
# resized, to an edge far past what any body column asks for.
LINE_ART_MAX_BYTES = 500_000
LINE_ART_MAX_EDGE = 4000
LINE_ART_QUALITY = 90
PHOTO_QUALITY = 85
# Bumped when the copies a given cap produces change shape, so caches
# written by an older scheme are ignored rather than misread.
CACHE_SCHEME = "v2"


def flat_fraction(im) -> float:
    """The share of horizontally adjacent pixel pairs that are identical
    -- near 1 for flat-colored art, near 0 under a photograph's sensor
    noise."""
    from PIL import ImageChops
    w, h = im.size
    if w < 2:
        return 1.0
    grey = im.convert("L")
    diff = ImageChops.difference(grey.crop((1, 0, w, h)),
                                 grey.crop((0, 0, w - 1, h)))
    return diff.histogram()[0] / ((w - 1) * h)


def is_line_art(im) -> bool:
    """True for a chart, screenshot or diagram -- art whose meaning is in
    thin strokes and small text -- and False for a photograph. See
    LINE_ART_MAX_COLORS."""
    rgb = im.convert("RGB")
    if rgb.getcolors(maxcolors=LINE_ART_MAX_COLORS) is None:
        return False               # more colors than flat-colored art has
    return flat_fraction(rgb) >= LINE_ART_MIN_FLAT


def has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info


class ImagePlacer:
    """Place a post's images into a site: hard-link each unchanged when
    nothing is to be gained (or nothing available can process it), else
    place a display copy. Line-art PNGs become full-resolution lossless
    webp, photographs are capped and encoded lossily (JPEG, or webp when
    they carry alpha), animated gifs go through gifsicle. Copies are
    built once into <out>/.image-cache/<scheme-caps>/ and hard-linked
    into every site that wants them, so the three exporters (and re-runs)
    share the work. Stills need Pillow and animated gifs need gifsicle;
    when either is missing the affected images are placed unchanged,
    with a note in the summary.

    place() returns the path it actually wrote, which carries a new
    extension when the copy changed format -- the exporters rewrite
    their pages' image references from it."""

    def __init__(self, out: Path, config: dict):
        images = config.get("images", {})
        self.still_cap = images.get("still_max_edge", STILL_MAX_EDGE) or 0
        self.gif_cap = images.get("animated_max_edge", ANIMATED_MAX_EDGE) or 0
        self.cache = (out / ".image-cache"
                      / f"{CACHE_SCHEME}-{self.still_cap}-{self.gif_cap}")
        self.gifsicle = shutil.which("gifsicle")
        try:
            from PIL import Image
            self.pillow = Image
        except ImportError:
            self.pillow = None
        self.resized = self.converted = self.unchanged = 0
        self.bytes_in = self.bytes_out = 0
        self.notes = []

    def place(self, src: Path, dst: Path) -> Path:
        """Place src at dst -- or beside it under the display copy's own
        extension, when the copy changed format -- and return the path
        written."""
        copy = self._display_copy(src)
        if copy is None:
            self.unchanged += 1
            link_or_copy(src, dst)
            return dst
        if copy.suffix == src.suffix:
            self.resized += 1
        else:
            self.converted += 1
            dst = dst.with_suffix(copy.suffix)
        self.bytes_in += src.stat().st_size
        self.bytes_out += copy.stat().st_size
        link_or_copy(copy, dst)
        return dst

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
        if self.resized or self.converted:
            mb = 1e6
            print(f"display-copy images: {self.converted} re-encoded, "
                  f"{self.resized} resized "
                  f"({self.bytes_in / mb:.0f} MB -> "
                  f"{self.bytes_out / mb:.0f} MB), "
                  f"{self.unchanged} placed as they are", file=sys.stderr)
        for note in self.notes:
            print(note, file=sys.stderr)

    def _note(self, text: str):
        if text not in self.notes:
            self.notes.append(text)

    def _display_copy(self, src: Path):
        """The cached display copy for src, built on first sight; None
        when src should be placed as it is. Cache entries are named by
        source content hash plus the extension the copy carries, so
        reuse survives regeneration and fresh checkouts (mtimes carry no
        meaning there) and identical images shared between posts are
        built once. A copy that came out no smaller than its source is
        cached as a link to the source, which reads back as that same
        None -- the verdict is remembered, not recomputed."""
        ext = src.suffix.lower()
        if ext == ".gif":
            cap, build, candidates = self.gif_cap, self._resize_gif, (ext,)
            if not cap:
                return None
            if not self.gifsicle:
                self._note("gifsicle not installed: animated gifs keep "
                           "their full size")
                return None
            size = self._probe(src)
            if size is None or max(size) <= cap:
                return None
        elif ext in STILL_EXTS:
            # the extensions a still's copy can carry, newest scheme
            # first: line art lands in webp, a photograph in jpg, and a
            # copy that did not pay off under the source's own
            cap, candidates = self.still_cap, (".webp", ".jpg", ext)
            if not cap:
                return None
            if not self.pillow:
                self._note("pillow not installed: still images keep "
                           "their full size")
                return None
            if ext == ".png":
                build = self._copy_png       # picks format and size itself
            else:
                build = self._resize_still   # kept as it is, only smaller
                size = self._probe(src)
                if size is None or max(size) <= cap:
                    return None
        else:
            return None                    # svg and friends pass through
        digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
        for suffix in candidates:
            cached = self.cache / f"{digest}{suffix}"
            if cached.exists():
                return (cached if cached.stat().st_size < src.stat().st_size
                        else None)
        self.cache.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache, suffix=ext)
        os.close(fd)
        built = build(src, tmp, cap)
        if not built:
            os.remove(tmp)
            return None
        if os.path.getsize(tmp) >= src.stat().st_size:
            os.remove(tmp)                 # the copy did not pay off
            built = ext                    # cache the verdict all the same
            cached = self.cache / f"{digest}{built}"
            link_or_copy(src, cached)
        else:
            cached = self.cache / f"{digest}{built}"
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

    def _resize_gif(self, src: Path, tmp: str, cap: int):
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
            return None
        return ".gif"

    def _copy_png(self, src: Path, tmp: str, cap: int):
        """A PNG is line art or a photograph in PNG clothing (see
        is_line_art): the first keeps every pixel, the second takes the
        photo path. Returns the extension written, or None to place the
        source as it is."""
        try:
            with self.pillow.open(src) as im:
                if getattr(im, "n_frames", 1) > 1:
                    return None        # animated: not ours to flatten
                im.load()
                if not is_line_art(im):
                    return self._save_photo(im, tmp, cap)
                return self._save_line_art(im, tmp)
        except Exception as e:
            self._note(f"re-encode failed on {src.name} ({e}); "
                       "placed at full size")
            return None

    def _save_line_art(self, im, tmp: str) -> str:
        """Lossless webp at the source's own resolution: every pixel of
        the text kept, for a fraction of the PNG's bytes."""
        icc = im.info.get("icc_profile")
        kwargs = {"icc_profile": icc} if icc else {}
        im = im.convert("RGBA" if has_alpha(im) else "RGB")
        im.save(tmp, "WEBP", lossless=True, quality=100, method=6, **kwargs)
        if os.path.getsize(tmp) <= LINE_ART_MAX_BYTES:
            return ".webp"
        # An intricate one -- a dense screenshot, a photographic inset --
        # costs more losslessly than a page should carry. Spend the
        # quality rather than the resolution: it is the resolution the
        # small text needs, and q90 leaves strokes crisp.
        im.save(tmp, "WEBP", quality=LINE_ART_QUALITY, method=4, **kwargs)
        if (os.path.getsize(tmp) > LINE_ART_MAX_BYTES
                and max(im.size) > LINE_ART_MAX_EDGE):
            im.thumbnail((LINE_ART_MAX_EDGE, LINE_ART_MAX_EDGE),
                         self.pillow.Resampling.LANCZOS)
            im.save(tmp, "WEBP", quality=LINE_ART_QUALITY, method=4, **kwargs)
        return ".webp"

    def _save_photo(self, im, tmp: str, cap: int) -> str:
        """Capped and lossily encoded: JPEG, or webp for the alpha JPEG
        cannot carry."""
        icc = im.info.get("icc_profile")
        kwargs = {"icc_profile": icc} if icc else {}
        alpha = has_alpha(im)
        im = im.convert("RGBA" if alpha else "RGB")
        if cap and max(im.size) > cap:
            im.thumbnail((cap, cap), self.pillow.Resampling.LANCZOS)
        if alpha:
            im.save(tmp, "WEBP", quality=PHOTO_QUALITY, method=4, **kwargs)
            return ".webp"
        im.save(tmp, "JPEG", quality=PHOTO_QUALITY, optimize=True,
                progressive=True, **kwargs)
        return ".jpg"

    def _resize_still(self, src: Path, tmp: str, cap: int):
        Image = self.pillow
        try:
            with Image.open(src) as im:
                if getattr(im, "n_frames", 1) > 1:
                    return None            # animated: not ours to flatten
                # Medium archives hold the odd mislabeled file (a PNG
                # under a .jpeg name); re-encode what the bytes are,
                # not what the name says -- the filename stays as the
                # pages reference it, and browsers sniff content anyway.
                fmt = im.format
                icc = im.info.get("icc_profile")
                if im.mode == "P":
                    im = im.convert(
                        "RGBA" if "transparency" in im.info else "RGB")
                im.thumbnail((cap, cap), Image.Resampling.LANCZOS)
                kwargs = {"icc_profile": icc} if icc else {}
                if fmt == "JPEG":
                    kwargs |= {"quality": PHOTO_QUALITY, "optimize": True,
                               "progressive": True}
                elif fmt == "WEBP":
                    kwargs |= {"quality": PHOTO_QUALITY, "method": 4}
                else:
                    kwargs |= {"optimize": True}
                im.save(tmp, format=fmt, **kwargs)
        except Exception as e:
            self._note(f"resize failed on {src.name} ({e}); "
                       "placed at full size")
            return None
        return src.suffix.lower()


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
                   front_matter, escape=None, placer=None,
                   transform=None) -> int:
    """The shared page loop for the /posts/<stem>/ exporters (hugo,
    pelican): one content/posts/<stem>/index.md per post -- front matter
    from front_matter(url, post), body with in-publication links rewritten
    to /posts/<stem>/ and then through transform() when given (a
    generator-specific whole-body rewrite, like pelican's figure
    markdown="1" opt-in) -- plus the post's images beside it (through
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
        if transform is not None:
            body = transform(body)
        page_dir = site / "content" / "posts" / stems[url]
        page_dir.mkdir(parents=True)
        # images first: a display copy can change format, and the page
        # has to reference the name that was actually placed
        renames = {}
        images = out / p["dir"] / "images"
        if images.is_dir():
            (page_dir / "images").mkdir()
            for img in sorted(images.iterdir()):
                dst = page_dir / "images" / img.name
                if placer:
                    dst = placer.place(img, dst)
                else:
                    link_or_copy(img, dst)
                if dst.name != img.name:
                    renames[img.name] = dst.name
        (page_dir / "index.md").write_text(
            retarget_images(front_matter(url, p) + body, renames),
            encoding="utf-8")
        pages += 1
    if placer:
        placer.report()
    return pages
