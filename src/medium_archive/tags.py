"""Hand-curated tag cleanup, applied by convert.

Medium tags are chosen for discovery on medium.com, so an archived
publication inherits tags that are meaningless on a standalone site (a
Jupyter blog where two-thirds of the posts are tagged "jupyter") and
fragmented variants of one concept ("notebook" / "notebooks" /
"jupyter-notebook"). An optional hand-written <out>/tags.json cleans
them up reproducibly -- like fixups and site.json, it is an input that
survives regeneration, while raw/ keeps the original tags untouched:

    {
      "drop": ["jupyter", "open-source"],
      "rename": {
        "notebook": "jupyter-notebook",
        "notebooks": "jupyter-notebook"
      },
      "add": {
        "release-of-ipython-5-0": ["ipython", "releases"]
      }
    }

`drop` removes a tag everywhere; `rename` replaces one with another, so
consolidating variants is renaming them all to the common tag. Convert
applies the map as each post's front matter is written -- posts.json and
every derived site inherit the cleaned tags -- and de-duplicates, so a
post tagged with two variants ends up with the target once.

`add` puts tags on specific posts, keyed by the post's slug: Medium tags
were chosen for medium.com discovery, so a post plainly about a topic
the archive tracks often never carried the tag (early Ghost-era posts
carried none at all). Slugs are not guaranteed unique; an entry applies
to every post with that slug. Added tags must be final names -- adding
a renamed tag aborts at load, so the cleanup stays one pass. Adding a
dropped tag is allowed, and is how an over-applied tag is split: drop
clears the inherited uses everywhere, and add re-asserts the tag on the
posts that genuinely deserve it (adds run after drops and renames).

The config fails loudly, like a fixup that no longer applies: unknown
top-level keys, malformed entries, a tag both dropped and renamed, a
rename to a dropped tag, and rename chains (a target that is itself
renamed) all abort at load; an entry that changes no post aborts a full
convert run -- a drop/rename matching no post's tags, or an add whose
every matching post already carries the tag -- so stale entries cannot
rot silently. `stats --tags` lists every tag with its post count, as a
worklist for curating the file.
"""

import json
import sys
from pathlib import Path


class TagMap:
    """A loaded tags.json: apply() cleans one post's tag list, and the
    entries that changed no post over a whole run are reported by
    unused() so convert can fail loudly on stale config."""

    def __init__(self, drop: set, rename: dict, add: dict, path: Path):
        self.drop = drop
        self.rename = rename
        self.add = add                        # slug -> [tags to ensure]
        self.path = path
        self._used = set()      # drop/rename tags and (slug, tag) add pairs

    def apply(self, tags, slug: str = None) -> list:
        out = []
        for tag in tags:
            if tag in self.drop:
                self._used.add(tag)
                continue
            if tag in self.rename:
                self._used.add(tag)
                tag = self.rename[tag]
            out.append(tag)
        result = set(out)
        for tag in self.add.get(slug, ()):
            if tag not in result:             # already-carried tags don't
                self._used.add((slug, tag))   # count the entry as used
                result.add(tag)
        return sorted(result)

    def unused(self) -> list:
        stale = (self.drop | set(self.rename)) - self._used
        stale |= {f"{slug}: +{tag}" for slug, tags in self.add.items()
                  for tag in tags if (slug, tag) not in self._used}
        return sorted(stale)


def _fail(path: Path, message: str):
    sys.exit(f"{path}: {message}")


def _check_tag(path: Path, tag, where: str) -> str:
    if not isinstance(tag, str) or not tag.strip():
        _fail(path, f"{where}: tags must be non-empty strings, got {tag!r}")
    if tag != tag.strip():
        _fail(path, f"{where}: {tag!r} has leading/trailing whitespace")
    return tag


def load_tag_map(out: Path) -> TagMap | None:
    """The parsed <out>/tags.json, or None when the archive has none.
    Malformed or self-contradictory config aborts: a config error that
    silently no-opped would defeat the point of keeping the cleanup
    reproducible."""
    path = out / "tags.json"
    if not path.exists():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(path, f"not valid JSON: {e}")
    if not isinstance(config, dict):
        _fail(path, "top level must be an object with 'drop' and/or 'rename'")
    unknown = set(config) - {"drop", "rename", "add"}
    if unknown:
        _fail(path, f"unknown key(s) {sorted(unknown)}; only 'drop', "
                    "'rename' and 'add' are understood")

    drop_list = config.get("drop", [])
    if not isinstance(drop_list, list):
        _fail(path, "'drop' must be a list of tags")
    drop = set()
    for tag in drop_list:
        _check_tag(path, tag, "drop")
        if tag in drop:
            _fail(path, f"drop: {tag!r} listed twice")
        drop.add(tag)

    rename = config.get("rename", {})
    if not isinstance(rename, dict):
        _fail(path, "'rename' must be an object of {old: new} entries")
    for old, new in rename.items():
        _check_tag(path, old, "rename")
        _check_tag(path, new, f"rename {old!r}")
        if old == new:
            _fail(path, f"rename: {old!r} renamed to itself")
        if old in drop:
            _fail(path, f"{old!r} is both dropped and renamed")
        if new in drop:
            _fail(path, f"rename: {old!r} -> {new!r}, but {new!r} is "
                        "dropped; drop the source tag directly instead")
        if new in rename:
            _fail(path, f"rename: {old!r} -> {new!r}, but {new!r} is itself "
                        f"renamed to {rename[new]!r}; rename {old!r} to the "
                        "final tag directly")

    add = config.get("add", {})
    if not isinstance(add, dict):
        _fail(path, "'add' must be an object of {slug: [tags]} entries")
    for slug, tags in add.items():
        if not isinstance(slug, str) or not slug.strip():
            _fail(path, f"add: slugs must be non-empty strings, got {slug!r}")
        if slug != slug.strip():
            _fail(path, f"add: {slug!r} has leading/trailing whitespace")
        if not isinstance(tags, list) or not tags:
            _fail(path, f"add {slug!r}: must be a non-empty list of tags")
        seen = set()
        for tag in tags:
            _check_tag(path, tag, f"add {slug!r}")
            if tag in seen:
                _fail(path, f"add {slug!r}: {tag!r} listed twice")
            seen.add(tag)
            if tag in rename:
                _fail(path, f"add {slug!r}: {tag!r} is renamed to "
                            f"{rename[tag]!r}; add the final tag instead")
    return TagMap(drop, rename, add, path)
