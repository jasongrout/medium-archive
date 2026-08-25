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
      }
    }

`drop` removes a tag everywhere; `rename` replaces one with another, so
consolidating variants is renaming them all to the common tag. Convert
applies the map as each post's front matter is written -- posts.json and
every derived site inherit the cleaned tags -- and de-duplicates, so a
post tagged with two variants ends up with the target once.

The config fails loudly, like a fixup that no longer applies: unknown
top-level keys, malformed entries, a tag both dropped and renamed, a
rename to a dropped tag, and rename chains (a target that is itself
renamed) all abort at load; an entry that matches no post's tags aborts
a full convert run, so stale entries cannot rot silently. `stats --tags`
lists every tag with its post count, as a worklist for curating the file.
"""

import json
import sys
from pathlib import Path


class TagMap:
    """A loaded tags.json: apply() cleans one post's tag list, and the
    entries that matched no post over a whole run are reported by
    unused() so convert can fail loudly on stale config."""

    def __init__(self, drop: set, rename: dict, path: Path):
        self.drop = drop
        self.rename = rename
        self.path = path
        self._used = set()

    def apply(self, tags) -> list:
        out = []
        for tag in tags:
            if tag in self.drop:
                self._used.add(tag)
                continue
            if tag in self.rename:
                self._used.add(tag)
                tag = self.rename[tag]
            out.append(tag)
        return sorted(set(out))

    def unused(self) -> list:
        return sorted((self.drop | set(self.rename)) - self._used)


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
    unknown = set(config) - {"drop", "rename"}
    if unknown:
        _fail(path, f"unknown key(s) {sorted(unknown)}; only 'drop' and "
                    "'rename' are understood")

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
    return TagMap(drop, rename, path)
