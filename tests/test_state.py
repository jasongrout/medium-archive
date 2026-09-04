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
            "tags": [{"__ref": "Tag:travel"}, {"__ref": "Tag:recipes"}],
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
    assert info["authors"] == [{"name": "Ann Author",
                                "url": "https://medium.com/@ann"}]
    assert info["date"] == "2019-12-29T12:11:11Z"
    assert info["updated"] == "2019-12-29T12:15:50Z"
    assert info["description"] == "The subtitle."
    assert info["tags"] == ["travel", "recipes"]


def test_leading_title_heading_is_dropped():
    md = md_of_state(make_state([para(0, "H3", "My Post"),
                                 para(1, "P", "Body text.")]))
    assert md == "Body text.\n"


def test_truncated_title_is_completed_from_the_opening_heading(tmp_path):
    # Medium titles a post whose author set none with its opening
    # heading, cut to about a hundred characters with an ellipsis; the
    # heading keeps the full text. The title is the full text, and the
    # heading is still the title's repeat, dropped from the body.
    full = ("Exploring Petabytes of the Night Sky: Notebooks at the "
            "Astro Data Lab Science Platform")
    cut = ("Exploring Petabytes of the Night Sky: Notebooks at the "
           "Astro Data Lab Science\u2026")
    state = make_state([para(0, "H3", full), para(1, "P", "Body text.")],
                       title=cut)
    assert state_metadata(state, MID)["title"] == full
    body = state_body(state, MID, cut)
    markdown, _ = to_markdown(body, URL, {}, None)
    assert markdown == "Body text.\n"

    raw = tmp_path / MID
    raw.mkdir()
    (raw / "page.html").write_text(shell_html(state))
    front = convert_post(URL, raw, tmp_path / "posts", prefer_page=False)
    assert front["title"] == full
    out = tmp_path / "posts" / "2019-12-29-my-post" / "index.md"
    assert full not in out.read_text().split("\n}\n", 1)[1]


def test_unrelated_heading_does_not_complete_a_truncated_title():
    state = make_state([para(0, "H3", "Some other heading"),
                        para(1, "P", "Body text.")],
                       title="A title cut short\u2026")
    assert state_metadata(state, MID)["title"] == "A title cut short\u2026"
    body = state_body(state, MID, "A title cut short\u2026")
    markdown, _ = to_markdown(body, URL, {}, None)
    assert markdown == "## Some other heading\n\nBody text.\n"


def test_paragraph_types_render():
    md = md_of_state(make_state([
        para(0, "H4", "Section"),
        para(1, "P", "Prose."),
        para(2, "ULI", "one"), para(3, "ULI", "two"),
        para(4, "PRE", "pip install mytool\nmytool run"),
        para(5, "BQ", "A quote."),
    ]))
    # H4 renders one level up (###), matching the rendered page, where
    # the h1 is the title
    assert md == ("### Section\n\nProse.\n\n- one\n- two\n\n"
                  "```\npip install mytool\nmytool run\n```\n\n"
                  "> A quote.\n")


def test_soft_line_break_survives_as_a_hard_break():
    # the editor stores a shift-enter break as a newline inside the
    # paragraph's text; as HTML whitespace it would join the two lines
    md = md_of_state(make_state([
        para(0, "P", "First line.\nSecond line."),
        para(1, "ULI", "item one\nstill item one"),
        para(2, "BQ", "Quoted.\nStill quoted."),
    ]))
    assert md == ("First line.  \nSecond line.\n\n"
                  "- item one  \n  still item one\n\n"
                  "> Quoted.  \n> Still quoted.\n")


def test_soft_break_takes_the_spaces_around_it():
    # a line that ends in a space would otherwise carry it into the
    # break's own two spaces, and one that starts with spaces would
    # arrive indented
    md = md_of_state(make_state([para(0, "P", "Time  \n   Session")]))
    assert md == "Time  \nSession\n"


def test_soft_break_inside_a_markup_span():
    # the markup offsets are the text's own, so a span covering the
    # break still wraps both lines
    p = para(0, "P", "bold one\nbold two")
    p["markups"] = [{"type": "STRONG", "start": 0, "end": 17}]
    md = md_of_state(make_state([p]))
    assert md == "**bold one  \nbold two**\n"


