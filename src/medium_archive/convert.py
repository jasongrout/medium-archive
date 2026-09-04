"""The convert step: turn <out>/raw/ into Markdown posts in <out>/posts/,
plus posts.json and redirects.csv.

Never touches the network, so it can be re-run freely while tuning the
conversion.
"""

import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from html import escape
from urllib.parse import (parse_qsl, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from .dates import parse_date
from .export import export_body, parse_export
from .fetch import archive_base, read_index
from .fixup import load_fixups, read_raw
from .images import (giphy_media, image_source, same_medium_asset,
                     sniff_image_ext)
from .pages import (collapse_br_pairs, extract_metadata, feed_body,
                    ghost_body, ghost_metadata, is_ghost_page, page_body,
                    parse_ld_json, strip_title_prefix)
from .state import (apollo_post_state, gist_blocks, gist_code_blocks,
                    state_body, state_metadata, state_title)
from .readme import write_readme
from .tags import load_tag_map
from .urls import (canonical_url, carbon_id, medium_id, resolve_canonical,
                   slug_of, tweet_id)

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


# CommonMark decides from the characters on either side of a marker
# whether it can open or close an emphasis span: a `**` between a word
# character and punctuation opens nothing, and the reader is shown the
# asterisks. Medium's editor produces exactly that, wrapping a stray
# period or a closing quote in <strong>, so the fix belongs here rather
# than in any one site's renderer -- hugo's goldmark and the pelican
# site's markdown-it read the same rules, and python-markdown, which
# guessed instead, is what used to paper over it.
_UNICODE_PUNCT = ("P", "S")          # what the specification counts


def _is_punct(ch: str) -> bool:
    return bool(ch) and unicodedata.category(ch)[0] in _UNICODE_PUNCT


def _is_space(ch: str) -> bool:
    return ch == "" or ch.isspace()


def _flanks_left(before: str, first: str) -> bool:
    """Can a marker with `before` behind it and `first` after it open?"""
    if _is_space(first):
        return False
    return not _is_punct(first) or _is_space(before) or _is_punct(before)


def _flanks_right(last: str, after: str) -> bool:
    """Can a marker with `last` behind it and `after` after it close?"""
    if _is_space(last):
        return False
    return not _is_punct(last) or _is_space(after) or _is_punct(after)


# a `*text*` or `**text**` span markdownify emits, with no marker or
# backslash against it: an escaped asterisk is literal text, and a
# longer run is not a span this converter writes
EMPHASIS_RE = re.compile(r"(?<![\\*])(\*{1,2})(?![\s*])(.+?)(?<![\s\\])\1(?!\*)")
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")


def unparsed_emphasis(body: str):
    """Every emphasis span in a converted body that CommonMark will not
    read as emphasis -- the reader is shown the markers instead -- as
    (line number, the span). Fenced blocks and code spans are not
    prose and are skipped. Both the conversion and `lint` use it: one
    to write HTML where Markdown will not carry the emphasis, the other
    to fail if any is left."""
    fence = False
    for number, line in enumerate(body.split("\n"), 1):
        if re.match(r"^`{3,}", line):
            fence = not fence
            continue
        if fence or "*" not in line:
            continue
        # a marker inside a code span is content, not emphasis
        masked = _CODE_SPAN_RE.sub(lambda m: "\x00" * len(m.group(0)), line)
        for match in EMPHASIS_RE.finditer(masked):
            inner = line[match.start(2):match.end(2)]
            before = line[match.start() - 1] if match.start() else ""
            after = line[match.end()] if match.end() < len(line) else ""
            if not _flanks_left(before, inner[0]) or \
                    not _flanks_right(inner[-1], after):
                yield number, line[match.start():match.end()]


def emphasis_as_html(markdown: str) -> str:
    """Emphasis CommonMark will not read, written as the HTML tag it
    means. The alternative is moving the marker past the punctuation in
    its way, which changes which characters are emphasized; the tag
    keeps the span exactly and every renderer these sites use reads
    inline HTML."""
    def rewrite(line: str) -> str:
        for span in {s for _, s in unparsed_emphasis(line)}:
            marker = "**" if span.startswith("**") else "*"
            tag = "strong" if marker == "**" else "em"
            inner = span[len(marker):-len(marker)]
            line = line.replace(span, f"<{tag}>{inner}</{tag}>")
        return line

    fence = False
    out = []
    for line in markdown.split("\n"):
        if re.match(r"^`{3,}", line):
            fence = not fence
        out.append(line if fence else rewrite(line))
    return "\n".join(out)


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
    hugo.figure_shortcodes, pelican.figure_directives,
    myst.myst_figures)."""

    def convert_figure(self, el, text, parent_tags):
        if not _captioned_figure(el):
            return text
        return f"\n\n<figure>\n\n{text.strip()}\n\n</figure>\n\n"

    def convert_video(self, el, text, parent_tags):
        # the looping clip a Giphy mp4 embed became (see to_markdown): the
        # gif's behaviour, as one canonical HTML block the exporters and
        # lint recognize (VIDEO_RE in sites.py)
        return (f'\n\n<video src="{escape(el.get("src") or "", quote=True)}" '
                'autoplay loop muted playsinline></video>\n\n')

    def convert_iframe(self, el, text, parent_tags):
        # a player to_markdown left in place (every other iframe became
        # a link or a placeholder before conversion), as its own HTML
        # block
        return "\n\n" + embed_iframe(el.get("src") or "", el.get("title") or "",
                                     el.get("width"), el.get("height")) + "\n\n"

    def convert_figcaption(self, el, text, parent_tags):
        if not _captioned_figure(el.find_parent("figure")):
            return text
        return f"\n\n<figcaption>\n\n{text.strip()}\n\n</figcaption>\n\n"

    def convert_markdown(self, el, text, parent_tags):
        # the <markdown> element gist_blocks wraps a Markdown gist file
        # in: its text is already Markdown, so it goes out verbatim as
        # its own block, bypassing markdownify's escaping and whitespace
        # normalization (which `text` has been through)
        return f"\n\n{el.get_text().strip()}\n\n"

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
    link, inlined code or Markdown on the way out) -- so its
    <figure>/<figcaption>
    shell survives conversion. A caption alone does not: some captures
    never hydrate the figure's image element."""
    if figure is None:
        return False
    cap = figure.find("figcaption")
    return bool(cap and cap.get_text(strip=True)
                and any(t.find_parent("figcaption") is None
                        for t in figure.find_all(["img", "a", "iframe", "video",
                                                  "script", "pre", "markdown"])))


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
                 "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_PATH_RE = re.compile(r"^/(?:embed|v|shorts|live)/([^/?#]+)")
YOUTUBE_TIME_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")
YOUTUBE_EMBED_BASE = "https://www.youtube-nocookie.com/embed/"


def youtube_video(url: str):
    """(video id, start second or None) of a YouTube URL in any of the
    forms Medium's embeds and the editor state carry -- watch?v=,
    youtu.be/, /embed/, /v/, /shorts/, /live/ -- or None for any other
    URL, including a playlist with no video. The start time comes from
    `t=` (4m15s, 255, 255s) or `start=`."""
    parts = urlsplit(url)
    if parts.netloc.lower() not in YOUTUBE_HOSTS:
        return None
    q = dict(parse_qsl(parts.query))
    video = q.get("v") if parts.netloc.lower() != "youtu.be" else parts.path[1:]
    if not video:
        m = YOUTUBE_PATH_RE.match(parts.path)
        video = m.group(1) if m else None
    if not video or not YOUTUBE_ID_RE.match(video) or video == "videoseries":
        return None                       # embed/videoseries?list= is a playlist
    start = None
    m = YOUTUBE_TIME_RE.match(q.get("start") or q.get("t") or "")
    if m and m.group(0):
        h, mi, s = (int(x or 0) for x in m.groups())
        start = h * 3600 + mi * 60 + s
    return video, start or None


def youtube_embed_url(video: str, start=None) -> str:
    """The player URL for a video: the no-cookie host, so a page with an
    embed sets no YouTube cookies until the reader plays it."""
    return YOUTUBE_EMBED_BASE + video + (f"?start={start}" if start else "")


YOUTUBE_ALLOW = ('allow="accelerometer; clipboard-write; encrypted-media; '
                 'gyroscope; picture-in-picture" '
                 'referrerpolicy="strict-origin-when-cross-origin" ')


def embed_iframe(src: str, title: str = "", width=None, height=None) -> str:
    """The one iframe form convert writes for a player it keeps: the
    provider's embed URL, a title for assistive tech (the state knows
    the embed's; an export iframe does not), the size Medium showed it
    at (YouTube's 560x315 by default) as attributes and as an
    aspect-ratio the theme's CSS scales to the column, lazily loaded.
    YouTube's own embed snippet adds its allow list. One canonical
    line, so the exporters and lint recognize it (IFRAME_RE in
    sites.py)."""
    host = urlsplit(src).netloc.lower()
    if not title:
        title = "YouTube video" if host in YOUTUBE_HOSTS else f"Embedded content from {host}"
    w = int(width) if str(width or "").isdigit() and int(width) > 0 else 560
    h = int(height) if str(height or "").isdigit() and int(height) > 0 else 315
    return (f'<iframe src="{escape(src, quote=True)}" '
            f'title="{escape(title, quote=True)}" width="{w}" height="{h}" '
            f'style="aspect-ratio: {w} / {h}" loading="lazy" '
            + (YOUTUBE_ALLOW if host in YOUTUBE_HOSTS else "")
            + "allowfullscreen></iframe>")


# Providers whose embed is a player with nothing to archive -- a podcast,
# a code screenshot, a video host -- kept as an iframe on the provider's
# own embed URL, derived from the canonical page URL Medium records (or
# taken from the embed form the editor state carries, when its host is
# the provider's). Each entry maps a host to (canonical path pattern,
# embed URL template) or, for the provider's own player host, None to
# pass the URL through. Anything else stays a link.
PROVIDER_EMBEDS = {
    "carbon.now.sh": (re.compile(r"^/(?:embed/)?([A-Za-z0-9]+)"), "https://carbon.now.sh/embed/{1}"),
    "vimeo.com": (re.compile(r"^/(?:video/)?(\d+)"), "https://player.vimeo.com/video/{1}"),
    "player.vimeo.com": None,
    "codepen.io": (re.compile(r"^/([^/]+)/(?:pen|embed)/([A-Za-z0-9]+)"), "https://codepen.io/{1}/embed/{2}"),
    "open.spotify.com": (re.compile(r"^/(?:embed/)?(track|album|playlist|episode|show)/([A-Za-z0-9]+)"),
                         "https://open.spotify.com/embed/{1}/{2}"),
    "soundcloud.com": (re.compile(r"^/[^/]+/[^/?#]+"), "https://w.soundcloud.com/player/?url={url}"),
    "w.soundcloud.com": None,
}


# Providers whose pages refuse to be framed (a frame-ancestors policy:
# the browser shows an error where the player would be), so the embed
# is best a plain link, titled by the editor state (an episode's name),
# which lint counts as content rather than an unfilled embed.
PROVIDER_LINKS = {"art19.com"}


def provider_link(src: str) -> bool:
    """Whether src's provider is one whose embed becomes a titled link."""
    return urlsplit(src).netloc.lower().removeprefix("www.") in PROVIDER_LINKS


def provider_embed(src: str, embed: str = "") -> str | None:
    """The provider embed URL to keep an iframe on, for src (the embed's
    canonical URL) with embed (the provider's embed form, when known),
    or None when the provider is not one whose player is kept."""
    for candidate in (embed, src):
        if not candidate:
            continue
        parts = urlsplit(candidate)
        host = parts.netloc.lower().removeprefix("www.")
        if host not in PROVIDER_EMBEDS:
            continue
        rule = PROVIDER_EMBEDS[host]
        if rule is None or candidate is embed:
            # the provider's own embed form, as it came (an empty query
            # dropped: Carbon's ends in a bare "?")
            return candidate.rstrip("?")
        pattern, template = rule
        m = pattern.match(parts.path)
        if not m:
            continue
        return template.format(*(("",) + m.groups()), path=m.group(0),
                               url=f"https://{host}{parts.path}")
    return None


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


# The link an RSS feed body puts inside the empty iframe it renders a
# gist embed as: it names the embed's media resource, the id fetch
# archives the media payload and the gist's files under (raw/media/).
# HTML parsers keep an iframe's content as text, so this is searched
# for in the text rather than matched against an <a>.
MEDIA_HREF_RE = re.compile(r"https?://medium\.com/media/([0-9a-f]+)/href")


REF_SRC_RE = re.compile(r"[?&]ref_src=[^&#]*")


PIC_LINK_RE = re.compile(r"^pic\.(?:twitter|x)\.com/")


def tweet_pictures(media: dict, url: str) -> str:
    """The tweet's photos as <img> tags, and a video's or animated
    gif's poster frame linked to the tweet, from its syndication
    payload (fetch_tweets); "" without one. The URLs are the ones fetch
    archived with the post's images, so to_markdown localizes them."""
    parts = []
    for m in (media or {}).get("mediaDetails") or []:
        src = m.get("media_url_https")
        if not src:
            continue
        if m.get("type") == "photo":
            parts.append(f'<img src="{escape(src, quote=True)}" alt="">')
        else:
            parts.append(f'<a href="{escape(url, quote=True)}">'
                         f'<img src="{escape(src, quote=True)}" alt="Video"></a>')
    return "".join(f"<p>{p}</p>" for p in parts)


def tweet_html(payload: dict, url: str, media: dict | None = None) -> str:
    """An archived tweet (its oEmbed payload) as the blockquote convert
    writes: the tweet's text with its links, its pictures when their
    syndication payload is archived (the pic.twitter.com link they
    stood behind goes), then an attribution line naming the author and
    dating the tweet, both linked. Plain Markdown once converted, so
    every generator renders it, and it outlives the tweet."""
    soup = BeautifulSoup(payload.get("html") or "", "html.parser")
    quote = soup.find("blockquote")
    text = quote.find("p") if quote else None
    date = ""
    for a in (quote.find_all("a") if quote else []):
        if tweet_id(a.get("href") or ""):
            date = a.get_text(strip=True)
    pictures = tweet_pictures(media, payload.get("url") or url)
    for a in (text.find_all("a") if text else []):
        if pictures and PIC_LINK_RE.match(a.get_text(strip=True)):
            prev = a.previous_sibling
            a.decompose()
            if isinstance(prev, str) and not prev.strip():
                prev.extract()
            continue
        a["href"] = REF_SRC_RE.sub("", a.get("href") or "")
    author = payload.get("author_name") or ""
    author_url = payload.get("author_url") or ""
    handle = author_url.rstrip("/").rsplit("/", 1)[-1] if author_url else ""
    who = f"{author} (@{handle})" if author and handle else author or handle
    link = payload.get("url") or url
    by = f'<a href="{escape(author_url, quote=True)}">{escape(who)}</a>' \
        if author_url else escape(who)
    when = f'<a href="{escape(link, quote=True)}">{escape(date or "tweet")}</a>'
    body = "".join(str(c) for c in text.contents).strip() if text else ""
    return ("<blockquote>" + (f"<p>{body}</p>" if body else "") + pictures
            + f"<p>\u2014 {by}, {when}</p></blockquote>")


def _archived_tweet(media: dict, url: str) -> str | None:
    """The blockquote for url's tweet when its oEmbed payload is archived
    (raw/media/tweet-<id>.json), else None."""
    tweet = tweet_id(url)
    entry = media.get(f"tweet:{tweet[0]}") if tweet else None
    if not entry or not entry.get("tweet"):
        return None
    if entry["tweet"].get("deleted"):
        # recorded by fetch when X answered 404: a link that says so,
        # rather than an embed lint keeps asking about
        who = f"@{tweet[1]}" if tweet[1] else "X"
        return (f'<p><a href="{escape(url, quote=True)}">A tweet by {who}, '
                "no longer available</a></p>")
    return tweet_html(entry["tweet"], url, entry.get("media"))


# Carbon names a snippet's language by its CodeMirror mode, often a MIME
# type; the fence needs the name highlighters know. Modes not listed
# fall back to the last path segment less its x- prefix (text/x-java ->
# java, text/x-rustsrc -> rustsrc is wrong, hence the table).
CARBON_LANGS = {
    "text/typescript-jsx": "tsx", "text/typescript": "typescript",
    "application/typescript": "typescript", "jsx": "jsx", "javascript": "javascript",
    "htmlmixed": "html", "text/html": "html", "text/x-csrc": "c",
    "text/x-c++src": "cpp", "text/x-csharp": "csharp", "text/x-java": "java",
    "text/x-kotlin": "kotlin", "text/x-scala": "scala", "text/x-swift": "swift",
    "text/x-rustsrc": "rust", "text/x-go": "go", "text/x-sh": "bash",
    "shell": "bash", "text/x-python": "python", "text/x-ruby": "ruby",
    "text/x-yaml": "yaml", "application/json": "json", "text/x-toml": "toml",
    "text/x-sql": "sql", "text/x-markdown": "markdown", "text/x-diff": "diff",
    "application/x-httpd-php": "php", "text/x-objectivec": "objectivec",
    "text/x-lua": "lua", "text/x-rsrc": "r", "text/x-julia": "julia",
    "text/x-dockerfile": "dockerfile", "text/x-nginx-conf": "nginx",
    "text/css": "css", "text/x-scss": "scss", "text/x-less": "less",
    "graphql": "graphql", "text/x-vue": "vue", "text/x-elixir": "elixir",
    "text/x-haskell": "haskell", "text/x-clojure": "clojure",
    "text/x-erlang": "erlang", "text/x-fsharp": "fsharp", "text/x-ocaml": "ocaml",
    "text/x-perl": "perl", "text/x-powershell": "powershell",
    "text/x-vb": "vbnet", "text/x-verilog": "verilog", "text/x-latex": "latex",
    "application/xml": "xml", "text/x-nim": "nim", "text/x-dart": "dart",
    "text/x-django": "django", "text/x-twig": "twig", "text/x-solidity": "solidity",
    "text/x-gfm": "markdown", "text/x-crystal": "crystal", "text/x-d": "d",
    "text/x-pascal": "pascal", "text/x-groovy": "groovy",
}


def carbon_language(mode: str) -> str:
    """The fence language for a Carbon snippet's language mode; "" for
    Carbon's "auto" (it guessed; nothing recorded) and plain text."""
    mode = (mode or "").strip().lower()
    if mode in ("", "auto", "text", "plaintext", "text/plain"):
        return ""
    if mode in CARBON_LANGS:
        return CARBON_LANGS[mode]
    return mode.rsplit("/", 1)[-1].removeprefix("x-")


def _archived_carbon(media: dict, url: str) -> str | None:
    """The code block for url's Carbon snippet when it is archived
    (raw/media/carbon-<id>.json), else None."""
    cid = carbon_id(url)
    entry = media.get(f"carbon:{cid}") if cid else None
    snippet = (entry or {}).get("carbon")
    if not snippet or snippet.get("code") is None:
        return None
    return gist_code_blocks({"snippet": {
        "language": carbon_language(snippet.get("language")),
        "content": snippet["code"]}})


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
    by_basename = {Path(urlsplit(u).path).name: f for u, f in img_map.items()
                   if same_medium_asset(u)}

    # A Giphy embed names a media file the archive fetches like any
    # image (fetch.embed_asset_urls), so the iframe becomes the file
    # itself: an <img> for a gif or webp, localized with the images
    # below, a <video> for an mp4 (the clip loops like the gif it stands
    # for). Giphy's titles are its page titles ("... GIF by X - Find &
    # Share on GIPHY"); the descriptive part becomes the alt text.
    # Export and Ghost bodies embed a tweet as Twitter's widget markup: a
    # <blockquote class="twitter-tweet"> holding only a link to the
    # tweet, for widgets.js to fill in. Nothing to keep but the target,
    # so it takes the iframe path below (a quote that already carries
    # the tweet's text, as a Ghost capture can, is left as it is).
    for quote in body.find_all("blockquote", class_="twitter-tweet"):
        link = next((a.get("href") for a in quote.find_all("a")
                     if tweet_id(a.get("href") or "")), None)
        if link and not quote.get_text(strip=True):
            quote.replace_with(doc.new_tag("iframe", src=link))

    # An archived tweet becomes its quote here, ahead of the image pass,
    # so the photos the quote carries are localized with the post's images.
    for iframe in body.find_all("iframe"):
        tweet = _archived_tweet(media or {}, iframe.get("src") or "")
        if tweet:
            iframe.replace_with(BeautifulSoup(tweet, "html.parser"))

    for iframe in body.find_all("iframe"):
        asset = giphy_media(iframe.get("src") or iframe.get("data-src") or "")
        if not asset:
            continue
        title = re.sub(r"\s*-\s*Find & Share on GIPHY$", "",
                       iframe.get("title") or "").strip()
        if asset.endswith(".mp4"):
            iframe.replace_with(doc.new_tag("video", src=asset))
        else:
            iframe.replace_with(doc.new_tag("img", src=asset, alt=title))

    def localize(src: str, copy: bool):
        """(local images/ path, used) for an asset URL the fetch step
        mapped, else (src, False)."""
        fname = img_map.get(src) or by_basename.get(Path(urlsplit(src).path).name)
        if not (fname and (out_dir is None or (raw / "images" / fname).exists())):
            return src, False
        src_file = raw / "images" / fname
        # an image fetched from an extensionless URL was stored as
        # .bin; the derived copy gets the extension its bytes call for
        if fname.endswith(".bin") and src_file.exists():
            fname = fname[:-len(".bin")] + (sniff_image_ext(src_file) or ".bin")
        if out_dir is not None and copy:
            (out_dir / "images").mkdir(exist_ok=True)
            shutil.copy2(src_file, out_dir / "images" / fname)
        return f"images/{fname}", True

    used_images = []
    for video in body.find_all("video"):
        local, used = localize(video.get("src") or "", copy=True)
        if used:
            used_images.append(local)
        video.attrs = {"src": local}

    for img in body.find_all("img"):
        src = image_source(img)
        if not src:
            img.decompose()
            continue
        local, used = localize(src, copy=True)   # not downloaded: remote URL stays
        if used:
            used_images.append(local)
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
            script.replace_with(BeautifulSoup(gist_blocks(files), "html.parser"))
        else:
            url = m.string[:m.end(1)]           # the gist's page URL
            script.replace_with(doc.new_tag("a", href=url,
                                            string=f"embed: {url}"))

    # A feed body renders a gist embed as an iframe with no source whose
    # only content is a link to medium.com/media/<id>/href, the media
    # resource the state names too. That id is where fetch archives the
    # gist's files, so the embed inlines them like the state and script
    # forms do; an archived payload that names a target instead (a
    # non-gist embed) gives the iframe its source for the loop below.
    for iframe in body.find_all("iframe"):
        if iframe.get("src") or iframe.get("data-src"):
            continue
        m = MEDIA_HREF_RE.search(iframe.get_text())
        entry = (media or {}).get(m.group(1)) if m else None
        if not entry:
            continue
        files = (entry.get("gist") or {}).get("files") or {}
        value = entry.get("value") or {}
        if files:
            iframe.replace_with(BeautifulSoup(gist_blocks(files), "html.parser"))
        elif value.get("iframeSrc") or value.get("href"):
            iframe["src"] = value.get("iframeSrc") or value.get("href")
            iframe.clear()

    # A YouTube iframe stays an iframe: the archive has its URL, and the
    # player is the content, so it is written as one (_Converter renders
    # it; the exporters render or rewrite that one form), as is a
    # player from a provider in PROVIDER_EMBEDS. Any other
    # iframe becomes a link to its target. An iframe with no source is
    # an embed whose content the body never carried (a feed body renders
    # a gist that way: src="", 0x0). It gets the same visible placeholder
    # the state conversion uses, which lint flags -- a link with no
    # target would read as a dangling "embed:".
    for iframe in body.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        video = youtube_video(src) if src else None
        code = _archived_carbon(media or {}, src) if src else None
        player = provider_embed(src, iframe.get("data-embed") or "") if src else None
        if code:                         # the snippet itself beats its screenshot
            iframe.replace_with(BeautifulSoup(code, "html.parser"))
        elif src and provider_link(src):
            iframe.replace_with(doc.new_tag("a", href=src,
                                            string=iframe.get("title") or src))
        elif video:                        # always the 16:9 default size
            iframe.attrs = {"src": youtube_embed_url(*video),
                            "title": iframe.get("title") or ""}
        elif player:
            iframe.attrs = {"src": player, "title": iframe.get("title") or "",
                            "width": iframe.get("width"), "height": iframe.get("height")}
        elif src:
            iframe.replace_with(doc.new_tag("a", href=src, string=f"embed: {src}"))
        else:
            iframe.replace_with(doc.new_tag("p", string="[missing embed]"))

    # Medium's editor emits things like <strong> </strong> between runs,
    # and <strong>.</strong> or <em>,</em> where a run ends on its
    # punctuation. markdownify drops the whitespace-only ones, losing
    # the space; the punctuation-only ones it keeps, and they are how a
    # reader ends up looking at `task**.**`, since CommonMark will not
    # open a marker between a word character and punctuation. Emphasis
    # on nothing but punctuation is emphasis on nothing, so both go.
    for el in body.find_all(["strong", "em", "b", "i"]):
        if el.parent is not None and not re.search(r"\w", el.get_text()):
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
    # what is left of the emphasis Medium wrote against punctuation:
    # spans whose markers CommonMark will not read, written as the tag
    # they mean (see emphasis_as_html)
    markdown = emphasis_as_html(markdown)
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
        if p.name.startswith("tweet-"):       # a tweet's oEmbed payload, and
            # the syndication payload naming its photos (fetch_tweets)
            tid, kind = p.name[len("tweet-"):-len(".json")], "tweet"
            if tid.endswith(".media"):
                tid, kind = tid[:-len(".media")], "media"
            media.setdefault(f"tweet:{tid}", {})[kind] = json.loads(read_raw(p, fixups))
            continue
        if p.name.startswith("carbon-"):      # a Carbon snippet
            media[f"carbon:{p.stem[len('carbon-'):]}"] = {
                "carbon": json.loads(read_raw(p, fixups))}
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
