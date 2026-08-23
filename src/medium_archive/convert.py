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
from urllib.parse import urljoin, urlparse, urlsplit

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from .dates import parse_date
from .export import export_body, parse_export
from .fetch import archive_base, read_index
from .fixup import load_fixups, read_raw
from .images import image_source
from .pages import (extract_metadata, feed_body, ghost_body, ghost_metadata,
                    is_ghost_page, page_body)
from .readme import write_readme
from .urls import canonical_url, medium_id, resolve_canonical, slug_of

EMPTY_INFO = {"title": "", "author": "", "author_url": None, "date": "",
              "updated": None, "description": "", "tags": []}


class _Converter(MarkdownConverter):
    """markdownify, with each code fence sized to its content: a <pre>
    whose text itself contains ``` lines (a post showing Markdown) would
    close a three-backtick fence early, spilling the rest of the block --
    and everything after it -- into broken structure."""

    def convert_pre(self, el, text, parent_tags):
        md = super().convert_pre(el, text, parent_tags)
        runs = re.findall(r"`{3,}", text)
        if not md or not runs:
            return md
        fence = "`" * (max(map(len, runs)) + 1)
        start, end = md.index("```"), md.rindex("```")
        return md[:start] + fence + md[start + 3:end] + fence + md[end + 3:]


def to_markdown(body, base_url: str, img_map: dict, raw: Path, out_dir: Path | None = None):
    """Rewrite images, iframes and links in a body and render it to
    Markdown; shared by convert and compare. With out_dir, referenced
    images are copied into out_dir/images/; without, mapped filenames are
    still used but nothing is written. Returns (markdown, used_images)."""
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
            if out_dir is not None:
                (out_dir / "images").mkdir(exist_ok=True)
                shutil.copy2(raw / "images" / fname, out_dir / "images" / fname)
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

    for iframe in body.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        iframe.replace_with(doc.new_tag("a", href=src, string=f"[embed: {src}]"))

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
            a["href"] = urljoin(base_url, href).replace(" ", "%20")

    markdown = _Converter(heading_style="ATX", bullets="-",
                          strip=["span"]).convert(str(body))
    # Export bodies keep the editor's non-breaking/hair spaces; the rendered
    # page serves plain spaces. Normalize so output is stable across sources.
    markdown = markdown.replace("\u00a0", " ").replace("\u200a", " ")
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    markdown = re.sub(r"(?:\n-{3,}\n)?\n[^\n]*was originally published[^\n]*\n*$", "\n", markdown)
    return markdown, used_images


def convert_post(url: str, raw: Path, posts_root: Path, prefer_page: bool,
                 prefer_ghost: bool = False, fixups: dict = None) -> dict:
    soup = None
    ghost = False
    if (raw / "page.html").exists():
        soup = BeautifulSoup(read_raw(raw / "page.html", fixups), "html.parser")
        ghost = is_ghost_page(soup)   # a Ghost capture saved by import-ghost
        info = ghost_metadata(soup, url) if ghost else extract_metadata(soup, url)
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
        info["author"] = info["author"] or feed_item.get("author", "")
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
        info["author"] = info["author"] or exp["author"]
        info["author_url"] = info["author_url"] or exp["author_url"]
        if exp["date"]:
            info["date"] = exp["date"]      # exact first-publish timestamp
        if exp["subtitle"]:
            info["description"] = exp["subtitle"]   # the real subtitle, no title mashed in
        if soup is None and exp["canonical_url"]:
            info["url"] = exp["canonical_url"]

    info["url"], external_canonical = resolve_canonical(url, info["url"])

    img_map = {}
    if (raw / "images.json").exists():
        img_map = json.loads(read_raw(raw / "images.json", fixups))

    have_feed = bool(feed_item and feed_item.get("content_html"))
    if soup is None and exp is None and ghost_soup is None and not have_feed:
        raise RuntimeError("no page.html, export.html, ghost.html or feed body to convert")
    if ghost:                          # page.html is itself a Ghost capture
        body, body_source = ghost_body(soup), "ghost"
    elif ghost_soup is not None and (prefer_ghost
                                     or not (soup is not None or exp or have_feed)):
        body, body_source = ghost_body(ghost_soup), "ghost"
    elif soup is not None and (prefer_page or not (exp or have_feed)):
        body, body_source = page_body(soup, info["tags"]), "page"
    elif exp:
        body, body_source = export_body(exp["soup"]), "export"
    else:
        body, body_source = feed_body(feed_item["content_html"]), "feed"

    out_dir = posts_root / f"{(info['date'] or '')[:10] or 'undated'}-{slug_of(url)}"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    markdown, used_images = to_markdown(body, info["url"], img_map, raw, out_dir)
    if "Continue reading on" in markdown and len(markdown) < 2000:
        print("  warning: body looks truncated", file=sys.stderr)
    if len(markdown) < 200:
        print(f"  warning: body is only {len(markdown)} chars; check selectors", file=sys.stderr)

    canon = info["url"]                 # already resolved and canonicalized
    ghost_url = gmeta.get("original_url")
    front = {
        "title": info["title"],
        "author": info["author"],
        "author_url": info["author_url"],
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
        "tags": sorted(set(info["tags"])),
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
                                         fixups)
            ok += 1
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    if manifest:
        write_redirects(manifest, args.out)
    if not (args.out / "README.md").exists():
        write_readme(args.out, args.base or archive_base(args.out) or "(unknown publication)")
    print(f"convert done: {ok}/{len(targets)} posts -> {posts_root}", file=sys.stderr)