def test_markups_apply_on_utf16_offsets():
    # "🎉🎉 bold" -- the emoji take two UTF-16 units each, so the STRONG
    # markup for "bold" starts at unit 5, character 3
    p = para(0, "P", "🎉🎉 bold and plain")
    p["markups"] = [{"type": "STRONG", "start": 5, "end": 9}]
    md = md_of_state(make_state([p]))
    assert md == "🎉🎉 **bold** and plain\n"


def test_overlapping_markups_never_split_a_link():
    # CODE covers "widget", the A covers "widget docs": the link must
    # stay one link, and the code toggling happens inside it
    p = para(0, "P", "see widget docs now")
    p["markups"] = [
        {"type": "A", "start": 4, "end": 15, "href": "https://x.example"},
        {"type": "CODE", "start": 4, "end": 10},
    ]
    md = md_of_state(make_state([p]))
    assert md == "see [`widget` docs](https://x.example) now\n"


def test_title_after_hero_image_is_dropped():
    md = md_of_state(make_state([
        para(0, "IMG", "", metadata={"id": "1*hero.png"}),
        para(1, "H3", "My Post"),
        para(2, "P", "Body text.")]))
    assert md == "![](https://miro.medium.com/v2/1*hero.png)\n\nBody text.\n"


def test_subtitle_heading_after_title_is_dropped():
    md = md_of_state(make_state([
        para(0, "H3", "My Post"),
        para(1, "H4", "The subtitle."),
        para(2, "P", "Body text.")]))
    assert md == "Body text.\n"


def test_section_boundaries_become_dividers():
    state = make_state([para(0, "P", "One."), para(1, "P", "Two.")])
    key = 'content({"postMeteringOptions":null})'
    state[f"Post:{MID}"][key]["bodyModel"]["sections"] = [
        {"startIndex": 0}, {"startIndex": 1}]
    md = md_of_state(state)
    assert md == "One.\n\n---\n\nTwo.\n"


def test_iframe_embed_with_caption():
    p = para(0, "IFRAME", "Watch the demo.",
             iframe={"mediaResource": {"__ref": "MediaResource:m1"}})
    state = make_state([p])
    state["MediaResource:m1"] = {
        "title": "A talk",
        "iframeSrc": "https://cdn.embedly.com/widgets/media.html"
                     "?src=https%3A%2F%2Fwww.youtube.com%2Fembed%2Fabcdefghijk"
                     "&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabcdefghijk"}
    md = md_of_state(state)
    # the embedly wrapper unwraps to the canonical watch URL; a YouTube
    # target is a player, titled by the resource, rather than a link
    assert ('<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk" '
            'title="A talk"') in md
    # a provider's player keeps the embed form and the size the state records
    p = para(0, "IFRAME", "", iframe={"mediaResource": {"__ref": "MediaResource:m1"}})
    state = make_state([p])
    state["MediaResource:m1"] = {
        "title": "A film", "iframeWidth": "720", "iframeHeight": "405",
        "iframeSrc": "https://cdn.embedly.com/widgets/media.html"
                     "?src=https%3A%2F%2Fplayer.vimeo.com%2Fvideo%2F76979871"
                     "&url=https%3A%2F%2Fvimeo.com%2F76979871"}
    md2 = md_of_state(state)
    assert md2.startswith('<iframe src="https://player.vimeo.com/video/76979871" '
                          'title="A film" width="720" height="405" style="aspect-ratio: 720 / 405"')
    # the caption rides in the figure shell, unstyled (CSS styles it)
    assert "<figcaption>\n\nWatch the demo.\n\n</figcaption>" in md


def test_mixtape_card_becomes_a_link():
    p = para(0, "MIXTAPE_EMBED", "Repo title\nDescription line\nsite.com",
             mixtapeMetadata={"href": "https://github.com/x/y"})
    md = md_of_state(make_state([p]))
    assert md == "[Repo title](https://github.com/x/y)\n"


