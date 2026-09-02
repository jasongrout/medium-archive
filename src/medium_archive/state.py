"""Convert a post from the page's embedded editor state.

Every Medium page carries its post twice: once server-rendered into the
visible HTML, and once as data in ``window.__APOLLO_STATE__`` -- the
ordered paragraph list with types and markup spans, image ids, code
blocks, plus the title, publish timestamps, author and tags. The state
is the cleaner body source: it has no page chrome to strip, it keeps
what the renderer destroys (the full text span of a link containing a
code fragment, bold on code, iframe embeds the un-hydrated page drops),
and it survives even when Medium serves the bare application shell (no
<article>, no JSON-LD, page title just "Medium") -- which is also how
shell-only captures are recovered offline.
"""

import json
import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

APOLLO_RE = re.compile(r"window\.__APOLLO_STATE__\s*=\s*")

IMG_BASE = "https://miro.medium.com/v2/"

# Wrap order: innermost first, so links end up outermost and a split
# forced by an overlapping markup never severs an <a>.
MARKUP_TAGS = ("CODE", "EM", "STRONG", "A")

# The renderer promotes the editor's section/sub-section headings one
# level (the h1 is the title); match it so both body sources agree.
HEADINGS = {"H2": "h2", "H3": "h2", "H4": "h3"}


def apollo_post_state(text: str, medium_id: str) -> dict | None:
    """The Apollo state blob holding the post's paragraphs, if any.
    A shell page carries several __APOLLO_STATE__ assignments; only one
    has the post's content."""
    dec = json.JSONDecoder()
    best = None
    for m in APOLLO_RE.finditer(text):
        try:
            state, _ = dec.raw_decode(text, m.end())
        except ValueError:
            continue
        if (isinstance(state, dict) and f"Post:{medium_id}" in state
                and any(k.startswith("Paragraph:") for k in state)):
            best = state
    return best


def _deref(state, v):
    return state.get(v["__ref"], {}) if isinstance(v, dict) and "__ref" in v else v


def _paragraphs(state, post) -> list:
    for k, v in post.items():
        if k.startswith("content") and isinstance(v, dict):
            body = v.get("bodyModel") or {}
            return [_deref(state, p) for p in body.get("paragraphs") or []]
    return []


def state_image_urls(text: str, medium_id: str) -> list:
    """Image URLs referenced by the embedded editor state's paragraphs,
    in order of appearance. On a shell capture the rendered body has no
    <img> tags, so this is the only image source the page offers."""
    state = apollo_post_state(text, medium_id)
    if not state:
        return []
    post = state.get(f"Post:{medium_id}") or {}
    urls = []
    for p in _paragraphs(state, post):
        img_id = (p.get("metadata") or {}).get("id")
        if p.get("type") == "IMG" and img_id:
            url = IMG_BASE + img_id
            if url not in urls:
                urls.append(url)
    return urls


def state_media_resources(text: str, medium_id: str) -> dict:
    """Media resources of IFRAME paragraphs whose iframeSrc is empty --
    the embeds the state itself cannot resolve (gists, mostly; every
    other embed type goes through embedly and names its target in
    iframeSrc). Keyed by resource id, valued with the resource title
    (for a gist, its filename). fetch archives these ids via
    medium.com/media/<id>; without that, the embed's content exists
    nowhere in the page."""
    if not re.search(r'"iframeSrc"\s*:\s*""', text):
        return {}
    state = apollo_post_state(text, medium_id)
    if not state:
        return {}
    post = state.get(f"Post:{medium_id}") or {}
    out = {}
    for p in _paragraphs(state, post):
        if p.get("type") != "IFRAME":
            continue
        media = _deref(state, (p.get("iframe") or {}).get("mediaResource") or {})
        if media.get("id") and not media.get("iframeSrc"):
            out.setdefault(media["id"], media.get("title") or "")
    return out


