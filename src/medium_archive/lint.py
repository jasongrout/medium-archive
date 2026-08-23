"""The lint step: scan converted posts for conversion-defect signatures.

Each check encodes a defect that has actually occurred -- leftover Medium
chrome, an unclosed code fence, a missing image file -- so regressions in
the conversion surface on every run instead of waiting for a reader.
Exits non-zero when a defect (not a warning) is found, so it can gate
scripts the way compare does.
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

FENCE_RE = re.compile(r"^`{3,}")


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


def lint_post(post_dir: Path) -> tuple[list, list]:
    """(errors, warnings) for one converted post directory."""
    errors, warnings = [], []
    text = (post_dir / "index.md").read_text(encoding="utf-8")
    front, body = split_post(text)
    if front is None:
        return ["no front matter block"], []

    for line, fenced in prose_lines(body):
        if not fenced and CHROME_RE.search(line):
            errors.append(f"Medium chrome in body: {line.strip()[:80]!r}")
        if not fenced:
            m = MEDIUM_CDN_RE.search(line)
            if m:
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
    return errors, warnings


def cmd_lint(args):
    posts_root = args.out / "posts"
    dirs = sorted(d for d in posts_root.iterdir() if (d / "index.md").is_file()) \
        if posts_root.is_dir() else []
    if not dirs:
        sys.exit(f"nothing to lint: no posts under {posts_root} (run convert first)")
    n_err = n_warn = 0
    for d in dirs:
        errors, warnings = lint_post(d)
        for msg in errors:
            print(f"{d.name}: {msg}")
        for msg in warnings:
            print(f"{d.name}: warning: {msg}")
        n_err += len(errors)
        n_warn += len(warnings)
    print(f"lint done: {len(dirs)} posts, {n_err} problem(s), "
          f"{n_warn} warning(s)", file=sys.stderr)
    if n_err:
        sys.exit(1)
