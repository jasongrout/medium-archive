"""Fixup patches: parsing <out>/fixups/*.patch and applying hunks to the
in-memory text of raw files."""

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


def test_pure_insertion(tmp_path):
    inserted = RAW.replace("<p>three</p>\n", "<p>three</p>\n<p>extra</p>\n")
    bare = "\n".join(difflib.unified_diff(
        RAW.split("\n"), inserted.split("\n"),
        "a/abc123/ghost.html", "b/abc123/ghost.html", lineterm="", n=0)) + "\n"
    out = write_out(tmp_path, patches=[("fix.patch", bare)])
    assert read_raw(out / "raw" / "abc123" / "ghost.html", load_fixups(out)) == inserted
