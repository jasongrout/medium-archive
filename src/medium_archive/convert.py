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
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

from .dates import parse_date
from .fetch import read_index
from .images import image_source
from .pages import extract_metadata, feed_body, page_body
from .readme import write_readme
from .urls import canonical_url, medium_id, slug_of


def convert_post(url: str, raw: Path, posts_root: Path, prefer_page: bool) -> dict:
    page_html = (raw / "page.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(page_html, "html.parser")
    info = extract_metadata(soup, url)

    feed_item = None
    if (raw / "feed_item.json").exists():
        feed_item = json.loads((raw / "feed_item.json").read_text())
        info["author"] = info["author"] or feed_item.get("author", "")
        info["title"] = info["title"] or feed_item.get("title", "")
        if feed_item.get("tags"):
            info["tags"] = feed_item["tags"]
        if not info["date"] and feed_item.get("date"):
            d = parse_date(feed_item["date"])
            info["date"] = d.isoformat() if d else ""

    img_map = {}
    if (raw / "images.json").exists():
        img_map = json.loads((raw / "images.json").read_text())

    if feed_item and feed_item.get("content_html") and not prefer_page:
        body, body_source = feed_body(feed_item["content_html"]), "feed"
    else:
        body, body_source = page_body(soup), "page"
    doc = body if body.parent is None else soup   # owner for new_tag()

    out_dir = posts_root / f"{(info['date'] or '')[:10] or 'undated'}-{slug_of(url)}"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    used_images = []
    for img in body.find_all("img"):
        src = image_source(img)
        if not src:
            img.decompose()
            continue
        fname = img_map.get(src)
        if fname and (raw / "images" / fname).exists():
            (out_dir / "images").mkdir(exist_ok=True)
            shutil.copy2(raw / "images" / fname, out_dir / "images" / fname)
            local = f"images/{fname}"
            used_images.append(local)
        else:
            local = src                         # not downloaded; keep remote URL
        new_img = doc.new_tag("img", src=local, alt=img.get("alt", ""))
        picture = img.find_parent("picture")
        (picture or img).replace_with(new_img)

    for iframe in body.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        iframe.replace_with(doc.new_tag("a", href=src, string=f"[embed: {src}]"))

    markdown = html_to_md(str(body), heading_style="ATX", bullets="-", strip=["span"])
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    markdown = re.sub(r"(?:\n-{3,}\n)?\n[^\n]*was originally published[^\n]*\n*$", "\n", markdown)
    if "Continue reading on" in markdown and len(markdown) < 2000:
        print("  warning: body looks truncated", file=sys.stderr)
    if len(markdown) < 200:
        print(f"  warning: body is only {len(markdown)} chars; check selectors", file=sys.stderr)

    canon = canonical_url(info["url"])
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
    ok = 0
    for n, url in enumerate(targets, 1):
        entry = index.get(url)
        if not entry:
            print(f"[{n}/{len(targets)}] not in raw archive: {url}", file=sys.stderr)
            continue
        raw = raw_dir / entry["medium_id"]
        print(f"[{n}/{len(targets)}] {url}", file=sys.stderr)
        try:
            manifest[url] = convert_post(url, raw, posts_root, args.prefer_page)
            ok += 1
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    if manifest:
        write_redirects(manifest, args.out)
    if not (args.out / "README.md").exists():
        write_readme(args.out, args.base)
    print(f"convert done: {ok}/{len(targets)} posts -> {posts_root}", file=sys.stderr)