def test_image_alt_text_is_kept():
    p = para(0, "IMG", "", metadata={"id": "1*a.png", "alt": "A robot"})
    md = md_of_state(make_state([p]))
    assert md == "![A robot](https://miro.medium.com/v2/1*a.png)\n"


def test_image_paragraph_with_caption_and_link():
    p = para(0, "IMG", "A caption.",
             metadata={"id": "1*abc.png"}, href="https://demo.example")
    md = md_of_state(make_state([p]))
    assert "[![](https://miro.medium.com/v2/1*abc.png)](https://demo.example)" in md
    assert "<figcaption>\n\nA caption.\n\n</figcaption>" in md


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


def test_ghost_migration_pairs_collapse_in_a_state_body(tmp_path):
    # Medium's Ghost importer turned each wrapped source line into a
    # <br><br> pair, which the state carries as a blank line inside the
    # paragraph text; on a post with a Ghost origin a pair is a line
    # wrap, so it collapses to a space, while a single break stays one
    raw = tmp_path / MID
    raw.mkdir()
    (raw / "page.html").write_text(shell_html(make_state([
        para(0, "P", "A wrapped\n\nsource line."),
        para(1, "P", "A real\nsoft break."),
    ])))
    (raw / "ghost.json").write_text(json.dumps(
        {"original_url": "http://blog.example.com/2015/03/04/my-post"}))
    convert_post(URL, raw, tmp_path / "posts", prefer_page=False)
    md = (tmp_path / "posts" / "2019-12-29-my-post" / "index.md").read_text()
    assert "A wrapped source line." in md
    assert "A real  \nsoft break." in md


def test_state_subtitle_repeating_the_title_loses_it(tmp_path):
    # the stored preview subtitle is built from the body, so on a post
    # that opens with its title the subtitle repeats it; the description
    # written to front matter is the summary alone
    raw = tmp_path / MID
    raw.mkdir()
    state = make_state([para(0, "H3", "My Post"), para(1, "P", "Body text.")],
                       previewContent={"subtitle": "My Post Body text."})
    (raw / "page.html").write_text(shell_html(state))
    front = convert_post(URL, raw, tmp_path / "posts", prefer_page=False)
    assert front["description"] == "Body text."


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


def test_code_fence_language_from_metadata():
    md = md_of_state(make_state([
        para(0, "PRE", "x = 1",
             codeBlockMetadata={"mode": "EXPLICIT", "lang": "python"}),
        para(1, "PRE", "y = 2",
             codeBlockMetadata={"mode": "DISABLED", "lang": "python"}),
        para(2, "PRE", "z = 3"),
    ]))
    assert "```python\nx = 1\n```" in md
    # DISABLED means the author turned highlighting off; no metadata at
    # all (older posts) is a bare fence too
    assert "```\ny = 2\n```" in md
    assert "```\nz = 3\n```" in md


def test_mention_markup_resolves_to_profile():
    # a user mention carries no href, only the userId; the state's User
    # entry names the profile
    p = para(0, "P", "by Ann Author today")
    p["markups"] = [{"type": "A", "start": 3, "end": 13, "href": None,
                     "anchorType": "USER", "userId": "u1"}]
    md = md_of_state(make_state([p]))
    assert md == "by [Ann Author](https://medium.com/@ann) today\n"


def test_unresolvable_mention_stays_plain_text():
    p = para(0, "P", "by Ann Author today")
    p["markups"] = [{"type": "A", "start": 3, "end": 13, "href": None,
                     "anchorType": "USER", "userId": "nobody"}]
    md = md_of_state(make_state([p]))
    assert md == "by Ann Author today\n"


def gist_state(caption=""):
    """A post with a gist embed: an IFRAME whose media resource has no
    iframeSrc (gists are the embed type that doesn't go through embedly)."""
    p = para(0, "IFRAME", caption,
             iframe={"mediaResource": {"__ref": "MediaResource:m1"}})
    state = make_state([p, para(1, "P", "After.")])
    state["MediaResource:m1"] = {"id": "abc123", "iframeSrc": "",
                                 "title": "tool.py"}
    return state


