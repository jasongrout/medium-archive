"""Where the pieces of a project live under its root.

    <root>/archive/       the archive: raw/ and the hand-written files
                            beside it (fixups/, tags.json), plus what
                            convert derives from them (posts/, posts.json,
                            redirects.csv)
    <root>/site/          the hand-written site inputs every exporter
                            reads: site.toml and the images it names
    <root>/site-hugo/     one generated site per exporter
    <root>/site-pelican/
    <root>/site-myst/
    <root>/.image-cache/  display copies of oversized images, shared by
                            the exporters
    <root>/SITES.md       what those generated sites are

Only `archive/` and `site/` are worth keeping: everything else under the
root is thrown away and rebuilt from them. Every command takes the root
(`--out`, the working directory by default) and asks this module for the
piece it needs, so the layout is written down once.
"""

from pathlib import Path


def archive_dir(root: Path) -> Path:
    """The archive: raw/, the hand-written files beside it, and what
    convert derives from them. Every step but the exporters works here."""
    return root / "archive"


def site_inputs(root: Path) -> Path:
    """The hand-written site inputs: site.toml, and the images it names
    (avatar, logo, favicon, share image), which it names relative to
    here so the directory moves as one."""
    return root / "site"


def site_config(root: Path) -> Path:
    """What the built sites say about themselves, hand-written and read
    by every exporter: TOML so that each key can carry its own
    documentation (see siteconf)."""
    return site_inputs(root) / "site.toml"


def site_dir(root: Path, generator: str) -> Path:
    """The site one exporter generates, beside the archive rather than
    inside it: it is output, not archive."""
    return root / f"site-{generator}"


def image_cache(root: Path) -> Path:
    """Display copies of oversized images, content-addressed and shared
    by the exporters (see sites.ImagePlacer)."""
    return root / ".image-cache"
