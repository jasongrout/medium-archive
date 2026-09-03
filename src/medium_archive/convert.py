"""The convert step: turn <out>/raw/ into Markdown posts in <out>/posts/,
plus posts.json and redirects.csv.

Never touches the network, so it can be re-run freely while tuning the
conversion.
"""

import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import (parse_qsl, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from .dates import parse_date
from .export import export_body, parse_export
from .fetch import archive_base, read_index
from .fixup import load_fixups, read_raw
from .images import image_source, sniff_image_ext
from .pages import (collapse_br_pairs, extract_metadata, feed_body,
                    ghost_body, ghost_metadata, is_ghost_page, page_body,
                    parse_ld_json, strip_title_prefix)
from .state import (apollo_post_state, gist_code_blocks, state_body,
                    state_metadata, state_title)
from .readme import write_readme
from .tags import load_tag_map
from .urls import canonical_url, medium_id, resolve_canonical, slug_of

EMPTY_INFO = {"title": "", "authors": [], "date": "",
              "updated": None, "description": "", "tags": []}


def feed_item_authors(feed_item: dict) -> list:
    """The RSS item's authors. Items saved before authors became a list
    carry one `author` name (raw/ is never rewritten), so read that
    form too."""
    if feed_item.get("authors"):
        return feed_item["authors"]
    if feed_item.get("author"):
        return [{"name": feed_item["author"], "url": None}]
    return []


class _Converter(MarkdownConverter):
    """markdownify, with two code-fence tweaks and figure preservation.

    Each fence is sized to its content: a <pre> whose text itself
    contains ``` lines (a post showing Markdown) would close a
    three-backtick fence early, spilling the rest of the block -- and
    everything after it -- into broken structure. And the opening fence
    carries the block's language when a nested <code
    class="language-..."> names one (the editor state's
    codeBlockMetadata, gist files, Ghost highlighting classes).

    A captioned figure keeps its <figure>/<figcaption> shell as raw
    HTML: flattening it to an image paragraph plus a text paragraph
    would lose the association Medium's markup gives a caption and its
    picture (a screen reader would hear an image and an unrelated
    paragraph). The shell lines go out blank-line separated, so
    CommonMark renderers (GitHub, Hugo's Goldmark) treat each tag as
    its own HTML block and still render the image and caption Markdown
    between them; the site exporters rewrite the shell to their native
    figure form, which is regular enough to match exactly (see
    hugo.figure_shortcodes, pelican.figure_blocks, myst.myst_figures)."""

    def convert_figure(self, el, text, parent_tags):
        if not _captioned_figure(el):
            return text
        return f"\n\n<figure>\n\n{text.strip()}\n\n</figure>\n\n"

    def convert_figcaption(self, el, text, parent_tags):
        if not _captioned_figure(el.find_parent("figure")):
            return text
        return f"\n\n<figcaption>\n\n{text.strip()}\n\n</figcaption>\n\n"

    def convert_pre(self, el, text, parent_tags):
        md = super().convert_pre(el, text, parent_tags)
        if not md:
            return md
        runs = re.findall(r"`{3,}", text)
        if runs:
            fence = "`" * (max(map(len, runs)) + 1)
            start, end = md.index("```"), md.rindex("```")
            md = md[:start] + fence + md[start + 3:end] + fence + md[end + 3:]
        code = el.find("code")
        lang = next((c[len("language-"):]
                     for c in (code.get("class") if code else None) or ()
                     if c.startswith("language-")), "")
        if lang:
            m = re.match(r"\s*`{3,}", md)
            md = md[:m.end()] + lang + md[m.end():]
        return md


def _captioned_figure(figure) -> bool:
    """figure (or None) has a non-empty caption and, outside it,
    something to caption -- an image, an embed in any of the shapes it
    passes through to_markdown in (iframe or gist script on the way in,
    link or inlined code on the way out) -- so its <figure>/<figcaption>
    shell survives conversion. A caption alone does not: some captures
    never hydrate the figure's image element."""
    if figure is None:
        return False
    cap = figure.find("figcaption")
    return bool(cap and cap.get_text(strip=True)
                and any(t.find_parent("figcaption") is None
                        for t in figure.find_all(["img", "a", "iframe",
                                                  "script", "pre"])))


def _strip_tracking(url: str) -> str:
    """Drop the `source=` telemetry parameter Medium's renderer appends
    to every link it emits, on any host. The dash-run value pattern
    (post_page----..., user_mention---...) marks it as Medium's, so a
    target site's own source parameter survives."""
    parts = urlsplit(url)
    if "source=" not in parts.query:
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if not (k == "source" and "---" in v)]
    return urlunsplit(parts._replace(query=urlencode(q)))


