"""tags.json: parsing, validation, application to front matter, and the
stale-entry check on full convert runs."""

import json
from types import SimpleNamespace

import pytest

from medium_archive.convert import cmd_convert, convert_post
from medium_archive.tags import load_tag_map

URL = "https://blog.example.com/my-post-0123456789ab"


def write_config(tmp_path, config):
    (tmp_path / "tags.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def write_raw_post(out, tags):
    raw = out / "raw" / "0123456789ab"
    raw.mkdir(parents=True)
    (raw / "feed_item.json").write_text(json.dumps({
        "title": "My post", "author": "Ann",
        "date": "2020-01-01T00:00:00Z", "tags": list(tags),
        "content_html": "<p>A body of prose long enough to be a post.</p>"}))
    (out / "raw" / "index.json").write_text(json.dumps(
        {URL: {"medium_id": "0123456789ab"}}))
    return raw


def convert_args(out, only=None):
    return SimpleNamespace(out=out, only=only, clean=False, prefer_page=False,
                           prefer_ghost=False, base=None)


def test_no_tags_json_is_none(tmp_path):
    assert load_tag_map(tmp_path) is None


def test_drop_and_rename_apply_sorted_and_deduped(tmp_path):
    out = write_config(tmp_path, {
        "drop": ["jupyter"],
        "rename": {"notebook": "jupyter-notebook",
                   "notebooks": "jupyter-notebook"}})
    tag_map = load_tag_map(out)
    # both variants collapse onto a tag the post already carries -- once
    assert tag_map.apply(["notebook", "jupyter", "python", "notebooks",
                          "jupyter-notebook"]) \
        == ["jupyter-notebook", "python"]


def test_unused_entries_are_tracked(tmp_path):
    out = write_config(tmp_path, {"drop": ["jupyter"],
                                  "rename": {"notebook": "jupyter-notebook"}})
    tag_map = load_tag_map(out)
    assert tag_map.unused() == ["jupyter", "notebook"]
    tag_map.apply(["jupyter", "python"])
    assert tag_map.unused() == ["notebook"]
    tag_map.apply(["notebook"])
    assert tag_map.unused() == []


@pytest.mark.parametrize("config, message", [
    ({"delete": ["a"]}, "unknown key"),
    ({"drop": "a"}, "must be a list"),
    ({"rename": ["a"]}, "must be an object"),
    ({"drop": ["a", "a"]}, "listed twice"),
    ({"drop": [1]}, "non-empty strings"),
    ({"drop": [" a"]}, "whitespace"),
    ({"rename": {"a": ""}}, "non-empty strings"),
    ({"rename": {"a": "a"}}, "renamed to itself"),
    ({"drop": ["a"], "rename": {"a": "b"}}, "both dropped and renamed"),
    ({"drop": ["b"], "rename": {"a": "b"}}, "is dropped"),
    ({"rename": {"a": "b", "b": "c"}}, "is itself renamed"),
    ({"add": ["a"]}, "must be an object"),
    ({"add": {"": ["a"]}}, "non-empty strings"),
    ({"add": {" s": ["a"]}}, "whitespace"),
    ({"add": {"s": []}}, "non-empty list"),
    ({"add": {"s": "a"}}, "non-empty list"),
    ({"add": {"s": ["a", "a"]}}, "listed twice"),
    ({"add": {"s": [""]}}, "non-empty strings"),
    ({"rename": {"a": "b"}, "add": {"s": ["a"]}}, "add the final tag"),
])
def test_malformed_config_aborts(tmp_path, config, message):
    write_config(tmp_path, config)
    with pytest.raises(SystemExit, match=message):
        load_tag_map(tmp_path)


def test_invalid_json_aborts(tmp_path):
    (tmp_path / "tags.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="not valid JSON"):
        load_tag_map(tmp_path)


def test_convert_post_writes_cleaned_tags(tmp_path):
    raw = write_raw_post(tmp_path, ["jupyter", "notebook", "python"])
    tag_map = load_tag_map(write_config(tmp_path, {
        "drop": ["jupyter"], "rename": {"notebook": "jupyter-notebook"}}))
    post = convert_post(URL, raw, tmp_path / "posts", prefer_page=False,
                        tag_map=tag_map)
    assert post["tags"] == ["jupyter-notebook", "python"]
    front = (tmp_path / "posts" / "2020-01-01-my-post" / "index.md") \
        .read_text(encoding="utf-8")
    assert "jupyter-notebook" in front and '"jupyter"' not in front


def test_add_applies_by_slug_and_dedupes(tmp_path):
    out = write_config(tmp_path, {
        "rename": {"notebook": "jupyter-notebook"},
        "add": {"my-post": ["releases", "python"]}})
    tag_map = load_tag_map(out)
    # a tag the post already carries (here via rename) is not re-added
    assert tag_map.apply(["notebook", "python"], "my-post") \
        == ["jupyter-notebook", "python", "releases"]
    # a different slug is untouched by the entry
    assert tag_map.apply(["python"], "other-post") == ["python"]


def test_add_pairs_track_usage_per_tag(tmp_path):
    out = write_config(tmp_path, {"add": {"my-post": ["releases", "python"]}})
    tag_map = load_tag_map(out)
    assert tag_map.unused() == ["my-post: +python", "my-post: +releases"]
    tag_map.apply(["python"], "my-post")     # adds releases, python was there
    assert tag_map.unused() == ["my-post: +python"]


def test_drop_then_add_splits_an_overapplied_tag(tmp_path):
    # dropping clears the inherited uses; add re-asserts the tag on the
    # posts that genuinely deserve it
    out = write_config(tmp_path, {
        "drop": ["notebook"], "add": {"my-post": ["notebook"]}})
    tag_map = load_tag_map(out)
    assert tag_map.apply(["notebook", "python"], "other-post") == ["python"]
    assert tag_map.apply(["notebook", "python"], "my-post") \
        == ["notebook", "python"]
    assert tag_map.unused() == []


def test_convert_post_writes_added_tags(tmp_path):
    raw = write_raw_post(tmp_path, ["notebook"])
    tag_map = load_tag_map(write_config(tmp_path, {
        "rename": {"notebook": "jupyter-notebook"},
        "add": {"my-post": ["releases"]}}))
    post = convert_post(URL, raw, tmp_path / "posts", prefer_page=False,
                        tag_map=tag_map)
    assert post["tags"] == ["jupyter-notebook", "releases"]


def test_full_convert_aborts_on_stale_entry(tmp_path):
    write_raw_post(tmp_path, ["python"])
    write_config(tmp_path, {"drop": ["python", "no-such-tag"]})
    with pytest.raises(SystemExit,
                       match="entries changed no post: no-such-tag"):
        cmd_convert(convert_args(tmp_path))
    # the converted output itself is fine; only the config is stale
    manifest = json.loads((tmp_path / "posts.json").read_text())
    assert manifest[URL]["tags"] == []


def test_full_convert_aborts_on_redundant_add(tmp_path):
    write_raw_post(tmp_path, ["python"])
    write_config(tmp_path, {"add": {"my-post": ["python"]}})
    with pytest.raises(SystemExit, match=r"my-post: \+python"):
        cmd_convert(convert_args(tmp_path))


def test_full_convert_aborts_on_add_for_unknown_slug(tmp_path):
    write_raw_post(tmp_path, ["python"])
    write_config(tmp_path, {"add": {"no-such-post": ["python"]}})
    with pytest.raises(SystemExit, match=r"no-such-post: \+python"):
        cmd_convert(convert_args(tmp_path))


def test_only_run_skips_the_stale_check(tmp_path):
    write_raw_post(tmp_path, ["python"])
    write_config(tmp_path, {"drop": ["no-such-tag"]})
    cmd_convert(convert_args(tmp_path, only=[URL]))    # must not raise
    manifest = json.loads((tmp_path / "posts.json").read_text())
    assert manifest[URL]["tags"] == ["python"]