def state_metadata(state: dict, medium_id: str) -> dict:
    """Front-matter fields from the state; same shape as extract_metadata."""
    post = state[f"Post:{medium_id}"]
    creator = _deref(state, post.get("creator") or {})
    first = post.get("firstPublishedAt") or 0
    latest = post.get("latestPublishedAt") or 0

    def iso(ms):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")

    preview = post.get("previewContent") or {}
    username = creator.get("username")
    return {
        "url": post.get("canonicalUrl") or post.get("mediumUrl") or "",
        "title": post.get("title") or "",
        "authors": [{"name": creator["name"],
                     "url": f"https://medium.com/@{username}" if username else None}]
        if creator.get("name") else [],
        "date": iso(first) if first else "",
        "updated": iso(latest) if latest > first else None,
        "description": preview.get("subtitle") or "",
        "tags": [t["__ref"][len("Tag:"):] for t in post.get("tags") or []
                 if isinstance(t, dict) and t.get("__ref", "").startswith("Tag:")],
    }


def _unit_to_char(text: str):
    """Medium markup offsets count UTF-16 code units; map them to
    Python character offsets (astral chars take two units)."""
    m = []
    for i, ch in enumerate(text):
        m.extend([i, i] if ord(ch) > 0xFFFF else [i])
    m.append(len(text))
    return lambda off: m[min(max(off, 0), len(m) - 1)]


def _markup_href(state, mu) -> str | None:
    """An A markup's link target. A user-mention markup carries no href,
    only the userId; the state's User entry names the profile."""
    if mu.get("href"):
        return mu["href"]
    user = (state or {}).get(f"User:{mu.get('userId')}") or {}
    username = user.get("username")
    return f"https://medium.com/@{username}" if username else None


def _rich_text(text: str, markups: list, state: dict | None = None) -> str:
    """Paragraph text with its markups applied, as escaped HTML."""
    markups = [mu for mu in markups or [] if mu.get("type") in MARKUP_TAGS]
    resolved = []
    for mu in markups:
        if mu["type"] == "A":
            href = _markup_href(state, mu)
            if href is None:        # unresolvable mention: keep plain text
                continue
            mu = {**mu, "href": href}
        resolved.append(mu)
    markups = resolved
    if not markups:
        return escape(text)
    to_char = _unit_to_char(text)
    spans = [(MARKUP_TAGS.index(mu["type"]), to_char(mu["start"]),
              to_char(mu["end"]), mu) for mu in markups]
    bounds = sorted({0, len(text), *(s for _, s, _, _ in spans),
                     *(e for _, _, e, _ in spans)})
    out = []
    for a, b in zip(bounds, bounds[1:]):
        seg = escape(text[a:b])
        for prio, s, e, mu in sorted(spans):    # low priority wraps first
            if s <= a and b <= e:
                if mu["type"] == "A":
                    seg = f'<a href="{escape(mu.get("href") or "", quote=True)}">{seg}</a>'
                else:
                    tag = mu["type"].lower()
                    seg = f"<{tag}>{seg}</{tag}>"
        out.append(seg)
    text_html = "".join(out)
    # a boundary forced by an overlapping markup reopens the same tag;
    # merge so markdownify never sees **bold****bold** or a severed link
    for tag in ("code", "em", "strong"):
        text_html = text_html.replace(f"</{tag}><{tag}>", "")
    for _, _, _, mu in spans:
        if mu["type"] == "A":
            href = escape(mu.get("href") or "", quote=True)
            text_html = text_html.replace(f'</a><a href="{href}">', "")
    return text_html


def _figure(state, p) -> str:
    meta = p.get("metadata") or {}
    img_id = meta.get("id")
    caption = _rich_text(p.get("text") or "", p.get("markups"), state)
    inner = ""
    if img_id:
        alt = f' alt="{escape(meta["alt"], quote=True)}"' if meta.get("alt") else ""
        inner = f'<img src="{escape(IMG_BASE + img_id, quote=True)}"{alt}>'
        if p.get("href"):
            inner = f'<a href="{escape(p["href"], quote=True)}">{inner}</a>'
    if caption.strip():
        inner += f"<figcaption>{caption}</figcaption>"
    return f"<figure>{inner}</figure>" if inner else ""


