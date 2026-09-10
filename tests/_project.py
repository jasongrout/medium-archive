"""A test project laid out the way a checkout of this one is.

The tool names its four directories one option at a time -- `--archive`,
`--site-inputs`, `--out`, `--image-cache` -- and none of them has to sit
beside any other. A fixture still wants one `tmp_path` to hang them all
off, so these helpers put them where the defaults would find them from
the project root, and `build` runs an exporter over that layout.
"""

from pathlib import Path


def archive_dir(root: Path) -> Path:
    return root / "archive"


def site_inputs(root: Path) -> Path:
    return root / "site"


def image_cache(root: Path) -> Path:
    return root / ".image-cache"


def site_dir(root: Path, generator: str) -> Path:
    return root / f"site-{generator}"


def build(module, root: Path, **kw) -> Path:
    """One exporter over that project. `out` defaults to the
    site-<generator>/ the command line would use; everything else
    (clean=...) is passed through."""
    generator = module.__name__.rsplit(".", 1)[-1]
    return module.build_site(archive_dir(root),
                             kw.pop("out", site_dir(root, generator)),
                             site_inputs(root), image_cache(root), **kw)
