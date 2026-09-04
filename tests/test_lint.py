"""lint_post defect signatures on converted posts."""

import json
from pathlib import Path

from medium_archive.lint import lint_post

FRONT = {"title": "A Post", "date": "2020-01-01T00:00:00Z"}


def write_post(tmp_path: Path, body: str, front: dict = FRONT,
               name: str = "2020-01-01-a-post") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "index.md").write_text(f"---\n{json.dumps(front)}\n---\n\n{body}")
    return d


def test_clean_post_passes(tmp_path):
    d = write_post(tmp_path, "Just a paragraph of honest prose.\n" * 10)
    assert lint_post(d) == ([], [])


def test_emphasis_commonmark_will_not_read_is_flagged(tmp_path):
    """The markers a reader would be shown. convert writes these as
    <em>/<strong>, so any left in a converted post means the post
    predates that or a fixup put it back."""
    d = write_post(tmp_path, "x\n" * 100 + "for next task**.** And so on\n")
    errors, _ = lint_post(d)
    assert any("emphasis CommonMark will not read" in e for e in errors)

    # what CommonMark does read, and what is not prose, are left alone
    body = ("x\n" * 100 + "a *word* and **another** one\n"
            "the mask is 10.0.0.* here\n"
            "a `code**.**span` stays\n"
            "and ``a `backtick` span**.**too`` stays\n"
            "```\nliteral**.**markers\n```\n")
    assert lint_post(write_post(tmp_path, body, name="2020-01-02-clean")) \
        == ([], [])


def test_medium_chrome_is_flagged(tmp_path):
    d = write_post(tmp_path, "x\n" * 100 +
                   "[Sign in](https://medium.com/m/signin?operation=login&x=1)\n")
    errors, _ = lint_post(d)
    assert any("chrome" in e for e in errors)


def test_byline_avatar_is_flagged(tmp_path):
    d = write_post(tmp_path, "x\n" * 100 +
                   "[![A](https://miro.medium.com/v2/1*a.jpeg)]"
                   "(https://a.medium.com/?source=post_page---byline--1--)\n")
    errors, _ = lint_post(d)
    assert errors


def test_remote_cdn_image_is_flagged_outside_fences_only(tmp_path):
    img = "![x](https://miro.medium.com/v2/1*a.jpeg)"
    errors, _ = lint_post(write_post(tmp_path, "x\n" * 100 + img + "\n"))
    assert any("CDN" in e for e in errors)
    # the same line inside a code fence is literal content
    errors, _ = lint_post(write_post(tmp_path, "x\n" * 100 + f"```\n{img}\n```\n",
                                     name="2020-01-02-fenced"))
    assert not errors


def test_unclosed_fence_is_flagged(tmp_path):
    d = write_post(tmp_path, "x\n" * 100 + "```\ncode with no closing fence\n")
    errors, _ = lint_post(d)
    assert any("fence" in e for e in errors)


def test_missing_image_file_is_flagged(tmp_path):
    d = write_post(tmp_path, "x\n" * 100 + "![x](images/gone.png)\n")
    errors, _ = lint_post(d)
    assert any("missing" in e for e in errors)


def test_short_body_and_empty_front_matter_warn(tmp_path):
    d = write_post(tmp_path, "tiny\n", front={"title": "", "date": ""})
    errors, warnings = lint_post(d)
    assert not errors
    assert len(warnings) == 3


def test_missing_embed_placeholder_is_flagged(tmp_path):
    d = write_post(tmp_path, "x\n" * 100 + "[missing embed: tool.py]\n")
    errors, _ = lint_post(d)
    assert any("embed" in e for e in errors)
    # markdownify may escape the bracket
    d = write_post(tmp_path, "x\n" * 100 + "\\[missing embed: tool.py]\n",
                   name="2020-01-02-escaped")
    errors, _ = lint_post(d)
    assert any("embed" in e for e in errors)
    # inside a code fence it is literal content
    errors, _ = lint_post(write_post(
        tmp_path, "x\n" * 100 + "```\n[missing embed: tool.py]\n```\n",
        name="2020-01-03-fenced"))
    assert not errors


