"""Fixups: parsing <out>/fixups/*.patch and *.sub and applying them to
the in-memory text of raw files."""

import difflib

import pytest

from medium_archive.fixup import load_fixups, read_raw

RAW = "<p>one</p>\n<p>two</p>\n<p>three</p>\n<p>four</p>\n"
FIXED = "<p>one</p>\n<p>2</p>\n<p>three</p>\n<p>four</p>\n"


def patch_text(a, b, a_name="a/abc123/ghost.html", b_name="b/abc123/ghost.html"):
    return "\n".join(difflib.unified_diff(
        a.split("\n"), b.split("\n"), a_name, b_name, lineterm="")) + "\n"


def write_out(tmp_path, raw_text=RAW, patches=()):
    (tmp_path / "raw" / "abc123").mkdir(parents=True)
    (tmp_path / "raw" / "abc123" / "ghost.html").write_text(raw_text)
    (tmp_path / "fixups").mkdir()
    for name, text in patches:
        (tmp_path / "fixups" / name).write_text(text)
    return tmp_path


def test_no_fixups_dir_is_empty(tmp_path):
    assert load_fixups(tmp_path) == {}


def test_read_raw_without_fixups(tmp_path):
    out = write_out(tmp_path)
    assert read_raw(out / "raw" / "abc123" / "ghost.html", None) == RAW
    assert read_raw(out / "raw" / "abc123" / "ghost.html", {}) == RAW


def test_apply_simple_hunk(tmp_path):
    out = write_out(tmp_path, patches=[("fix.patch", patch_text(RAW, FIXED))])
    fixups = load_fixups(out)
    assert read_raw(out / "raw" / "abc123" / "ghost.html", fixups) == FIXED


def test_comments_and_git_headers_are_ignored(tmp_path):
    text = ("# why: the capture's href is broken\n"
            "diff --git a/abc123/ghost.html b/abc123/ghost.html\n"
            + patch_text(RAW, FIXED))
    out = write_out(tmp_path, patches=[("fix.patch", text)])
    assert read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out)) == FIXED


def test_path_prefix_conventions_match(tmp_path):
    # paths are keyed by their last two components, whatever the prefix
    text = patch_text(RAW, FIXED, "raw/abc123/ghost.html",
                      "medium_export/raw/abc123/ghost.html")
    out = write_out(tmp_path, patches=[("fix.patch", text)])
    assert read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out)) == FIXED


def test_drifted_hunk_found_by_context(tmp_path):
    # file gained lines above the hunk since the patch was made
    out = write_out(tmp_path, raw_text="<p>new</p>\n<p>new</p>\n" + RAW,
                    patches=[("fix.patch", patch_text(RAW, FIXED))])
    got = read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))
    assert got == "<p>new</p>\n<p>new</p>\n" + FIXED


def test_stale_hunk_aborts(tmp_path):
    out = write_out(tmp_path, raw_text=RAW.replace("two", "TWO"),
                    patches=[("fix.patch", patch_text(RAW, FIXED))])
    with pytest.raises(SystemExit, match="matches nowhere"):
        read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))


def test_ambiguous_hunk_aborts(tmp_path):
    # drifted (nothing at the stated position) AND duplicated context
    doubled = "<p>pad</p>\n" * 3 + RAW + RAW
    bare = "\n".join(difflib.unified_diff(
        RAW.split("\n"), FIXED.split("\n"),
        "a/abc123/ghost.html", "b/abc123/ghost.html", lineterm="", n=0)) + "\n"
    out = write_out(tmp_path, raw_text=doubled, patches=[("fix.patch", bare)])
    with pytest.raises(SystemExit, match="ambiguous"):
        read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))


def test_two_files_in_one_patch(tmp_path):
    other = patch_text("x\ny\n", "x\nz\n",
                       "a/abc123/export.html", "b/abc123/export.html")
    out = write_out(tmp_path,
                    patches=[("fix.patch", patch_text(RAW, FIXED) + other)])
    (out / "raw" / "abc123" / "export.html").write_text("x\ny\n")
    fixups = load_fixups(out)
    assert read_raw(out / "raw" / "abc123" / "ghost.html", fixups) == FIXED
    assert read_raw(out / "raw" / "abc123" / "export.html", fixups) == "x\nz\n"


def test_sub_literal(tmp_path):
    out = write_out(tmp_path, patches=[("fix.sub",
        "# a one-character fix, reviewable\n"
        "file: abc123/ghost.html\n"
        "old: <p>two</p>\n"
        "new: <p>2</p>\n")])
    assert read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out)) == FIXED