def _iframe_src(state, p) -> str:
    """The embed's own URL. The state stores an embedly wrapper URL whose
    query carries the real target (url= the canonical page, src= the
    embed form); prefer the canonical page."""
    media = _deref(state, (p.get("iframe") or {}).get("mediaResource") or {})
    src = media.get("iframeSrc") or p.get("href") or ""
    if "embedly.com" in src:
        q = parse_qs(urlsplit(src).query)
        src = (q.get("url") or q.get("src") or [src])[0]
    return src


def _iframe(state, p, media: dict | None = None) -> str:
    src = _iframe_src(state, p)
    caption = _rich_text(p.get("text") or "", p.get("markups"), state)
    if not src:
        res = _deref(state, (p.get("iframe") or {}).get("mediaResource") or {})
        return _media_embed(res, media or {}, caption)
    inner = f'<iframe src="{escape(src, quote=True)}"></iframe>'
    if caption.strip():
        inner += f"<figcaption>{caption}</figcaption>"
    return f"<figure>{inner}</figure>"


def gist_code_blocks(files: dict) -> str:
    """A gist's files (the GitHub API's `files` mapping) as <pre><code>
    blocks ready for to_markdown, each fence carrying the file's
    language."""
    blocks = []
    for f in files.values():
        lang = (f.get("language") or "").lower()
        cls = f' class="language-{escape(lang, quote=True)}"' if lang else ""
        blocks.append(f"<pre><code{cls}>{escape(f.get('content') or '')}"
                      "</code></pre>")
    return "".join(blocks)


def _media_embed(res: dict, media: dict, caption: str) -> str:
    """An embed whose state names no target (iframeSrc empty -- a gist,
    usually). With its media resource archived (fetch saves raw/media/),
    inline the gist's files as code blocks, or fall back to whatever URL
    the media payload names; otherwise emit a visible
    [missing embed: ...] placeholder that lint flags -- the one thing
    this must never do is drop the embed silently."""
    entry = media.get(res.get("id") or "") or {}
    files = (entry.get("gist") or {}).get("files") or {}
    if files:
        inner = gist_code_blocks(files)
        if caption.strip():
            inner += f"<figcaption>{caption}</figcaption>"
        return f"<figure>{inner}</figure>"
    value = entry.get("value") or {}
    src = value.get("iframeSrc") or value.get("href") or ""
    if src:
        inner = f'<iframe src="{escape(src, quote=True)}"></iframe>'
        if caption.strip():
            inner += f"<figcaption>{caption}</figcaption>"
        return f"<figure>{inner}</figure>"
    title = res.get("title") or ""
    out = f"<p>{escape(f'[missing embed: {title}]' if title else '[missing embed]')}</p>"
    if caption.strip():
        out += f"<figure><figcaption>{caption}</figcaption></figure>"
    return out


def _mixtape(p) -> str:
    """A link-preview card: render as a plain link with the card's
    title line as its text."""
    href = (p.get("mixtapeMetadata") or {}).get("href") or ""
    title = (p.get("text") or "").split("\n")[0].strip()
    if not href:
        return f"<p>{escape(title)}</p>" if title else ""
    return (f'<p><a href="{escape(href, quote=True)}">'
            f"{escape(title or href)}</a></p>")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip().lower()