GIST_SRC_RE = re.compile(
    r"https?://gist\.github\.com/(?:[^/\s]+/)?([0-9a-f]+)(?:\.js)?(?:\?.*)?$")


def _archived_gist_files(media: dict, gist_id: str) -> dict | None:
    """The archived files of gist `gist_id`, from whichever media
    resource entry holds them (media entries are keyed by Medium's
    resource id, not the gist id)."""
    for entry in media.values():
        gist = entry.get("gist") or {}
        if gist.get("files") and gist_id in (
                gist.get("id"),
                ((entry.get("value") or {}).get("gist") or {}).get("gistId")):
            return gist["files"]
    return None


def to_markdown(body, base_url: str, img_map: dict, raw: Path,
                out_dir: Path | None = None, media: dict | None = None):
    """Rewrite images, iframes and links in a body and render it to
    Markdown; shared by convert and compare. With out_dir, referenced
    images are copied into out_dir/images/; without, mapped filenames are
    still used but nothing is written. `media` (convert.load_media) lets
    gist embeds inline their archived files. Returns
    (markdown, used_images)."""
    doc = BeautifulSoup("", "html.parser")        # owner for new_tag()
    # the same asset appears under miro.medium.com and cdn-images-1.medium.com
    by_basename = {Path(urlsplit(u).path).name: f for u, f in img_map.items()}

    used_images = []
    for img in body.find_all("img"):
        src = image_source(img)
        if not src:
            img.decompose()
            continue
        fname = img_map.get(src) or by_basename.get(Path(urlsplit(src).path).name)
        if fname and (out_dir is None or (raw / "images" / fname).exists()):
            src_file = raw / "images" / fname
            # an image fetched from an extensionless URL was stored as
            # .bin; the derived copy gets the extension its bytes call for
            if fname.endswith(".bin") and src_file.exists():
                fname = fname[:-len(".bin")] + (sniff_image_ext(src_file)
                                                or ".bin")
            if out_dir is not None:
                (out_dir / "images").mkdir(exist_ok=True)
                shutil.copy2(src_file, out_dir / "images" / fname)
            local = f"images/{fname}"
            used_images.append(local)
        else:
            local = src                         # not downloaded; keep remote URL
        new_img = doc.new_tag("img", src=local, alt=img.get("alt", ""))
        picture = img.find_parent("picture")
        (picture or img).replace_with(new_img)

    # Export grid layouts put several image <figure>s side by side in one
    # row, which would render run together on a single line; break them
    # onto separate lines (the page renders such grids one per line too).
    for fig in body.find_all(["figure", "img"]):
        if getattr(fig.next_sibling, "name", None) == fig.name:
            fig.insert_after(doc.new_tag("br"))

    # Export <pre> blocks break lines with <br>, which markdownify renders
    # as hard breaks (trailing double-space) -- invisible noise inside a
    # code fence, where a plain newline is the faithful form.
    for pre in body.find_all("pre"):
        for br in pre.find_all("br"):
            br.replace_with("\n")

    # Medium styles figure captions with CSS, not markup, and so do the
    # site themes, off the <figcaption> in the shell _Converter
    # preserves -- so a caption's text stays clean of styling. Only a
    # caption whose figure lost its image (some captures never hydrate
    # the element) has no shell to hang styling on: it stays a plain
    # paragraph, and italics is the Markdown idiom that keeps it
    # visually distinct from body prose.
    for cap in body.find_all("figcaption"):
        if _captioned_figure(cap.find_parent("figure")):
            continue
        if cap.get_text(strip=True) and not (
                len(cap.contents) == 1 and cap.contents[0].name in ("em", "i")):
            em = doc.new_tag("em")
            for child in list(cap.children):
                em.append(child.extract())
            cap.append(em)

    # Export and Ghost bodies embed gists as <script src=".../<id>.js">
    # tags, which would otherwise convert to nothing at all. Inline the
    # gist's archived files (raw/media/), else keep a link to the gist --
    # never drop the embed silently.
    for script in body.find_all("script"):
        m = GIST_SRC_RE.match(script.get("src") or "")
        if not m:
            continue
        files = _archived_gist_files(media or {}, m.group(1))
        if files:
            script.replace_with(BeautifulSoup(gist_code_blocks(files),
                                              "html.parser"))
        else:
            url = m.string[:m.end(1)]           # the gist's page URL
            script.replace_with(doc.new_tag("a", href=url,
                                            string=f"embed: {url}"))

    # An iframe with no source is an embed whose content the body never
    # carried (a feed body renders a gist that way: src="", 0x0). It gets
    # the same visible placeholder the state conversion uses, which lint
    # flags -- a link with no target would read as a dangling "embed:".
    for iframe in body.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        if src:
            iframe.replace_with(doc.new_tag("a", href=src, string=f"embed: {src}"))
        else:
            iframe.replace_with(doc.new_tag("p", string="[missing embed]"))

    # Medium's editor emits things like <strong> </strong> between runs;
    # markdownify drops whitespace-only emphasis, losing the space.
    for el in body.find_all(["strong", "em", "b", "i"]):
        if el.parent is not None and not el.get_text().strip():
            el.replace_with(el.get_text())

    # The rendered page links same-publication posts relatively; those
    # would break off Medium (and redirects.csv matches absolute URLs).
    for a in body.find_all("a"):
        href = a.get("href")
        if href and not href.startswith(("#", "mailto:")):
            # export hrefs can contain literal spaces, which break the
            # Markdown link syntax
            a["href"] = _strip_tracking(urljoin(base_url, href).replace(" ", "%20"))

    markdown = _Converter(heading_style="ATX", bullets="-",
                          strip=["span"]).convert(str(body))
    # Export bodies keep the editor's non-breaking/hair spaces; the rendered
    # page serves plain spaces. Normalize so output is stable across sources.
    markdown = markdown.replace("\u00a0", " ").replace("\u200a", " ")
    # markdownify renders the grid-separating <br>s as whitespace-only
    # "hard break" lines; those are just blank lines to Markdown, so
    # normalize them away -- except in code fences, where whitespace is
    # content.
    lines, fence = markdown.split("\n"), False
    for i, line in enumerate(lines):
        if re.match(r"^`{3,}", line):
            fence = not fence
        elif not fence and line.strip() == "":
            lines[i] = ""
    markdown = "\n".join(lines)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    markdown = re.sub(r"(?:\n-{3,}\n)?\n[^\n]*was originally published[^\n]*\n*$", "\n", markdown)
    # A body must not open with a section divider: it is the separator
    # that followed the (removed) subtitle block, and a leading --- also
    # reads as more front matter to some Markdown tooling.
    markdown = re.sub(r"^(?:-{3,}\n+)+", "", markdown)
    return markdown, used_images


