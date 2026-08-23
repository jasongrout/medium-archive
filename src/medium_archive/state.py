"""Recover a post from the page's embedded editor state.

Medium sometimes serves a post page as its bare application shell: no
server-rendered <article>, no JSON-LD, page title just "Medium". The
data the client would have rendered is still in the capture, in
``window.__APOLLO_STATE__`` -- the ordered paragraph list with markups,
image ids, code blocks, plus the title, publish timestamps, author and
tags -- so such a capture can be converted offline after all. Only the
images are lost to the shell: their full-resolution files were never
fetched, so the reconstructed body keeps remote miro.medium.com URLs
until the post is re-fetched.
"""

import json
import re
from datetime import datetime, timezone
from html import escape

from bs4 import BeautifulSoup

APOLLO_RE = re.compile(r"window\.__APOLLO_STATE__\s*=\s*")

IMG_BASE = "https://miro.medium.com/v2/"

# Wrap order: innermost first, so links end up outermost and a split
# forced by an overlapping markup never severs an <a>.
MARKUP_TAGS = ("CODE", "EM", "STRONG", "A")

HEADINGS = {"H2": "h2", "H3": "h3", "H4": "h4"}


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
    if not img_id:
        return ""
    img = f'<img src="{escape(IMG_BASE + img_id, quote=True)}">'
    if p.get("href"):
        img = f'<a href="{escape(p["href"], quote=True)}">{img}</a>'
    caption = _rich_text(p.get("text") or "", p.get("markups"))
    if caption.strip():
        img += f"<figcaption>{caption}</figcaption>"
    return f"<figure>{img}</figure>"


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

    for i, p in enumerate(_paragraphs(state, post)):
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
            # the title is rendered as the leading heading; it lives in
            # the front matter, so drop the repeat (same as page_body)
            if i == 0 and title and (p.get("text") or "").strip() == title.strip():
                continue
            tag = HEADINGS[ptype]
            parts.append(f"<{tag}>{rich()}</{tag}>")
        elif ptype == "IMG":
            parts.append(_figure(p))
        elif ptype == "PRE":
            parts.append(f"<pre>{escape(p.get('text') or '')}</pre>")
        elif ptype in ("BQ", "PQ"):
            parts.append(f"<blockquote>{rich()}</blockquote>")
        elif ptype == "IFRAME":
            src = ((p.get("iframe") or {}).get("mediaResource") or {}).get("href") \
                or p.get("href") or ""
            if src:
                parts.append(f'<iframe src="{escape(src, quote=True)}"></iframe>')
        else:                                   # P and anything unknown
            parts.append(f"<p>{rich()}</p>")
    close_list()
    return BeautifulSoup(f"<article>{''.join(parts)}</article>",
                         "html.parser").article