def test_seo_analysis_is_opt_in(tmp_path):
    """--seo adds the page analysis an SEO plugin runs (title and
    description length, a missing description, images without alt
    text, no cover image), as warnings, and only when asked for."""
    body = ("x\n" * 100 + "![](images/bare.png)\n\n"
            "<figure>\n\n![](images/captioned.png)\n\n<figcaption>\n\n"
            "Captioned\n\n</figcaption>\n\n</figure>\n")
    d = write_post(tmp_path, body, front={
        "title": "A title that runs well past the sixty characters a result shows",
        "date": "2020-01-01T00:00:00Z", "description": "d" * 200,
        "images": []})
    (d / "images").mkdir()
    for name in ("bare.png", "captioned.png"):
        (d / "images" / name).write_bytes(b"PNG")
    assert lint_post(d) == ([], [])
    errors, warnings = lint_post(d, seo=True)
    assert not errors
    assert [w.split(":")[0] for w in warnings] == [
        "title is 63 chars; a search result shows about 60",
        "description is 200 chars; a search result shows about 160",
        "image without alt text",
        "no image a card cover or a share preview could use (site.json \"share_image\" stands in)"]
    assert "images/bare.png" in warnings[2]
    # a captioned figure's image gets its alt from the caption
    assert not any("captioned" in w for w in warnings)

    d = write_post(tmp_path, "x\n" * 100 + "![](images/p.png)\n",
                   front={"title": "Short", "date": "2020-01-01T00:00:00Z",
                          "images": ["images/p.png"]},
                   name="2020-01-02-short")
    (d / "images").mkdir()
    (d / "images" / "p.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + (100).to_bytes(4, "big") * 2)
    _, warnings = lint_post(d, seo=True)
    assert warnings == ["no description: search results and share cards "
                        "get the site's, or none",
                        "image without alt text: images/p.png"]


def test_duplicate_titles_are_reported_across_posts():
    from medium_archive.lint import duplicate_titles
    got = duplicate_titles({"a": "Release notes", "b": "release notes ",
                            "c": "Other", "d": ""})
    assert len(got) == 1 and "'a' and 'b'" in got[0]
    assert duplicate_titles({"a": "x", "b": "y"}) == []


def test_embeds_mode_is_opt_in_and_flags_bare_embed_links(tmp_path):
    """--embeds reports every embed that is still the link convert left
    for an iframe: the sites show the link, not the content. Off by
    default, and a link inside a code fence is literal content."""
    body = ("x\n" * 100 +
            "[embed: https://www.youtube.com/watch?v=a]"
            "(https://www.youtube.com/watch?v=a)\n"
            "```\n[embed: https://x.example/b](https://x.example/b)\n```\n")
    d = write_post(tmp_path, body)
    assert lint_post(d) == ([], [])
    errors, warnings = lint_post(d, embeds=True)
    assert not warnings
    assert errors == ["embed is a bare link, its content is not in the "
                      "archive: https://www.youtube.com/watch?v=a "
                      "(replace it by hand)"]


def test_embeds_mode_reports_embeds_the_body_source_dropped(tmp_path):
    """With the archive's raw/ at hand, --embeds compares the body's
    embed links against the embeds the page's editor state resolves:
    fewer links means the export or feed body lost some. Gist embeds
    (no target in the state) are not expected as links."""
    from test_state import MID, make_state, para, shell_html

    def embed(i, target, title):
        p = para(i, "IFRAME", "",
                 iframe={"mediaResource": {"__ref": f"MediaResource:m{i}"}})
        return p, {"id": f"m{i}", "title": title, "iframeSrc": target and (
            "https://cdn.embedly.com/widgets/media.html?url=" + target)}

    paras = [embed(0, "https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Da", "A talk"),
             embed(1, "https%3A%2F%2Ftwitter.com%2Fx%2Fstatus%2F1", "X on Twitter"),
             embed(2, "", "tool.py")]
    state = make_state([p for p, _ in paras])
    for i, (_, res) in enumerate(paras):
        state[f"MediaResource:m{i}"] = res
    raw = tmp_path / "raw"
    (raw / MID).mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))

    body = ("x\n" * 100 + "[embed: https://www.youtube.com/embed/a]"
            "(https://www.youtube.com/embed/a)\n```\nprint(1)\n```\n")
    front = {**FRONT, "medium_id": MID, "body_source": "export"}
    d = write_post(tmp_path, body, front=front)
    errors, _ = lint_post(d, embeds=True, raw_root=raw)
    assert len(errors) == 2
    assert errors[0].startswith("embed is a bare link")
    assert errors[1] == ("body source 'export' dropped 1 embed(s) the page's "
                         "editor state carries (state has 2: 'A talk', "
                         "'X on Twitter'); restore them in a fixup")
    # the state's own conversion keeps every embed: nothing dropped
    body = body.replace("```\nprint(1)\n```\n",
                        "[embed: https://twitter.com/x/status/1]"
                        "(https://twitter.com/x/status/1)\n")
    d = write_post(tmp_path, body, front={**front, "body_source": "state"},
                   name="2020-01-02-from-state")
    errors, _ = lint_post(d, embeds=True, raw_root=raw)
    assert len(errors) == 2 and errors[0].startswith("embed is a bare link")
    assert errors[1].startswith("tweet not archived, embed is a bare link")
    # no page (or no raw/) to compare against: only the links
    errors, _ = lint_post(d, embeds=True, raw_root=tmp_path / "nowhere")
    assert len(errors) == 2


