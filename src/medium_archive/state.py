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
        "author": creator.get("name") or "",
        "author_url": f"https://medium.com/@{username}" if username else None,
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


def _rich_text(text: str, markups: list) -> str:
    """Paragraph text with its markups applied, as escaped HTML."""
    markups = [mu for mu in markups or [] if mu.get("type") in MARKUP_TAGS]
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


def _figure(p) -> str:
    meta = p.get("metadata") or {}
    img_id = meta.get("id")
    caption = _rich_text(p.get("text") or "", p.get("markups"))
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


def _iframe(state, p) -> str:
    src = _iframe_src(state, p)
    caption = _rich_text(p.get("text") or "", p.get("markups"))
    inner = f'<iframe src="{escape(src, quote=True)}"></iframe>' if src else ""
    if caption.strip():
        inner += f"<figcaption>{caption}</figcaption>"
    return f"<figure>{inner}</figure>" if inner else ""


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


def state_body(state: dict, medium_id: str, title: str = ""):
    """The post body reconstructed from the state's paragraph list, as a
    soup ready for to_markdown; mirrors what Medium would have rendered."""
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
        rich = lambda: _rich_text(p.get("text") or "", p.get("markups"))
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
            parts.append(_figure(p))
        elif ptype == "PRE":
            parts.append(f"<pre>{escape(p.get('text') or '')}</pre>")
        elif ptype in ("BQ", "PQ"):
            parts.append(f"<blockquote>{rich()}</blockquote>")
        elif ptype == "IFRAME":
            parts.append(_iframe(state, p))
        elif ptype == "MIXTAPE_EMBED":
            parts.append(_mixtape(p))
        else:                                   # P and anything unknown
            parts.append(f"<p>{rich()}</p>")
    close_list()
    return BeautifulSoup(f"<article>{''.join(parts)}</article>",
                         "html.parser").article
