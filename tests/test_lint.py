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
