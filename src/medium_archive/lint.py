"""The lint step: scan converted posts for conversion-defect signatures.

Each check encodes a defect that has actually occurred -- leftover Medium
chrome, an unclosed code fence, a missing image file -- so regressions in
the conversion surface on every run instead of waiting for a reader.
Exits non-zero when a defect (not a warning) is found, so it can gate
scripts the way compare does.

`--seo` adds the page analysis WordPress's SEO plugins run on every
post, as warnings: a description that is missing or longer than a
search result shows, a title longer than one shows, a body image with
no alt text, a post with no image a card or a share could carry, and
two posts with the same title. None is a conversion defect -- each is
a fact about the post as it was written -- so they are asked for
rather than reported on every run.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

# Nav/UI text and link markers that only occur in Medium page chrome,
# never in an article body.
CHROME_RE = re.compile(
    r"\?operation=login|\?operation=register|source=post_page---byline|"
    r"Press enter or click to view image in full size|"
    r"was originally published (in|on) ",
)

# Body images should have been localized; a Medium CDN URL means either
# leaked chrome or an image the fetch step never downloaded.
MEDIUM_CDN_RE = re.compile(
    r"!\[[^\]]*\]\((https?://(?:miro\.medium\.com|cdn-images-\d+\.medium\.com)[^)]*)\)")

IMAGE_RE = re.compile(r"!\[[^\]]*\]\((images/[^)]+)\)")

# convert's placeholder for an embed whose content was never archived
# (a gist embed with no raw/<id>/media/ files); markdownify may escape
# the bracket
MISSING_EMBED_RE = re.compile(r"\\?\[missing embed")

FENCE_RE = re.compile(r"^`{3,}")

# The page analysis WordPress's SEO plugins run (--seo): where a search
# result cuts a title and a description, per their own defaults
TITLE_MAX = 60
DESCRIPTION_MAX = 160
BARE_IMAGE_RE = re.compile(r"!\[\]\((images/[^)]+)\)")


def split_post(text: str):
    """(front matter dict, body) of an index.md."""
    m = re.match(r"---\n(.*?)\n---\n\n?", text, re.S)
    if not m:
        return None, text
    return json.loads(m.group(1)), text[m.end():]


def prose_lines(body: str):
    """(line, in_fence) pairs; checks that only apply to prose skip
    fenced lines, where e.g. a literal ![](https://...) is content."""
    fence = False
    for line in body.split("\n"):
        if FENCE_RE.match(line):
            fence = not fence
            continue
        yield line, fence


def seo_warnings(front: dict, body: str, post_dir: Path) -> list:
    """The --seo page analysis for one post (see the module docstring),
    as warnings. An image with an empty alt inside a captioned figure
    is not reported: the site exporters fill that alt from the caption
    (sites.caption_text)."""
    warnings = []
    title, description = front.get("title") or "", front.get("description") or ""
    if len(title) > TITLE_MAX:
        warnings.append(f"title is {len(title)} chars; a search result "
                        f"shows about {TITLE_MAX}")
    if not description:
        warnings.append("no description: search results and share cards "
                        "get the site's, or none")
    elif len(description) > DESCRIPTION_MAX:
        warnings.append(f"description is {len(description)} chars; a "
                        f"search result shows about {DESCRIPTION_MAX}")
    lines = [line for line, fenced in prose_lines(body) if not fenced]
    for i, line in enumerate(lines):
        m = BARE_IMAGE_RE.search(line)
        if not m:
            continue
        following = [x for x in lines[i + 1:i + 3] if x.strip()]
        if following and following[0].startswith("<figcaption>"):
            continue
        warnings.append(f"image without alt text: {m.group(1)}")
    from .sites import pick_cover       # sites imports this module
    if not pick_cover(front, post_dir):
        warnings.append("no image a card cover or a share preview could "
                        "use (site.json \"share_image\" stands in)")
    return warnings


def lint_post(post_dir: Path, seo: bool = False) -> tuple[list, list]:
    """(errors, warnings) for one converted post directory; seo adds
    the page-analysis warnings (see seo_warnings)."""
    errors, warnings = [], []
    text = (post_dir / "index.md").read_text(encoding="utf-8")
    front, body = split_post(text)
    if front is None:
        return ["no front matter block"], []

    for line, fenced in prose_lines(body):
        if not fenced and CHROME_RE.search(line):
            errors.append(f"Medium chrome in body: {line.strip()[:80]!r}")
        if not fenced and MISSING_EMBED_RE.search(line):
            errors.append(f"embed content not archived: {line.strip()[:80]!r} "
                          "(re-run fetch to archive its media)")
        if not fenced:
            m = MEDIUM_CDN_RE.search(line)
            if m:
                # a body recovered from the page's embedded editor state
                # keeps remote URLs by design until the post is re-fetched
                # with its images; anywhere else a CDN URL is a defect
                if front.get("body_source") == "state":
                    warnings.append("remote image, not fetched yet: "
                                    f"{m.group(1)[:80]}")
                else:
                    errors.append(f"remote Medium CDN image: {m.group(1)[:80]}")

    if sum(1 for line in body.split("\n") if FENCE_RE.match(line)) % 2:
        errors.append("odd number of code-fence lines (unclosed fence)")

    if "[[embed:" in body:
        errors.append("double-bracket embed link")

    for rel in IMAGE_RE.findall(body):
        if not (post_dir / unquote(rel)).exists():
            errors.append(f"referenced image missing on disk: {rel}")

    if not front.get("title"):
        warnings.append("empty title")
    if not front.get("date"):
        warnings.append("empty date")
    if len(body) < 200:
        warnings.append(f"body is only {len(body)} chars")
    if seo:
        warnings.extend(seo_warnings(front, body, post_dir))
    return errors, warnings


def duplicate_titles(titles: dict) -> list:
    """Warnings for titles shared by several posts (post dir -> title):
    two pages with one title compete for the same query, and a search
    result cannot tell them apart."""
    by_title = {}
    for name, title in titles.items():
        if title:
            by_title.setdefault(title.strip().lower(), []).append(name)
    return [f"title shared by {len(names)} posts: {names[0]!r} and "
            f"{', '.join(repr(n) for n in names[1:])} "
            f"({titles[names[0]]!r})"
            for names in by_title.values() if len(names) > 1]


def cmd_lint(args):
    posts_root = args.out / "posts"
    dirs = sorted(d for d in posts_root.iterdir() if (d / "index.md").is_file()) \
        if posts_root.is_dir() else []
    if not dirs:
        sys.exit(f"nothing to lint: no posts under {posts_root} (run convert first)")
    n_err = n_warn = 0
    seo = getattr(args, "seo", False)
    titles = {}
    for d in dirs:
        errors, warnings = lint_post(d, seo=seo)
        for msg in errors:
            print(f"{d.name}: {msg}")
        for msg in warnings:
            print(f"{d.name}: warning: {msg}")
        n_err += len(errors)
        n_warn += len(warnings)
        if seo:
            front, _ = split_post((d / "index.md").read_text(encoding="utf-8"))
            titles[d.name] = (front or {}).get("title") or ""
    for msg in duplicate_titles(titles):
        print(f"warning: {msg}")
        n_warn += 1
    print(f"lint done: {len(dirs)} posts, {n_err} problem(s), "
          f"{n_warn} warning(s)", file=sys.stderr)
    if n_err:
        sys.exit(1)
