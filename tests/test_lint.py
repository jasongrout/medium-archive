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