def test_gist_embed_inlines_archived_files():
    media = {"abc123": {"value": {}, "gist": {"files": {
        "tool.py": {"language": "Python", "content": "print(1)"}}}}}
    body = state_body(gist_state(), MID, "My Post", media)
    markdown, _ = to_markdown(body, URL, {}, None)
    assert "```python\nprint(1)\n```" in markdown
    assert "missing embed" not in markdown


def test_markdown_gist_file_is_inlined_as_markdown():
    # a Markdown gist is prose Medium could not hold (a table): its
    # source goes out verbatim, not fenced, so the table renders; a code
    # file in the same gist still gets its fence
    table = "| Theme | People |\n| --- | --- |\n| Large data | 15 *ish* |"
    media = {"abc123": {"value": {}, "gist": {"files": {
        "OTHER-THEMES.md": {"language": "Markdown", "type": "text/markdown",
                            "content": table},
        "tool.py": {"language": "Python", "content": "print(1)"}}}}}
    body = state_body(gist_state(), MID, "My Post", media)
    markdown, _ = to_markdown(body, URL, {}, None)
    assert markdown.startswith(f"{table}\n\n```python\nprint(1)\n```\n")
    assert "```markdown" not in markdown
    assert "After." in markdown


def test_captioned_markdown_gist_keeps_its_figure_shell():
    media = {"abc123": {"value": {}, "gist": {"files": {
        "notes.md": {"language": "Markdown", "content": "| a | b |\n| - | - |"}}}}}
    body = state_body(gist_state("Table 1"), MID, "My Post", media)
    markdown, _ = to_markdown(body, URL, {}, None)
    assert markdown.startswith(
        "<figure>\n\n| a | b |\n| - | - |\n\n<figcaption>\n\nTable 1\n\n"
        "</figcaption>\n\n</figure>\n")


def test_unarchived_gist_embed_gets_placeholder():
    # never silently dropped: without archived media the embed becomes a
    # visible placeholder that lint flags
    markdown, _ = to_markdown(state_body(gist_state(), MID, "My Post"),
                              URL, {}, None)
    assert "[missing embed: tool.py]" in markdown
    assert "After." in markdown


def test_media_payload_can_name_the_embed_target():
    # a non-gist media resource: the archived payload's own iframeSrc
    media = {"abc123": {"value": {"iframeSrc": "https://example.com/embed"}}}
    body = state_body(gist_state(), MID, "My Post", media)
    markdown, _ = to_markdown(body, URL, {}, None)
    assert "[embed: https://example.com/embed]" in markdown


def test_convert_post_inlines_gist_from_media(tmp_path):
    raw = tmp_path / MID
    (raw / "media").mkdir(parents=True)
    (raw / "page.html").write_text(shell_html(gist_state()))
    (raw / "media" / "abc123.json").write_text(json.dumps(
        {"payload": {"value": {"gist": {"gistId": "g1"}}}}))
    (raw / "media" / "abc123.gist.json").write_text(json.dumps(
        {"files": {"tool.py": {"language": "Python", "content": "print(1)"}}}))
    convert_post(URL, raw, tmp_path / "posts", prefer_page=False)
    out = (tmp_path / "posts" / "2019-12-29-my-post" / "index.md").read_text()
    assert "```python\nprint(1)\n```" in out


def test_state_embed_targets_lists_resolvable_embeds_only():
    from medium_archive.state import state_embed_targets
    p = para(0, "IFRAME", "", iframe={"mediaResource": {"__ref": "MediaResource:m1"}})
    state = gist_state()                      # m1: a gist, no target
    state["Paragraph:v_2"] = {**p, "id": "v_2",
                              "iframe": {"mediaResource": {"__ref": "MediaResource:m2"}}}
    state[f"Post:{MID}"]['content({"postMeteringOptions":null})']["bodyModel"][
        "paragraphs"].append({"__ref": "Paragraph:v_2"})
    state["MediaResource:m2"] = {
        "id": "def456", "title": "A talk",
        "iframeSrc": "https://cdn.embedly.com/widgets/media.html"
                     "?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc"}
    assert state_embed_targets(shell_html(state), MID) == [
        ("https://www.youtube.com/watch?v=abc", "A talk")]
    assert state_embed_targets("<html>no state</html>", MID) == []