def load_media(raw: Path, fixups: dict = None) -> dict:
    """Archived embed media resources (raw/media/, saved by fetch for
    embeds the page state leaves unresolved): {resource_id: {"value":
    the medium.com/media payload's value, "gist": the GitHub gist API
    response with the gist's files}}, either part absent when not
    archived."""
    media_dir = raw / "media"
    if not media_dir.is_dir():
        return {}
    media = {}
    for p in sorted(media_dir.glob("*.json")):
        if p.name.endswith(".gist.json"):
            continue
        payload = json.loads(read_raw(p, fixups))
        entry = {"value": (payload.get("payload") or {}).get("value") or {}}
        gist_file = p.with_name(f"{p.stem}.gist.json")
        if gist_file.exists():
            entry["gist"] = json.loads(read_raw(gist_file, fixups))
        media[p.stem] = entry
    return media


def convert_post(url: str, raw: Path, posts_root: Path, prefer_page: bool,
                 prefer_ghost: bool = False, fixups: dict = None,
                 tag_map=None) -> dict:
    soup = None
    state = None
    ghost = page_shell = False
    if (raw / "page.html").exists():
        page_text = read_raw(raw / "page.html", fixups)
        soup = BeautifulSoup(page_text, "html.parser")
        ghost = is_ghost_page(soup)   # a Ghost capture saved by import-ghost
        info = ghost_metadata(soup, url) if ghost else extract_metadata(soup, url)
        # Medium sometimes serves an empty app shell -- nav chrome with no
        # article markup, JSON-LD or title. Converting it would produce a
        # post of nav links, and it is long enough to slip past the short-
        # body warning; it is not a body source at all. But the data the
        # client would have rendered is usually still in the page, in its
        # embedded editor state -- recover from that.
        page_shell = (not ghost and soup.find("article") is None
                      and not parse_ld_json(soup) and not info["title"])
        if not ghost:
            state = apollo_post_state(page_text, raw.name)
        if page_shell and state is not None:
            info.update(state_metadata(state, raw.name))
            info["url"] = info["url"] or url
        elif state is not None:
            # a title Medium truncated, completed from the opening heading
            info["title"] = state_title(state, raw.name, info["title"])
    else:
        info = {"url": url, **EMPTY_INFO}

    # A Ghost capture attached to a Medium post (import-ghost found the post
    # archived under both URLs); an alternate body source, like export.html.
    ghost_soup, gmeta = None, {}
    if (raw / "ghost.html").exists():
        ghost_soup = BeautifulSoup(read_raw(raw / "ghost.html", fixups),
                                   "html.parser")
    if (raw / "ghost.json").exists():
        gmeta = json.loads(read_raw(raw / "ghost.json", fixups))

    feed_item = None
    if (raw / "feed_item.json").exists():
        feed_item = json.loads(read_raw(raw / "feed_item.json", fixups))
        info["authors"] = info["authors"] or feed_item_authors(feed_item)
        info["title"] = info["title"] or feed_item.get("title", "")
        if feed_item.get("tags"):
            info["tags"] = feed_item["tags"]
        if not info["date"] and feed_item.get("date"):
            d = parse_date(feed_item["date"])
            info["date"] = d.isoformat() if d else ""

    exp = None
    if (raw / "export.html").exists():
        exp = parse_export(read_raw(raw / "export.html", fixups))
        info["title"] = info["title"] or exp["title"]
        info["authors"] = info["authors"] or exp["authors"]
        if exp["date"]:
            info["date"] = exp["date"]      # exact first-publish timestamp
        if exp["subtitle"]:
            info["description"] = exp["subtitle"]   # the real subtitle
        if soup is None and exp["canonical_url"]:
            info["url"] = exp["canonical_url"]

    # Whichever source the title and the description came from, the
    # description is the summary alone: a page-scraped or state-read one
    # may still open with the title (see strip_title_prefix), and the
    # title is only final here, after the feed and the export have had
    # their say.
    info["description"] = strip_title_prefix(info["description"], info["title"])

    info["url"], external_canonical = resolve_canonical(url, info["url"])

    img_map = {}
    if (raw / "images.json").exists():
        img_map = json.loads(read_raw(raw / "images.json", fixups))
    media = load_media(raw, fixups)

    have_feed = bool(feed_item and feed_item.get("content_html"))
    have_page = soup is not None and not page_shell
    if not have_page and exp is None and ghost_soup is None and not have_feed \
            and state is None:
        raise RuntimeError(
            "page.html is Medium's empty app shell (no article or embedded "
            "state); re-fetch it" if page_shell else
            "no page.html, export.html, ghost.html or feed body to convert")
    if ghost:                          # page.html is itself a Ghost capture
        body, body_source = ghost_body(soup), "ghost"
    elif ghost_soup is not None and (prefer_ghost
                                     or not (have_page or exp or have_feed
                                             or state is not None)):
        body, body_source = ghost_body(ghost_soup), "ghost"
    elif have_page and prefer_page:
        body, body_source = page_body(soup, info["tags"], info["title"]), "page"
    elif exp:
        body, body_source = export_body(exp["soup"]), "export"
    elif have_feed:
        body, body_source = feed_body(feed_item["content_html"]), "feed"
    elif state is not None:            # the page's embedded editor state
        body = state_body(state, raw.name, info["title"], media)
        body_source = "state"
    else:                              # a page without embedded state
        body, body_source = page_body(soup, info["tags"], info["title"]), "page"

    # A post with a Ghost origin carries Medium's migration line-break
    # damage in its Medium-side sources; the Ghost capture itself doesn't.
    if gmeta and body_source != "ghost":
        collapse_br_pairs(body)

    out_dir = posts_root / f"{(info['date'] or '')[:10] or 'undated'}-{slug_of(url)}"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    markdown, used_images = to_markdown(body, info["url"], img_map, raw,
                                        out_dir, media)
    if "Continue reading on" in markdown and len(markdown) < 2000:
        print("  warning: body looks truncated", file=sys.stderr)
    if len(markdown) < 200:
        print(f"  warning: body is only {len(markdown)} chars; check selectors", file=sys.stderr)

    canon = info["url"]                 # already resolved and canonicalized
    ghost_url = gmeta.get("original_url")
    front = {
        "title": info["title"],
        "authors": info["authors"],
        "date": info["date"],
        "updated": info["updated"],
        "original_url": canon,
        "original_path": urlparse(canon).path,
        "medium_id": medium_id(canon),
        "slug": slug_of(canon),
        # a canonical URL the post declared that names a different page (a
        # gist it was imported from, a pre-migration slug); provenance only
        "canonical_url": external_canonical,
        # the post's URL on the blog's Ghost incarnation, when import-ghost
        # attached a capture; old inbound links may carry this path too
        "ghost_url": ghost_url if ghost_url != canon else None,
        "description": info["description"],
        # tags.json cleanup applies only here, at output: body extraction
        # above needs the original tags to recognize the page's tag-link
        # chrome, and raw/ keeps them untouched
        "tags": (tag_map.apply(info["tags"], slug_of(canon)) if tag_map
                 else sorted(set(info["tags"]))),
        "images": used_images,
        "body_source": body_source,
    }
    with open(out_dir / "index.md", "w", encoding="utf-8") as fh:
        fh.write("---\n")
        fh.write(json.dumps(front, indent=2, ensure_ascii=False))   # JSON is valid YAML
        fh.write("\n---\n\n")
        fh.write(markdown)
    return {**front, "dir": str(out_dir.relative_to(posts_root.parent))}