def _lead_skips(paragraphs: list, post: dict, title: str) -> set:
    """Indices of the leading title/subtitle headings. The title is
    rendered as the leading heading (sometimes after a hero image) and
    the subtitle as the heading right after it; both live in the front
    matter, so the repeats are dropped (page_body does the same via
    <h1> and .pw-subtitle-paragraph). The stored subtitle may be
    truncated with a trailing ellipsis."""
    titles = {_norm(title), _norm(post.get("title") or "")} - {""}
    skips = set()
    i = 0
    while i < len(paragraphs) and paragraphs[i].get("type") in ("IMG", "IFRAME"):
        i += 1                       # hero images may precede the title
    if i < len(paragraphs) and paragraphs[i].get("type") in HEADINGS \
            and _norm(paragraphs[i].get("text") or "") in titles:
        skips.add(i)
        sub = _norm(((post.get("extendedPreviewContent") or {}).get("subtitle")
                     or (post.get("previewContent") or {}).get("subtitle")
                     or "").rstrip("…"))
        j = i + 1
        if sub and j < len(paragraphs) and paragraphs[j].get("type") in HEADINGS:
            head = _norm(paragraphs[j].get("text") or "")
            if head and (head.startswith(sub) or sub.startswith(head)):
                skips.add(j)
    return skips


def _section_breaks(post: dict) -> set:
    """Paragraph indices where a new section starts; the renderer puts a
    divider there (page_body turns those into <hr> too)."""
    for k, v in post.items():
        if k.startswith("content") and isinstance(v, dict):
            return {s["startIndex"]
                    for s in (v.get("bodyModel") or {}).get("sections") or []
                    if s.get("startIndex")}
    return set()


def _code_lang(p) -> str:
    """The code block's language, when Medium highlighted it: AUTO is
    Medium's own detection, EXPLICIT the author's choice, DISABLED means
    highlighting was turned off (render a bare fence)."""
    meta = p.get("codeBlockMetadata") or {}
    if meta.get("mode") == "DISABLED":
        return ""
    return (meta.get("lang") or "").lower()


def state_body(state: dict, medium_id: str, title: str = "",
               media: dict | None = None):
    """The post body reconstructed from the state's paragraph list, as a
    soup ready for to_markdown; mirrors what Medium would have rendered.
    `media` maps media resource ids to their archived payloads
    (convert.load_media), for embeds the state leaves unresolved."""
    post = state[f"Post:{medium_id}"]
    parts, list_tag = [], None

    def close_list():
        nonlocal list_tag
        if list_tag:
            parts.append(f"</{list_tag}>")
            list_tag = None

    paragraphs = _paragraphs(state, post)
    skips = _lead_skips(paragraphs, post, title)
    breaks = _section_breaks(post)
    for i, p in enumerate(paragraphs):
        if i in skips:
            continue
        if i in breaks:
            close_list()
            parts.append("<hr>")
        ptype = p.get("type") or "P"
        rich = lambda: _rich_text(p.get("text") or "", p.get("markups"), state)
        if ptype in ("ULI", "OLI"):
            tag = "ul" if ptype == "ULI" else "ol"
            if list_tag != tag:
                close_list()
                parts.append(f"<{tag}>")
                list_tag = tag
            parts.append(f"<li>{rich()}</li>")
            continue
        close_list()
        if ptype in HEADINGS:
            parts.append(f"<{HEADINGS[ptype]}>{rich()}</{HEADINGS[ptype]}>")
        elif ptype == "IMG":
            parts.append(_figure(state, p))
        elif ptype == "PRE":
            lang = _code_lang(p)
            code = escape(p.get("text") or "")
            parts.append(
                f'<pre><code class="language-{escape(lang, quote=True)}">'
                f"{code}</code></pre>" if lang else f"<pre>{code}</pre>")
        elif ptype in ("BQ", "PQ"):
            parts.append(f"<blockquote>{rich()}</blockquote>")
        elif ptype == "IFRAME":
            parts.append(_iframe(state, p, media))
        elif ptype == "MIXTAPE_EMBED":
            parts.append(_mixtape(p))
        else:                                   # P and anything unknown
            parts.append(f"<p>{rich()}</p>")
    close_list()
    return BeautifulSoup(f"<article>{''.join(parts)}</article>",
                         "html.parser").article
