"""cmd_stats: the provenance section (discovery, recovered sources, body
source, posts gone from Medium)."""

import json
from types import SimpleNamespace

from medium_archive import stats as statsmod

A = "https://blog.example.com/alpha-111122223333"
B = "https://blog.example.com/beta-444455556666"
C = "https://blog.example.com/old-ghost-post/"
GONE = "https://blog.example.com/gone-post-0123456789ab"


def write_post(out, rel, front):
    d = out / rel
    d.mkdir(parents=True)
    (d / "index.md").write_text(
        "---\n" + json.dumps(front) + "\n---\n\nSome body text.\n", encoding="utf-8")


def build_archive(out):
    manifest = {
        A: {"dir": "posts/2020-01-01-alpha", "title": "Alpha", "authors": [{"name": "Ann", "url": None}],
            "date": "2020-01-01T00:00:00Z", "tags": ["t"], "images": [],
            "body_source": "export"},
        B: {"dir": "posts/2021-02-02-beta", "title": "Beta", "authors": [{"name": "Ann", "url": None}],
            "date": "2021-02-02T00:00:00Z", "tags": [], "images": [],
            "body_source": "page"},
        C: {"dir": "posts/2015-03-03-old-ghost-post", "title": "Old", "authors": [{"name": "Bo", "url": None}],
            "date": "2015-03-03T00:00:00Z", "tags": [], "images": [],
            "body_source": "ghost"},
    }
    (out / "posts.json").write_text(json.dumps(manifest))
    for p in manifest.values():
        write_post(out, p["dir"], p)
    raw = out / "raw"
    raw.mkdir()
    (raw / "index.json").write_text(json.dumps({
        A: {"medium_id": "111122223333", "found_via": "feed", "in_feed": True,
            "in_export": True},
        B: {"medium_id": "444455556666", "found_via": "wayback", "in_feed": False,
            "in_export": True, "draft": True, "in_ghost": True},
        C: {"medium_id": "ghost-old-ghost-post", "found_via": "ghost-wayback",
            "in_feed": False},
    }))
    (raw / "missing.json").write_text(json.dumps({
        GONE: {"status": 404, "found_via": "wayback",
               "wayback_url": f"https://web.archive.org/web/*/{GONE}"},
    }))


def run_stats(out, capsys):
    statsmod.cmd_stats(SimpleNamespace(out=out, base=None, top=15))
    return capsys.readouterr().out


def test_provenance_section(tmp_path, capsys):
    build_archive(tmp_path)
    text = run_stats(tmp_path, capsys)
    assert "Provenance:" in text
    assert "discovered via: feed: 1, wayback: 1, ghost-wayback: 1" in text
    assert "(wayback:" in text and "(ghost-wayback:" in text
    assert ("also sourced: 1 in the RSS feed, 2 in an account export (drafts: 1), "
            "1 with a Ghost capture attached") in text
    assert "body converted from: export: 1, page: 1, ghost: 1" in text
    assert "gone from Medium: 1" in text


def test_provenance_without_raw_index(tmp_path, capsys):
    # stats still works on a posts/ tree copied without raw/ -- only the
    # body-source line remains
    build_archive(tmp_path)
    (tmp_path / "raw" / "index.json").unlink()
    (tmp_path / "raw" / "missing.json").unlink()
    text = run_stats(tmp_path, capsys)
    assert "body converted from: export: 1, page: 1, ghost: 1" in text
    assert "discovered via" not in text
    assert "gone from Medium" not in text