def test_youtube_player_is_content_not_a_bare_link(tmp_path):
    """A YouTube embed convert kept as a player is filled in: --embeds
    does not report it, and it counts against the state's embeds."""
    from test_state import MID, make_state, para, shell_html
    player = ('<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk" '
              'title="A talk" width="560" height="315" loading="lazy" '
              "allowfullscreen></iframe>")
    d = write_post(tmp_path, "x\n" * 100 + player + "\n",
                   front={**FRONT, "medium_id": MID, "body_source": "export"})
    p = para(0, "IFRAME", "", iframe={"mediaResource": {"__ref": "MediaResource:m0"}})
    state = make_state([p])
    state["MediaResource:m0"] = {
        "id": "m0", "title": "A talk",
        "iframeSrc": "https://cdn.embedly.com/widgets/media.html"
                     "?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabcdefghijk"}
    raw = tmp_path / "raw"
    (raw / MID).mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))
    assert lint_post(d, embeds=True, raw_root=raw) == ([], [])


def test_giphy_embed_is_an_asset_not_a_link(tmp_path):
    """A Giphy embed converts to an image or clip: not a bare link, not
    among the embeds a body source could have dropped, and reported
    only while it is still served from Giphy."""
    from test_state import MID, make_state, para, shell_html
    gif = "https://media.giphy.com/media/fWgAW7WZtPMBjmpa3V/giphy.gif"
    mp4 = "https://media.giphy.com/media/Ri327iDKuC4pnExM4L/giphy.mp4"
    state = make_state([
        para(0, "IFRAME", "", iframe={"mediaResource": {"__ref": "MediaResource:m0"}}),
        para(1, "IFRAME", "", iframe={"mediaResource": {"__ref": "MediaResource:m1"}})])
    for i, url in enumerate((gif, mp4)):
        state[f"MediaResource:m{i}"] = {
            "id": f"m{i}", "title": "", "iframeSrc":
            "https://cdn.embedly.com/widgets/media.html?url=" + url.replace("/", "%2F")}
    raw = tmp_path / "raw"
    (raw / MID).mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))
    front = {**FRONT, "medium_id": MID, "body_source": "export"}
    d = write_post(tmp_path, "x\n" * 100 + "![](images/001-giphy.gif)\n\n"
                   '<video src="images/002-giphy.mp4" autoplay loop muted playsinline></video>\n',
                   front=front)
    (d / "images").mkdir()
    (d / "images" / "001-giphy.gif").write_bytes(b"GIF89a")
    assert lint_post(d, embeds=True, raw_root=raw) == ([], [])
    d = write_post(tmp_path, "x\n" * 100 + f"![]({gif})\n\n"
                   f'<video src="{mp4}" autoplay loop muted playsinline></video>\n',
                   front=front, name="2020-01-02-remote")
    errors, _ = lint_post(d, embeds=True, raw_root=raw)
    tail = " (re-run fetch; `fetch --urls` takes this post's name)"
    assert errors == [f"embed media not archived, served remotely: {gif}{tail}",
                      f"embed media not archived, served remotely: {mp4}{tail}"]


def test_archived_tweet_quote_is_content(tmp_path):
    """The blockquote an archived tweet became counts against the
    state's embeds like a player; an unarchived one is reported as a
    tweet, with fetch as the remedy."""
    from test_state import MID, make_state, para, shell_html
    state = make_state([para(0, "IFRAME", "",
                             iframe={"mediaResource": {"__ref": "MediaResource:m0"}})])
    state["MediaResource:m0"] = {
        "id": "m0", "title": "Ann on Twitter", "iframeSrc":
        "https://cdn.embedly.com/widgets/media.html?url=https%3A%2F%2Ftwitter.com%2Fann%2Fstatus%2F12345"}
    raw = tmp_path / "raw"
    (raw / MID).mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))
    front = {**FRONT, "medium_id": MID, "body_source": "export"}
    quote = ("> Hello [world](https://e.com)\n>\n> \u2014 [Ann (@ann)](https://twitter.com/ann), "
             "[May 1, 2020](https://twitter.com/ann/status/12345)\n")
    d = write_post(tmp_path, "x\n" * 100 + quote, front=front)
    assert lint_post(d, embeds=True, raw_root=raw) == ([], [])
    d = write_post(tmp_path, "x\n" * 100 + "[embed: https://twitter.com/ann/status/12345]"
                   "(https://twitter.com/ann/status/12345)\n", front=front,
                   name="2020-01-02-bare")
    errors, _ = lint_post(d, embeds=True, raw_root=raw)
    assert errors == ["tweet not archived, embed is a bare link: "
                      "https://twitter.com/ann/status/12345 (re-run fetch for its "
                      "text; a deleted tweet stays a link)"]