def write_redirects(manifest: dict, out: Path):
    def q(v):
        v = "" if v is None else str(v)
        return '"' + v.replace('"', '""') + '"' if any(c in v for c in ',"\n') else v
    rows = ["original_path,medium_id,original_url,new_dir,date,title"]
    for url, p in sorted(manifest.items(), key=lambda kv: kv[1].get("date") or ""):
        rows.append(",".join(q(x) for x in (
            p.get("original_path"), p.get("medium_id"), url, Path(p["dir"]).name,
            (p.get("date") or "")[:10], p.get("title"))))
        if p.get("ghost_url"):    # old inbound links to the Ghost URL, too
            rows.append(",".join(q(x) for x in (
                urlparse(p["ghost_url"]).path, p.get("medium_id"), p["ghost_url"],
                Path(p["dir"]).name, (p.get("date") or "")[:10], p.get("title"))))
    (out / "redirects.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def cmd_convert(args):
    raw_dir = args.out / "raw"
    index = read_index(raw_dir)
    if not index:
        sys.exit(f"nothing to convert: {raw_dir}/index.json missing or empty (run fetch first)")
    posts_root = args.out / "posts"
    if args.clean:
        shutil.rmtree(posts_root, ignore_errors=True)
    manifest_path = args.out / "posts.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() and not args.clean else {}

    targets = [canonical_url(u) for u in args.only] if args.only else list(index)
    fixups = load_fixups(args.out)
    if fixups:
        print(f"fixups: patching {len(fixups)} raw file(s) in memory "
              f"from {args.out / 'fixups'}", file=sys.stderr)
    tag_map = load_tag_map(args.out)
    if tag_map:
        print(f"tags: dropping {len(tag_map.drop)}, renaming "
              f"{len(tag_map.rename)}, implying from {len(tag_map.imply)}, "
              f"adding to {len(tag_map.add)} and removing from "
              f"{len(tag_map.remove)} post(s), naming "
              f"{len(tag_map.display)} per {tag_map.path}",
              file=sys.stderr)
    ok = 0
    for n, url in enumerate(targets, 1):
        entry = index.get(url)
        if not entry:
            print(f"[{n}/{len(targets)}] not in raw archive: {url}", file=sys.stderr)
            continue
        raw = raw_dir / entry["medium_id"]
        print(f"[{n}/{len(targets)}] {url}", file=sys.stderr)
        try:
            manifest[url] = convert_post(url, raw, posts_root, args.prefer_page,
                                         getattr(args, "prefer_ghost", False),
                                         fixups, tag_map)
            ok += 1
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    if manifest:
        write_redirects(manifest, args.out)
    if not (args.out / "README.md").exists():
        write_readme(args.out, args.base or archive_base(args.out) or "(unknown publication)")
    print(f"convert done: {ok}/{len(targets)} posts -> {posts_root}", file=sys.stderr)
    # A tags.json entry that changed no post is stale config -- fail
    # loudly, like a fixup that no longer applies. Only a complete run
    # can tell (--only sees a subset; a failed post's tags go unseen).
    if tag_map and not args.only and ok == len(targets):
        unused = tag_map.unused()
        if unused:
            sys.exit(f"{tag_map.path}: entries changed no post: "
                     f"{', '.join(unused)} (remove the stale entries, "
                     "or fix their spelling)")
