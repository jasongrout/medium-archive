"""The myst step: build a MyST (mystmd) site in <out>/site/ from the
converted archive -- one page per post with its images, a chronological
landing page, a year-grouped table of contents, and a site-level redirect
map.

Works from posts.json and <out>/posts/ alone (run convert first), so the
site is as reproducible as the posts are: raw/ + fixups/ -> convert ->
posts/ -> myst -> site/. Never touches the network; rendering the site
(`myst start` or `myst build --html` inside <out>/site/) is mystmd's job,
not this step's.

The posts/ layer stays generator-agnostic Markdown; everything
MyST-specific happens here: front matter is reshaped to MyST's schema
(authors, tags), page URLs are chosen (each page's filename is its URL
slug), links between posts in the publication are rewritten from Medium
URLs to site-relative page links, and redirects.csv maps every old inbound
path to its new page URL.

Site-wide text (title, description, the landing-page intro) comes from an
optional hand-written <out>/site.json, so it is versioned with the archive
and survives regeneration.
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .lint import split_post
from .urls import medium_id

P_PATH_RE = re.compile(r"^/p/([0-9a-f]{8,12})$")   # Medium's short post URL
LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")  # inline [text](url)
AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")  # autolink <url>
# Segments MyST-escaping must leave alone: inline code, link destinations,
# autolinks. Everything else in a prose line is text MyST will parse.
PROTECT_RE = re.compile(r"(`+[^`]*`+|\]\([^)\s]*\)|<https?://[^>\s]+>)")
AT_RE = re.compile(r"(?<![\w\\])@(?=\w)")          # @handle, not an email's @
DOLLAR_RE = re.compile(r"(?<!\\)\$")


def _yml(value) -> str:
    """A scalar or flow list as YAML, via JSON (valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def page_stems(manifest: dict) -> dict:
    """url -> page filename stem, which mystmd uses as the page's URL slug
    (paths do not survive into site URLs -- the namespace is flat). The
    Medium slug alone, unless several posts share it (deleted-and-
    republished announcements, yearly series); those keep their date
    prefix so every page URL is distinct and stable."""
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
            page = (Path(p["dir"]).name, stems[url])   # (post dir, file stem)
            for u in (p["original_url"], p.get("ghost_url"),
                      p.get("canonical_url")):
                if u:
                    parts = urlsplit(u)
                    self.by_path[(parts.netloc.lower(),
                                  unquote(parts.path).rstrip("/"))] = page
            if p.get("medium_id"):
                self.by_id[p["medium_id"]] = page

    def page_for(self, url: str):
        """(post dir, file stem, fragment) or None."""
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
    for a post page, "posts/" for the landing page). Fenced code is left
    alone: a URL there is content."""
    def rel(url):
        hit = links.page_for(url)
        if hit is None:
            return None
        d, stem, frag = hit
        return f"{prefix}{d}/{stem}.md" + (f"#{frag}" if frag else "")

    def inline(m):
        return f"]({rel(m.group(1)) or m.group(1)})"

    def auto(m):
        target = rel(m.group(1))
        return f"[{m.group(1)}]({target})" if target else m.group(0)

    out, fence = [], False
    for line in markdown.split("\n"):
        if re.match(r"^`{3,}", line):
            fence = not fence
        elif not fence:
            line = LINK_RE.sub(inline, line)
            line = AUTOLINK_RE.sub(auto, line)
            line = escape_prose(line)
        out.append(line)
    return "\n".join(out)


def page_front_matter(post: dict) -> str:
    """The post's front matter reshaped to MyST's schema. Archive
    provenance fields (original_url, medium_id, body_source, ...) stay in
    posts/ and posts.json; a site page carries only what MyST renders."""
    lines = [f"title: {_yml(post['title'])}"]
    if post.get("description"):
        lines.append(f"description: {_yml(post['description'])}")
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


def _link_or_copy(src: Path, dst: Path):
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


def write_myst_yml(site: Path, manifest: dict, stems: dict, config: dict):
    lines = ["# Generated by `medium-archive myst`; do not edit.",
             "# Site title/description/intro come from <out>/site.json.",
             "version: 1",
             "project:",
             f"  title: {_yml(config['title'])}"]
    if config.get("description"):
        lines.append(f"  description: {_yml(config['description'])}")
    lines += ["  toc:",
              "    - file: index.md"]
    for year, posts in by_year(manifest):
        lines.append(f"    - title: {_yml(year)}")
        lines.append("      children:")
        for url, p in posts:
            lines.append(f"        - file: posts/{Path(p['dir']).name}/{stems[url]}.md")
    lines += ["site:",
              "  template: book-theme",
              f"  title: {_yml(config['title'])}"]
    (site / "myst.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_landing(site: Path, manifest: dict, stems: dict, config: dict):
    esc = lambda t: escape_prose(t.replace("[", "\\[").replace("]", "\\]"))
    lines = ["---", f"title: {_yml(config['title'])}", "---", ""]
    if config.get("intro"):
        lines += [config["intro"].rstrip(), ""]
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
    (site / "index.md").write_text("\n".join(lines), encoding="utf-8")


def write_site_redirects(site: Path, manifest: dict, stems: dict):
    """Old inbound path -> new page URL, one row per path a post was ever
    reachable under: the Medium slug+id path, Medium's /p/<id> short form,
    and the Ghost-era path when there is one. The archive-root
    redirects.csv maps to posts/ directories; this one maps to the URLs
    the site actually serves."""
    def q(v):
        v = "" if v is None else str(v)
        return '"' + v.replace('"', '""') + '"' if any(c in v for c in ',"\n') else v
    rows = ["old_path,new_path,original_url"]
    for url, p in sorted(manifest.items(), key=lambda kv: kv[1].get("date") or ""):
        new = f"/{stems[url]}"
        rows.append(",".join(q(x) for x in (p["original_path"], new, url)))
        if p.get("medium_id"):
            rows.append(",".join(q(x) for x in (f"/p/{p['medium_id']}", new, url)))
        if p.get("ghost_url"):
            ghost_path = urlsplit(p["ghost_url"]).path
            if ghost_path != p["original_path"]:
                rows.append(",".join(q(x) for x in (ghost_path, new, p["ghost_url"])))
    (site / "redirects.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def build_site(out: Path) -> Path:
    manifest_path = out / "posts.json"
    if not manifest_path.exists():
        sys.exit(f"nothing to build: {manifest_path} missing (run convert first)")
    manifest = json.loads(manifest_path.read_text())
    if not manifest:
        sys.exit("nothing to build: posts.json is empty (run convert first)")

    config = {"title": "Blog archive"}
    if (out / "site.json").exists():
        config.update(json.loads((out / "site.json").read_text()))

    stems = page_stems(manifest)
    links = LinkMap(manifest, stems)
    # Rebuild from scratch, but keep mystmd's _build/ (its template cache
    # and rendered output) so regenerating doesn't force a re-download.
    site = out / "site"
    if site.exists():
        for child in site.iterdir():
            if child.name != "_build":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    (site / "posts").mkdir(parents=True)

    pages = 0
    for url, p in manifest.items():
        src = out / p["dir"]
        if not (src / "index.md").exists():
            print(f"skipping (no index.md; re-run convert): {p['dir']}",
                  file=sys.stderr)
            continue
        front, body = split_post((src / "index.md").read_text(encoding="utf-8"))
        del front  # the manifest carries the same fields
        body = rewrite_body(body, links, "../")
        page_dir = site / "posts" / Path(p["dir"]).name
        page_dir.mkdir()
        (page_dir / f"{stems[url]}.md").write_text(
            page_front_matter(p) + body, encoding="utf-8")
        if (src / "images").is_dir():
            (page_dir / "images").mkdir()
            for img in sorted((src / "images").iterdir()):
                _link_or_copy(img, page_dir / "images" / img.name)
        pages += 1

    write_landing(site, manifest, stems, config)
    write_myst_yml(site, manifest, stems, config)
    write_site_redirects(site, manifest, stems)
    print(f"myst done: {pages}/{len(manifest)} pages -> {site}", file=sys.stderr)
    print(f"render it with: cd {site} && myst start   (or: myst build --html)",
          file=sys.stderr)
    return site


def cmd_myst(args):
    build_site(args.out)
