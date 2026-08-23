"""Recovering a post from a shell page's embedded editor state."""

import json

from medium_archive.convert import convert_post, to_markdown
from medium_archive.state import (apollo_post_state, state_body,
                                  state_metadata)

MID = "abcdef123456"
URL = f"https://blog.example.com/my-post-{MID}"


def para(i, ptype, text, **kw):
    return {"__typename": "Paragraph", "id": f"v_{i}", "type": ptype,
            "text": text, "markups": [], "metadata": None, "href": None,
            "iframe": None, **kw}


def make_state(paragraphs, **post_extra):
    refs = [{"__ref": f"Paragraph:v_{i}"} for i in range(len(paragraphs))]
    state = {
        f"Post:{MID}": {
            "__typename": "Post", "id": MID,
            "title": "My Post",
            "canonicalUrl": URL,
            "firstPublishedAt": 1577621471789,      # 2019-12-29T12:11:11Z
            "latestPublishedAt": 1577621750482,
            "creator": {"__ref": "User:u1"},
            "previewContent": {"subtitle": "The subtitle."},
            "tags": [{"__ref": "Tag:jupyter"}, {"__ref": "Tag:dashboards"}],
            'content({"postMeteringOptions":null})': {
                "bodyModel": {"paragraphs": refs},
            },
            **post_extra,
        },
        "User:u1": {"name": "Ann Author", "username": "ann"},
        **{f"Paragraph:v_{i}": p for i, p in enumerate(paragraphs)},
    }
    return state


def shell_html(state):
    return ("<html><head><title>Medium</title></head><body>"
            "<script>window.__APOLLO_STATE__ = "
            + json.dumps(state) + "</script></body></html>")


def md_of_state(state):
    body = state_body(state, MID, "My Post")
    markdown, _ = to_markdown(body, URL, {}, None)
    return markdown


def test_metadata_from_state():
    info = state_metadata(make_state([]), MID)
    assert info["title"] == "My Post"
    assert info["author"] == "Ann Author"
    assert info["author_url"] == "https://medium.com/@ann"
    assert info["date"] == "2019-12-29T12:11:11Z"
    assert info["updated"] == "2019-12-29T12:15:50Z"
    assert info["description"] == "The subtitle."
    assert info["tags"] == ["jupyter", "dashboards"]


def test_leading_title_heading_is_dropped():
    md = md_of_state(make_state([para(0, "H3", "My Post"),
                                 para(1, "P", "Body text.")]))
    assert md == "Body text.\n"


def test_paragraph_types_render():
    md = md_of_state(make_state([
        para(0, "H4", "Section"),
        para(1, "P", "Prose."),
        para(2, "ULI", "one"), para(3, "ULI", "two"),
        para(4, "PRE", "pip install voila\nvoila nb.ipynb"),
        para(5, "BQ", "A quote."),
    ]))
    assert md == ("#### Section\n\nProse.\n\n- one\n- two\n\n"
                  "```\npip install voila\nvoila nb.ipynb\n```\n\n"
                  "> A quote.\n")


def test_markups_apply_on_utf16_offsets():
    # "🎉🎉 bold" -- the emoji take two UTF-16 units each, so the STRONG
    # markup for "bold" starts at unit 5, character 3
    p = para(0, "P", "🎉🎉 bold and plain")
    p["markups"] = [{"type": "STRONG", "start": 5, "end": 9}]
    md = md_of_state(make_state([p]))
    assert md == "🎉🎉 **bold** and plain\n"


def test_overlapping_markups_never_split_a_link():
    # CODE covers "voila", the A covers "voila docs": the link must stay
    # one link, and the code toggling happens inside it
    p = para(0, "P", "see voila docs now")
    p["markups"] = [
        {"type": "A", "start": 4, "end": 14, "href": "https://x.example"},
        {"type": "CODE", "start": 4, "end": 9},
    ]
    md = md_of_state(make_state([p]))
    assert md == "see [`voila` docs](https://x.example) now\n"


def test_image_paragraph_with_caption_and_link():
    p = para(0, "IMG", "A caption.",
             metadata={"id": "1*abc.png"}, href="https://demo.example")
    md = md_of_state(make_state([p]))
    assert "[![](https://miro.medium.com/v2/1*abc.png)](https://demo.example)" in md
    assert "*A caption.*" in md


def test_convert_post_recovers_shell_from_state(tmp_path):
    raw = tmp_path / MID
    raw.mkdir()
    (raw / "page.html").write_text(shell_html(make_state(
        [para(0, "H3", "My Post"), para(1, "P", "Recovered body text.")])))
    front = convert_post(URL, raw, tmp_path / "posts", prefer_page=False)
    assert front["body_source"] == "state"
    assert front["title"] == "My Post"
    assert front["date"] == "2019-12-29T12:11:11Z"
    out = tmp_path / "posts" / "2019-12-29-my-post" / "index.md"
    assert "Recovered body text." in out.read_text()


def test_shell_without_state_still_fails(tmp_path):
    raw = tmp_path / MID
    raw.mkdir()
    (raw / "page.html").write_text(
        "<html><head><title>Medium</title></head><body>"
        '<a href="https://medium.com/m/signin?operation=login">Sign in</a>'
        "</body></html>")
    import pytest
    with pytest.raises(RuntimeError, match="empty app shell"):
        convert_post(URL, raw, tmp_path / "posts", prefer_page=False)


def test_apollo_state_picks_the_blob_with_paragraphs():
    # shells carry several __APOLLO_STATE__ assignments; only one has
    # the post's content
    empty = {f"Post:{MID}": {"id": MID, "title": "My Post"}}
    full = make_state([para(0, "P", "x")])
    html = ("<script>window.__APOLLO_STATE__ = " + json.dumps(empty)
            + "</script><script>window.__APOLLO_STATE__ = "
            + json.dumps(full) + "</script>")
    state = apollo_post_state(html, MID)
    assert any(k.startswith("Paragraph:") for k in state)