def test_sub_count_must_match_exactly(tmp_path):
    raw = RAW + RAW                        # pattern occurs twice
    out = write_out(tmp_path, raw_text=raw, patches=[("fix.sub",
        "file: abc123/ghost.html\nold: <p>two</p>\nnew: <p>2</p>\n")])
    with pytest.raises(SystemExit, match="matches 2 time"):
        read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))
    out2 = write_out(tmp_path / "b", raw_text=raw, patches=[("fix.sub",
        "file: abc123/ghost.html\ncount: 2\nold: <p>two</p>\nnew: <p>2</p>\n")])
    got = read_raw(out2 / "raw" / "abc123" / "ghost.html", load_fixups(out2))
    assert got == FIXED + FIXED


def test_sub_missing_text_aborts(tmp_path):
    out = write_out(tmp_path, patches=[("fix.sub",
        "file: abc123/ghost.html\nold: <p>gone</p>\nnew: <p>x</p>\n")])
    with pytest.raises(SystemExit, match="matches 0 time"):
        read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))


def test_sub_regex(tmp_path):
    out = write_out(tmp_path, patches=[("fix.sub",
        "file: abc123/ghost.html\n"
        "count: 4\n"
        r"old-regex: <p>(\w+)</p>" + "\n"
        r"new: <div>\1</div>" + "\n")])
    got = read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))
    assert got == RAW.replace("<p>", "<div>").replace("</p>", "</div>")


def test_sub_several_files_and_pairs(tmp_path):
    out = write_out(tmp_path, patches=[("fix.sub",
        "file: abc123/ghost.html\n"
        "old: <p>two</p>\n"
        "new: <p>2</p>\n"
        "file: abc123/export.html\n"
        "old: y\n"
        "new: z\n")])
    (out / "raw" / "abc123" / "export.html").write_text("x\ny\n")
    fixups = load_fixups(out)
    assert read_raw(out / "raw" / "abc123" / "ghost.html", fixups) == FIXED
    assert read_raw(out / "raw" / "abc123" / "export.html", fixups) == "x\nz\n"


def test_sub_malformed_aborts(tmp_path):
    for i, (bad, msg) in enumerate([
            ("old: x\n", "'old' without 'new'"),
            ("new: x\n", "'new' without 'old'"),
            ("old: x\nnew: y\n", "before 'file:'"),
            ("file: abc123/ghost.html\nnonsense line\n", "malformed")]):
        out = write_out(tmp_path / str(i), patches=[("fix.sub", bad)])
        with pytest.raises(SystemExit, match=msg):
            load_fixups(out)


def test_sub_and_patch_apply_in_name_order(tmp_path):
    # a.sub rewrites two -> 2; b.patch then rewrites the result
    out = write_out(tmp_path, patches=[
        ("a.sub", "file: abc123/ghost.html\nold: <p>two</p>\nnew: <p>2</p>\n"),
        ("b.patch", patch_text(FIXED, FIXED.replace("<p>2</p>", "<p>22</p>")))])
    got = read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out))
    assert got == FIXED.replace("<p>2</p>", "<p>22</p>")


def test_pure_insertion(tmp_path):
    inserted = RAW.replace("<p>three</p>\n", "<p>three</p>\n<p>extra</p>\n")
    bare = "\n".join(difflib.unified_diff(
        RAW.split("\n"), inserted.split("\n"),
        "a/abc123/ghost.html", "b/abc123/ghost.html", lineterm="", n=0)) + "\n"
    out = write_out(tmp_path, patches=[("fix.patch", bare)])
    assert read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out)) == inserted


def test_embed_media_files_are_keyed_under_their_post(tmp_path):
    # an archived gist, tweet or Carbon snippet lives in the post's
    # media/ directory; the fixup names it as <medium_id>/media/<name>
    out = write_out(tmp_path, patches=[("lang.sub", (
        "file: abc123/media/carbon-x.json\n"
        'old: "id": "x"\nnew: "language": "tsx", "id": "x"\n'))])
    media = out / "raw" / "abc123" / "media"
    media.mkdir()
    (media / "carbon-x.json").write_text('{"code": "1", "id": "x"}')
    fixups = load_fixups(out)
    assert list(fixups) == ["abc123/media/carbon-x.json"]
    assert read_raw(media / "carbon-x.json", fixups) == '{"code": "1", "language": "tsx", "id": "x"}'
    # a patch header path resolves the same way
    out2 = write_out(tmp_path / "two", patches=[("m.patch", patch_text(
        '{"id": "x"}\n', '{"id": "y"}\n', "a/abc123/media/carbon-x.json",
        "b/abc123/media/carbon-x.json"))])
    (out2 / "raw" / "abc123" / "media").mkdir()
    (out2 / "raw" / "abc123" / "media" / "carbon-x.json").write_text('{"id": "x"}\n')
    assert list(load_fixups(out2)) == ["abc123/media/carbon-x.json"]


def test_fixup_for_a_missing_file_aborts(tmp_path):
    out = write_out(tmp_path, patches=[("nope.sub", (
        "file: abc123/nothing.html\nold: a\nnew: b\n"))])
    with pytest.raises(SystemExit, match="no such raw file to patch: abc123/nothing.html"):
        load_fixups(out)
