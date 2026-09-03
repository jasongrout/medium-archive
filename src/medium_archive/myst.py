"""The myst step: build a MyST (mystmd) site in <out>/site-myst/ from the
converted archive -- one page per post with its images, a cover-image
gallery landing page, a chronological archive page, a year-grouped table
of contents, and a site-level redirect map.

Works from posts.json and <out>/posts/ alone (run convert first), so the
site is as reproducible as the posts are: raw/ + fixups/ -> convert ->
posts/ -> myst -> site-myst/. Never touches the network; rendering the
site (`myst start` or `myst build --html` inside <out>/site-myst/) is
mystmd's job,
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

from .sites import (IFRAME_RE, VIDEO_RE, Covers, ImagePlacer, LinkMap, by_year, clean_site,
                    load_site_inputs, page_stems, place_images,
                    read_post_body, retarget_images, rewrite_body as _rewrite,
                    rewrite_figures, tag_names, template_text,
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

# Companion plugin written into site-myst/ beside myst.yml, from
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


FIGURE_TAG_LINE_RE = re.compile(r"^</?fig(?:ure|caption)>\n\n?", re.M)

# a captioned player: the shell around convert's iframe line
IFRAME_SHELL_RE = re.compile(
    r"<figure>\n\n(<iframe [^\n]+></iframe>)\n\n"
    r"<figcaption>\n\n([^\n]+)\n\n</figcaption>\n\n</figure>")


def _iframe_directive(line: str, caption: str = "") -> str:
    """convert's YouTube player line as MyST's {iframe} directive,
    which mystmd renders as a responsive player; raw HTML would not be
    guaranteed to render. The caption, when any, is the directive body,
    as with {figure}."""
    m = IFRAME_RE.match(line)
    src, title = m.group(1), m.group(2)
    body = f"\n{caption}\n" if caption else ""
    return f":::{{iframe}} {src}\n:width: 100%\n{body}:::"


def myst_iframes(markdown: str) -> str:
    """Every player line, captioned or not, as an {iframe} directive."""
    markdown = IFRAME_SHELL_RE.sub(
        lambda m: _iframe_directive(m.group(1), m.group(2)), markdown)
    return IFRAME_RE.sub(lambda m: _iframe_directive(m.group(0)), markdown)


# a captioned clip: the shell around convert's video line
VIDEO_SHELL_RE = re.compile(
    r"<figure>\n\n(<video [^\n]+></video>)\n\n"
    r"<figcaption>\n\n([^\n]+)\n\n</figcaption>\n\n</figure>")


def myst_videos(markdown: str) -> str:
    """convert's clip lines in MyST's own form: mystmd renders an image
    whose source is a video file as a <video>, so a bare clip is image
    syntax and a captioned one a {figure} directive."""
    def src_of(line):
        return VIDEO_RE.match(line).group(1)
    markdown = VIDEO_SHELL_RE.sub(
        lambda m: f":::{{figure}} {src_of(m.group(1))}\n\n{m.group(2)}\n:::",
        markdown)
    return VIDEO_RE.sub(lambda m: f"![]({m.group(1)})", markdown)


def myst_figures(markdown: str) -> str:
    """The <figure>/<figcaption> shells convert writes around captioned
    images, rendered the MyST way: a captioned image becomes a
    {figure} directive, whose body mystmd renders as a real
    <figcaption> under the image. Anything else the shell wraps (the
    link an embed became, an image wrapped in a link -- the directive
    has no link option) falls back to dropping the shell lines, leaving
    the paragraphs they wrapped -- mystmd is not guaranteed to render
    raw HTML, so no shell may survive."""
    def directive(alt, src, link, caption):
        if link:
            return None
        opt = f":alt: {alt}\n" if alt else ""
        return f":::{{figure}} {src}\n{opt}\n{caption}\n:::"
    markdown = rewrite_figures(markdown, directive)
    markdown = myst_videos(myst_iframes(markdown))
    markdown = FIGURE_TAG_LINE_RE.sub("", markdown)
    return re.sub(r"\n{3,}", "\n\n", markdown)


def rewrite_body(markdown: str, links: LinkMap, prefix: str) -> str:
    """Point links at other posts of the publication to their site pages
    instead of Medium, rewrite convert's figure shells to MyST's own
    figure form, and escape prose MyST would misparse. prefix is
    the path from the referring page's directory to site-myst/posts/ ("../"
    for a post page, "posts/" for the landing page)."""
    def target_for(url):
        hit = links.page_for(url)
        if hit is None:
            return None
        d, stem, frag = hit
        return f"{prefix}{d}/{stem}.md" + (f"#{frag}" if frag else "")
    return _rewrite(myst_figures(markdown), target_for, escape_prose)


def page_front_matter(post: dict, cover: str | None = None,
                      names: dict = None) -> str:
    """The post's front matter reshaped to MyST's schema. Archive
    provenance fields (original_url, medium_id, body_source, ...) stay in
    posts/ and posts.json; a site page carries only what MyST renders.
    cover is a page-relative image path; it becomes the page's thumbnail
    (its landing-gallery card and its social-card image). Tags are
    written under the names tags.json gives them: MyST has no tag pages,
    so nothing here derives a URL from a tag and the name is all a
    reader ever sees."""
    lines = [f"title: {_yml(post['title'])}"]
    if post.get("description"):
        lines.append(f"description: {_yml(post['description'])}")
    if cover:
        lines.append(f"thumbnail: {_yml(cover)}")
    if post.get("date"):
        # bare date: MyST ignores (and warns about) a time component
        lines.append(f"date: {_yml(post['date'][:10])}")
    if post.get("authors"):
        lines.append("authors:")
        for a in post["authors"]:
            if " " in a["name"].strip():
                lines.append(f"  - name: {_yml(a['name'])}")
            else:                # mononym; MyST would warn parsing it
                lines.append(f"  - name:\n      literal: {_yml(a['name'])}")
            if a.get("url"):
                lines.append(f"    url: {_yml(a['url'])}")
    if post.get("tags"):
        shown = [(names or {}).get(tag, tag) for tag in post["tags"]]
        lines.append(f"tags: {_yml(shown)}")
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
            if p.get("authors"):
                entry += " · " + esc(", ".join(a["name"] for a in p["authors"]))
            lines.append(entry)
        lines.append("")
    (site / "archive.md").write_text("\n".join(lines), encoding="utf-8")


def build_site(out: Path) -> Path:
    manifest, config = load_site_inputs(out)
    names = tag_names(manifest, out)
    stems = page_stems(manifest)
    links = LinkMap(manifest, stems)
    # Rebuild from scratch, but keep mystmd's _build/ (its template cache
    # and rendered output) so regenerating doesn't force a re-download.
    site = out / "site-myst"
    clean_site(site, keep=("_build",))
    (site / "posts").mkdir(parents=True)
    covers = Covers(out, manifest, shown_as="gallery covers")
    placer = ImagePlacer(out, config)
    placer.warm(out, manifest)
    pages = 0
    for url, p in manifest.items():
        body = read_post_body(out / p["dir"])
        if body is None:
            continue
        body = rewrite_body(body, links, "../")
        page_dir = site / "posts" / Path(p["dir"]).name
        page_dir.mkdir()
        # images first: a display copy can change format, and the page
        # has to reference the name that was actually placed
        renames = place_images(out, p, page_dir, placer)
        (page_dir / f"{stems[url]}.md").write_text(
            retarget_images(page_front_matter(p, covers.path(url), names)
                            + body, renames),
            encoding="utf-8")
        covers.bake(url, page_dir)
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
