"""The myst step: build a MyST (mystmd) site in <out>/site/ from the
converted archive -- one page per post with its images, a cover-image
gallery landing page, a chronological archive page, a year-grouped table
of contents, and a site-level redirect map.

Works from posts.json and <out>/posts/ alone (run convert first), so the
site is as reproducible as the posts are: raw/ + fixups/ -> convert ->
posts/ -> myst -> site/. Never touches the network; rendering the site
(`myst start` or `myst build --html` inside <out>/site/) is mystmd's job,
not this step's. (The landing-page gallery uses the myst-listing plugin,
which mystmd downloads at build time like the site theme itself.)

The posts/ layer stays generator-agnostic Markdown; everything
MyST-specific happens here: front matter is reshaped to MyST's schema
(authors, tags), page URLs are chosen (each page's URL slug is derived
from its filename -- mystmd caps slugs at 50 characters, so a long
filename serves at a truncated URL), links between posts in the
publication are rewritten from Medium URLs to site-relative page links,
prose MyST would misparse is escaped, and redirects.csv maps every old
inbound path to the page URL mystmd actually serves.

Site-wide text (title, description, the landing-page intro) comes from an
optional hand-written <out>/site.json, so it is versioned with the archive
and survives regeneration. The machinery shared with the other site
exporters (hugo, pelican) lives in sites.py.
"""

import json
import re
import sys
from pathlib import Path

from .sites import (ImagePlacer, LinkMap, by_year, clean_site,
                    link_or_copy, load_site_inputs, make_cover_thumbnail,
                    page_stems, pick_cover, read_post_body,
                    retarget_images, rewrite_body as _rewrite, template_text,
                    write_redirects_csv)

# Segments MyST-escaping must leave alone: inline code, link destinations,
# autolinks. Everything else in a prose line is text MyST will parse.
PROTECT_RE = re.compile(r"(`+[^`]*`+|\]\([^)\s]*\)|<https?://[^>\s]+>)")
AT_RE = re.compile(r"(?<![\w\\])@(?=\w)")          # @handle, not an email's @
DOLLAR_RE = re.compile(r"(?<!\\)\$")

# The landing-page gallery comes from the myst-listing plugin
# (https://contrib.mystmd.org/myst-listing/), pinned so a regenerated site
# renders the same way next year. mystmd downloads it at build time, like
# the site theme; the generation itself stays offline.
LISTING_PLUGIN_URL = ("https://github.com/myst-contrib/myst-listing/"
                      "releases/download/v0.1.9/plugin.mjs")

# Companion plugin written into site/ beside myst.yml, from
# templates/myst/listing-covers.mjs (its header comment explains why the
# gallery's cover images need it). It must be listed *after* myst-listing
# in myst.yml: plugin transforms run in listing order.
COVER_SHIM_NAME = "listing-covers.mjs"