def test_archived_carbon_snippet_is_not_a_dropped_embed(tmp_path):
    """An archived Carbon snippet converts to a fence, which the
    cross-check cannot count, so its target leaves the state's list."""
    from test_state import MID, make_state, para, shell_html
    state = make_state([para(0, "IFRAME", "",
                             iframe={"mediaResource": {"__ref": "MediaResource:m0"}})])
    state["MediaResource:m0"] = {
        "id": "m0", "title": "Carbon snippet", "iframeSrc":
        "https://cdn.embedly.com/widgets/media.html?url=https%3A%2F%2Fcarbon.now.sh%2FPaDDn2ZszZUVmuhvRP52"}
    raw = tmp_path / "raw"
    (raw / MID / "media").mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))
    front = {**FRONT, "medium_id": MID, "body_source": "state"}
    d = write_post(tmp_path, "x\n" * 100 + "```python\nx = 1\n```\n", front=front)
    errors, _ = lint_post(d, embeds=True, raw_root=raw)
    assert errors and "dropped 1 embed" in errors[0]
    (raw / MID / "media" / "carbon-PaDDn2ZszZUVmuhvRP52.json").write_text("{}")
    assert lint_post(d, embeds=True, raw_root=raw) == ([], [])


def test_provider_link_is_not_a_dropped_embed(tmp_path):
    from test_state import MID, make_state, para, shell_html
    state = make_state([para(0, "IFRAME", "",
                             iframe={"mediaResource": {"__ref": "MediaResource:m0"}})])
    state["MediaResource:m0"] = {
        "id": "m0", "title": "Ep. 248", "iframeSrc":
        "https://cdn.embedly.com/widgets/media.html?url=https%3A%2F%2Fart19.com%2Fshows%2Flc%2Fepisodes%2Fce2c"}
    raw = tmp_path / "raw"
    (raw / MID).mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))
    d = write_post(tmp_path, "x\n" * 100 + "[Ep. 248](https://art19.com/shows/lc/episodes/ce2c)\n",
                   front={**FRONT, "medium_id": MID, "body_source": "state"})
    assert lint_post(d, embeds=True, raw_root=raw) == ([], [])


def test_unfetched_tweet_photo_is_reported(tmp_path):
    d = write_post(tmp_path, "x\n" * 100 +
                   "> ![](https://pbs.twimg.com/media/CnW7DC6VUAE7NaZ.jpg)\n")
    errors, _ = lint_post(d, embeds=True)
    assert errors == ["embed media not archived, served remotely: "
                      "https://pbs.twimg.com/media/CnW7DC6VUAE7NaZ.jpg "
                      "(re-run fetch; `fetch --urls` takes this post's name)"]


def test_recorded_deleted_tweet_is_not_an_unfilled_embed(tmp_path):
    from test_state import MID, make_state, para, shell_html
    state = make_state([para(0, "IFRAME", "",
                             iframe={"mediaResource": {"__ref": "MediaResource:m0"}})])
    state["MediaResource:m0"] = {
        "id": "m0", "title": "", "iframeSrc":
        "https://cdn.embedly.com/widgets/media.html?url=https%3A%2F%2Ftwitter.com%2Fann%2Fstatus%2F12345"}
    raw = tmp_path / "raw"
    (raw / MID / "media").mkdir(parents=True)
    (raw / MID / "page.html").write_text(shell_html(state))
    (raw / MID / "media" / "tweet-12345.json").write_text('{"deleted": true}')
    d = write_post(tmp_path, "x\n" * 100 +
                   "[A tweet by @ann, no longer available](https://twitter.com/ann/status/12345)\n",
                   front={**FRONT, "medium_id": MID, "body_source": "state"})
    assert lint_post(d, embeds=True, raw_root=raw) == ([], [])


def test_a_short_post_that_carries_its_own_summary_is_not_short(tmp_path):
    # a 2015 welcome note is one sentence long, and its description is
    # that sentence: nothing was lost in conversion
    text = "Watch this space for announcements about Jupyter and IPython."
    d = write_post(tmp_path, text + "\n", front={**FRONT, "description": text})
    assert lint_post(d) == ([], [])
    # a description the body does not carry is a lost body
    d = write_post(tmp_path, "Watch this\n", front={**FRONT, "description": text},
                   name="2020-01-02-lost")
    _, warnings = lint_post(d)
    assert warnings == ["body is only 11 chars"]
