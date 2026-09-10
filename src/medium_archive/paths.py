"""Where the pieces of a project live, and the defaults that name them.

Four directories, each named by its own option so that none of them has
to sit beside any other:

    --archive DIR       the archive: raw/ and the hand-written files
                          beside it (fixups/, tags.json), plus what
                          convert derives from them (posts/, posts.json,
                          redirects.csv).  Every step reads or writes it
    --site-inputs DIR   the hand-written site inputs every exporter
                          reads: site.toml and the images it names
    --out DIR           the site one exporter generates.  It is written
                          in place, so it can be a checkout of the
                          published site kept in git; `--clean` empties
                          it first, sparing .git/ and what .gitignore
                          ignores
    --image-cache DIR   display copies of oversized images,
                          content-addressed and shared by the exporters
                          and by re-runs (see sites.ImagePlacer)

The defaults below put them where a checkout of this project has them,
so from the project root every step runs without arguments; each
default is relative to the working directory, and every step takes the
option to point elsewhere.

Only the archive and the site inputs are worth keeping: the sites and
the image cache are thrown away and rebuilt from them.
"""

from pathlib import Path

DEFAULT_ARCHIVE = Path("archive")
DEFAULT_SITE_INPUTS = Path("site")
DEFAULT_IMAGE_CACHE = Path(".image-cache")


def default_out(generator: str) -> Path:
    """Where an exporter writes when --out does not say: beside the
    archive as a checkout of this project has it, one directory per
    generator so the three can be built and compared side by side."""
    return Path(f"site-{generator}")


def site_config(inputs: Path) -> Path:
    """What the built sites say about themselves, hand-written and read
    by every exporter: TOML so that each key can carry its own
    documentation (see siteconf). The images it names are named
    relative to it, so the directory moves as one."""
    return inputs / "site.toml"
