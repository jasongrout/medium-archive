"""The lint step: scan converted posts for conversion-defect signatures.

Each check encodes a defect that has actually occurred -- leftover Medium
chrome, an unclosed code fence, a missing image file -- so regressions in
the conversion surface on every run instead of waiting for a reader.
Exits non-zero when a defect (not a warning) is found, so it can gate
scripts the way compare does.

`--embeds` adds, as problems, every embed whose content the archive
does not carry: one that converted to a bare `[embed: url]` link (the
sites render the link, not the video, tweet or gist it stood for, so
the post is missing content until the embed is replaced by hand), and
one the post's body source dropped altogether while the page's editor
state still carries it (an export or feed body that lost an embed).
Neither is a conversion defect, and both are what a post looks like
until someone fixes it, so they are asked for rather than reported on
every run; a CI job that runs `lint --embeds` fails until every post
is fixed.

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
# (a gist embed with no raw/<id>/media/ files, an iframe with no
# source); markdownify may escape the bracket
MISSING_EMBED_RE = re.compile(r"\\?\[missing embed")

# the link convert leaves where an iframe stood (--embeds); the href is
# the embed's target, unescaped. A YouTube embed stays a player instead
# (convert.embed_iframe), which is content, not a bare link; so does a
# player from a provider in convert.PROVIDER_EMBEDS.
EMBED_LINK_RE = re.compile(r"\\?\[embed: [^\]]*\]\(([^)]*)\)")

# the attribution line of the blockquote an archived tweet became
# (convert.tweet_html): a quoted line ending in a dated link to the tweet
TWEET_QUOTE_RE = re.compile(
    r"^> .*\]\(https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/[^/)]+/status/\d+\)\s*$")

# a Giphy embed or a tweet's photo whose file the fetch step has not
# archived yet: the image or clip still points at the provider (--embeds)
REMOTE_EMBED_ASSET_RE = re.compile(
    r'(?:!\[[^\]]*\]\(|<video src=")(https?://[^)"]*(?:giphy\.com|pbs\.twimg\.com)/[^)"]*)')

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


def embed_problems(front: dict, body: str, raw_root: Path | None) -> list:
    """The --embeds problems for one post (see the module docstring).
    raw_root is the archive's raw/ directory, for the page's editor
    state; without it, or without a page, only the bare links are
    reported."""
    from .images import giphy_media
    from .sites import IFRAME_RE           # sites imports this module
    from .urls import carbon_id, tweet_id
    problems = []
    links, players = [], 0
    for line, fenced in prose_lines(body):
        if fenced:
            continue
        links.extend(m.group(1) for m in EMBED_LINK_RE.finditer(line))
        players += bool(IFRAME_RE.match(line) or TWEET_QUOTE_RE.match(line))
        for m in REMOTE_EMBED_ASSET_RE.finditer(line):
            problems.append(f"embed media not archived, served remotely: "
                            f"{m.group(1)[:100]} (re-run fetch; "
                            "`fetch --urls` takes this post's name)")
    for url in links:
        if tweet_id(url):
            problems.append(f"tweet not archived, embed is a bare link: "
                            f"{url[:100]} (re-run fetch for its text; a "
                            "deleted tweet stays a link)")
        else:
            problems.append(f"embed is a bare link, its content is not in "
                            f"the archive: {url[:100]} (replace it by hand)")
    page = (raw_root / (front.get("medium_id") or "") / "page.html"
            if raw_root and front.get("medium_id") else None)
    if page is None or not page.is_file():
        return problems
    from .state import state_embed_targets     # sites imports this module
    # a Giphy embed converts to an image or clip, archived or not, an
    # archived Carbon snippet to a code block, an archived tweet to a
    # quote (or, recorded deleted, to a link saying so), and an embed
    # from a provider that refuses framing to a titled link, so none is
    # among the embed links a body source could have dropped
    from .convert import provider_link
    def archived(kind, ident):
        return (page.parent / "media" / f"{kind}-{ident}.json").is_file()
    def archived_carbon(url):
        cid = carbon_id(url)
        return cid and archived("carbon", cid)
    def archived_tweet(url):
        # a quote, or the link fetch's record of a deleted tweet becomes
        tweet = tweet_id(url)
        return tweet and archived("tweet", tweet[0])
    expected = [t for t in state_embed_targets(
        page.read_text(encoding="utf-8", errors="replace"), front["medium_id"])
        if not giphy_media(t[0]) and not archived_carbon(t[0])
        and not archived_tweet(t[0]) and not provider_link(t[0])]
    # the state's targets and the body's links name one embed in different
    # forms (a canonical page vs an embed URL), so they are compared by
    # count: fewer links and players than the state has embeds means the
    # body source dropped some -- name the state's, since those are what
    # is missing
    dropped = len(expected) - len(links) - players
    if dropped > 0:
        names = ", ".join(repr(title or url[:60]) for url, title in expected)
        problems.append(
            f"body source {front.get('body_source', '?')!r} dropped "
            f"{dropped} embed(s) the page's editor state carries "
            f"(state has {len(expected)}: {names}); restore them in a fixup")
    return problems


def lint_post(post_dir: Path, seo: bool = False, embeds: bool = False,
              raw_root: Path | None = None) -> tuple[list, list]:
    """(errors, warnings) for one converted post directory; embeds adds
    the missing-embed-content problems (see embed_problems, which reads
    the page's editor state under raw_root), seo the page-analysis
    warnings (see seo_warnings)."""
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
                          "(a gist: re-run fetch for its media; an iframe "
                          "with no source: the body lost the embed, restore "
                          "it in a fixup)")
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
    # a short body is the signature of a conversion that lost the body,
    # unless the post really is that short: then the summary Medium
    # derived from it (the description) is in it, whole
    description = " ".join((front.get("description") or "").split())
    if len(body) < 200 and not (description and description in " ".join(body.split())):
        warnings.append(f"body is only {len(body)} chars")
    if embeds:
        errors.extend(embed_problems(front, body, raw_root))
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
    embeds = getattr(args, "embeds", False)
    titles = {}
    for d in dirs:
        errors, warnings = lint_post(d, seo=seo, embeds=embeds,
                                     raw_root=args.out / "raw")
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