def _yml(value) -> str:
    """A scalar or flow list as YAML, via JSON (valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def myst_slug(stem: str) -> str:
    """The URL slug mystmd serves a page file at (myst-common's
    createSlug): a leading enumeration is stripped (but a year is kept),
    runs of characters outside [a-z0-9-] collapse to a single '-', and
    the result is trimmed and then capped at 50 characters -- so a page
    named voilà-0-5-0-homecoming.md serves at /voil-0-5-0-homecoming, and
    a long filename serves at a truncated URL (which may end in '-': the
    cap is applied after the trim)."""
    if not re.match(r"[12][0-9]{3}|[0-9]{5}", stem):
        stem = re.sub(r"^[0-9_.-]+", "", stem) or stem
    slug = re.sub(r"[^a-z0-9-]+", "-", stem.replace("&", "-and-").lower())
    return re.sub(r"-+", "-", slug).strip("-")[:50]


def page_paths(manifest: dict, stems: dict) -> dict:
    """stem -> the site-relative path mystmd will serve the page at:
    myst_slug of the filename, with colliding slugs numbered -1, -2, ...
    in the order mystmd loads the pages -- the toc order write_myst_yml
    emits, after the landing and archive pages (whose slugs are seeded so
    a post named index or archive is numbered, not shadowed)."""
    seen = {"index": 1, "archive": 1}
    paths = {}
    for year, posts in by_year(manifest):
        for url, p in posts:
            slug = myst_slug(stems[url])
            if slug in seen:
                seen[slug] += 1
                slug = f"{slug}-{seen[slug] - 1}"
            else:
                seen[slug] = 1
            paths[stems[url]] = f"/{slug}"
    return paths


def escape_prose(line: str) -> str:
    """Escape Markdown that plain Markdown treats as text but MyST parses
    as syntax: @handle mentions (MyST citations -- GitHub handles in
    contributor lists would silently become unresolved cites) and $
    (dollar math -- "grants of $10,000 to $20,000" would render the span
    between the dollars as math). Inline code, link destinations and
    autolinks pass through untouched."""
    parts = PROTECT_RE.split(line)
    return "".join(p if i % 2 else DOLLAR_RE.sub(r"\\$", AT_RE.sub(r"\\@", p))
                   for i, p in enumerate(parts))


def rewrite_body(markdown: str, links: LinkMap, prefix: str) -> str:
    """Point links at other posts of the publication to their site pages
    instead of Medium, and escape prose MyST would misparse. prefix is
    the path from the referring page's directory to site/posts/ ("../"
    for a post page, "posts/" for the landing page)."""
    def target_for(url):
        hit = links.page_for(url)
        if hit is None:
            return None
        d, stem, frag = hit
        return f"{prefix}{d}/{stem}.md" + (f"#{frag}" if frag else "")
    return _rewrite(markdown, target_for, escape_prose)


def page_front_matter(post: dict, cover: str | None = None) -> str:
    """The post's front matter reshaped to MyST's schema. Archive
    provenance fields (original_url, medium_id, body_source, ...) stay in
    posts/ and posts.json; a site page carries only what MyST renders.
    cover is a page-relative image path; it becomes the page's thumbnail
    (its landing-gallery card and its social-card image)."""
    lines = [f"title: {_yml(post['title'])}"]
    if post.get("description"):
        lines.append(f"description: {_yml(post['description'])}")
    if cover:
        lines.append(f"thumbnail: {_yml(cover)}")
    if post.get("date"):
        # bare date: MyST ignores (and warns about) a time component
        lines.append(f"date: {_yml(post['date'][:10])}")
    if post.get("author"):
        if " " in post["author"].strip():
            lines.append(f"authors:\n  - name: {_yml(post['author'])}")
        else:                    # mononym; MyST would warn parsing it
            lines.append("authors:\n  - name:\n"
                         f"      literal: {_yml(post['author'])}")
        if post.get("author_url"):
            lines.append(f"    url: {_yml(post['author_url'])}")
    if post.get("tags"):
        lines.append(f"tags: {_yml(post['tags'])}")
    return "---\n" + "\n".join(lines) + "\n---\n\n"


def write_myst_yml(site: Path, manifest: dict, stems: dict, config: dict):
    lines = ["# Generated by `medium-archive myst`; do not edit.",
             "# Site title/description/intro come from <out>/site.json.",
             "version: 1",
             "project:",
             f"  title: {_yml(config['title'])}"]
    if config.get("description"):
        lines.append(f"  description: {_yml(config['description'])}")
    lines += ["  plugins:",
              "    # the landing-page gallery, then the local transform that",
              "    # makes its cover images work (order matters)",
              f"    - {LISTING_PLUGIN_URL}",
              f"    - {COVER_SHIM_NAME}",
              "  toc:",
              "    - file: index.md",
              "    - file: archive.md"]
    for year, posts in by_year(manifest):
        lines.append(f"    - title: {_yml(year)}")
        lines.append("      children:")
        for url, p in posts:
            lines.append(f"        - file: posts/{Path(p['dir']).name}/{stems[url]}.md")
    lines += ["site:",
              "  template: book-theme",
              f"  title: {_yml(config['title'])}"]
    (site / "myst.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_landing(site: Path, config: dict):
    """The landing page: the intro, then every post as a cover-image card,
    newest first (myst-listing's default sort) -- the myst counterpart of
    the hugo/pelican card-grid home."""
    lines = ["---", f"title: {_yml(config['title'])}", "---", ""]
    if config.get("intro"):
        lines += [config["intro"].rstrip(), ""]
    lines += ["Every post, newest first; the [archive](archive.md) lists "
              "them chronologically by year.", "",
              ":::{listing}",
              ":path: posts/*/*.md",
              ":display: gallery",
              ":limit: 0",              # every post, not the default 10
              ":::", ""]
    (site / "index.md").write_text("\n".join(lines), encoding="utf-8")


def write_archive(site: Path, manifest: dict, stems: dict):
    """The chronological archive: a year-grouped date — title · author list
    of every post (what the landing page was before the gallery)."""
    esc = lambda t: escape_prose(t.replace("[", "\\[").replace("]", "\\]"))
    lines = ["---", "title: Archive", "---", ""]
    for year, posts in by_year(manifest):
        lines += [f"## {year}", ""]
        for url, p in posts:
            date = (p.get("date") or "")[:10]
            entry = f"- {date} — [{esc(p['title'] or url)}]" \
                    f"(posts/{Path(p['dir']).name}/{stems[url]}.md)"
            if p.get("author"):
                entry += f" · {esc(p['author'])}"
            lines.append(entry)
        lines.append("")
    (site / "archive.md").write_text("\n".join(lines), encoding="utf-8")


def build_site(out: Path) -> Path:
    manifest, config = load_site_inputs(out)
    stems = page_stems(manifest)
    links = LinkMap(manifest, stems)
    # Rebuild from scratch, but keep mystmd's _build/ (its template cache
    # and rendered output) so regenerating doesn't force a re-download.
    site = out / "site"
    clean_site(site, keep=("_build",))
    (site / "posts").mkdir(parents=True)

    try:
        from PIL import Image                      # noqa: F401
        have_pillow = True
    except ImportError:
        have_pillow = False
        print("pillow not installed: gallery covers keep full-size images "
              "(`pip install pillow` and re-run for 640x360 thumbnails)",
              file=sys.stderr)
    covers = {url: cover for url, p in manifest.items()
              if (cover := pick_cover(p, out / p["dir"]))}

    placer = ImagePlacer(out, config)
    placer.warm(out, manifest)
    pages = 0
    for url, p in manifest.items():
        body = read_post_body(out / p["dir"])
        if body is None:
            print(f"skipping (no index.md; re-run convert): {p['dir']}",
                  file=sys.stderr)
            continue
        body = rewrite_body(body, links, "../")
        page_dir = site / "posts" / Path(p["dir"]).name
        page_dir.mkdir()
        cover = covers.get(url)
        # images first: a display copy can change format, and the page
        # has to reference the name that was actually placed
        renames = {}
        images = out / p["dir"] / "images"
        if images.is_dir():
            (page_dir / "images").mkdir()
            for img in sorted(images.iterdir()):
                dst = placer.place(img, page_dir / "images" / img.name)
                if dst.name != img.name:
                    renames[img.name] = dst.name
        (page_dir / f"{stems[url]}.md").write_text(
            retarget_images(
                page_front_matter(p, cover and ("images/cover.jpg"
                                                if have_pillow else cover))
                + body, renames),
            encoding="utf-8")
        if cover and have_pillow:
            # baked beside the placed originals; an image that defeats
            # Pillow keeps its (already placed) display copy instead
            dst = page_dir / "images" / "cover.jpg"
            if not make_cover_thumbnail(out / p["dir"] / cover, dst):
                link_or_copy(page_dir / retarget_images(cover, renames), dst)
        pages += 1

    placer.report()
    write_landing(site, config)
    write_archive(site, manifest, stems)
    (site / COVER_SHIM_NAME).write_text(
        template_text("myst/listing-covers.mjs"), encoding="utf-8")
    write_myst_yml(site, manifest, stems, config)
    write_redirects_csv(site, manifest, stems,
                        page_paths(manifest, stems).__getitem__)
    print(f"myst done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    print(f"render it with: cd {site} && myst start   (or: myst build --html)",
          file=sys.stderr)
    return site


def cmd_myst(args):
    build_site(args.out)
