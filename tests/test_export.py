"""iter_export_files zip/directory layouts and the import-export step."""

import argparse
import json
import zipfile
from pathlib import Path

from medium_archive.export import cmd_import_export, iter_export_files

POST = """<html><head><title>Hello</title></head><body>
<footer><a class="p-canonical" href="https://blog.example.com/hello-0123456789ab">Canonical</a>
<time class="dt-published" datetime="2020-01-02T03:04:05Z">2020</time></footer>
</body></html>"""


def make_zip(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, POST)
    return path


def names_of(path: Path) -> list[str]:
    return [name for name, _ in iter_export_files(path)]


def test_full_export_zip_only_reads_posts(tmp_path):
    z = make_zip(tmp_path / "export.zip",
                 ["posts/2020-01-02_Hello--0123456789ab.html",
                  "profile/profile.html", "bookmarks/bookmarks-0001.html"])
    assert names_of(z) == ["2020-01-02_Hello--0123456789ab.html"]


def test_zip_of_posts_folder(tmp_path):
    z = make_zip(tmp_path / "posts.zip", ["posts/2020-01-02_Hello--0123456789ab.html"])
    assert names_of(z) == ["2020-01-02_Hello--0123456789ab.html"]


def test_zip_of_post_files_at_top_level(tmp_path):
    z = make_zip(tmp_path / "posts.zip",
                 ["2020-01-02_Hello--0123456789ab.html", "2021-05-06_Again--ba9876543210.html"])
    assert names_of(z) == ["2020-01-02_Hello--0123456789ab.html",
                           "2021-05-06_Again--ba9876543210.html"]


def test_zip_of_renamed_posts_folder(tmp_path):
    z = make_zip(tmp_path / "posts.zip", ["posts 2/2020-01-02_Hello--0123456789ab.html"])
    assert names_of(z) == ["2020-01-02_Hello--0123456789ab.html"]


def test_zip_macos_junk_is_ignored(tmp_path):
    z = make_zip(tmp_path / "posts.zip",
                 ["posts/2020-01-02_Hello--0123456789ab.html",
                  "__MACOSX/posts/._2020-01-02_Hello--0123456789ab.html",
                  "posts/._stray.html"])
    assert names_of(z) == ["2020-01-02_Hello--0123456789ab.html"]


def test_directory_of_post_files(tmp_path):
    (tmp_path / "2020-01-02_Hello--0123456789ab.html").write_text(POST, encoding="utf-8")
    assert names_of(tmp_path) == ["2020-01-02_Hello--0123456789ab.html"]


def test_unzipped_export_directory(tmp_path):
    (tmp_path / "posts").mkdir()
    (tmp_path / "posts" / "2020-01-02_Hello--0123456789ab.html").write_text(POST, encoding="utf-8")
    (tmp_path / "profile.html").write_text("<html></html>", encoding="utf-8")
    assert names_of(tmp_path) == ["2020-01-02_Hello--0123456789ab.html"]


def test_import_posts_only_zip(tmp_path, capsys):
    z = make_zip(tmp_path / "posts.zip", ["2020-01-02_Hello--0123456789ab.html"])
    out = tmp_path / "archive"
    args = argparse.Namespace(out=out, export_path=z, all=True, drafts=False)
    cmd_import_export(args)
    assert (out / "raw" / "0123456789ab" / "export.html").read_text() == POST
    index = json.loads((out / "raw" / "index.json").read_text())
    entry = index["https://blog.example.com/hello-0123456789ab"]
    assert entry["medium_id"] == "0123456789ab" and entry["in_export"]
    assert "1 posts" in capsys.readouterr().err
