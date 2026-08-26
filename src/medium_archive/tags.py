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
      "imply": {"jupytercon": ["events"]},
      "add": {
        "release-of-ipython-5-0": ["ipython", "releases"]
      },
      "remove": {
        "jupyter-community-call-june-2025": ["jupyterlab"]
      }
    }

`drop` removes a tag everywhere; `rename` replaces one with another, so
consolidating variants is renaming them all to the common tag. Convert
applies the map as each post's front matter is written -- posts.json and
every derived site inherit the cleaned tags -- and de-duplicates, so a
post tagged with two variants ends up with the target once.

`imply` states that one tag entails another everywhere it appears: every
post tagged "jupytercon" is also an "events" post, without listing them
one by one. Implications are drawn on the cleaned tags -- after renames
and after `add` below, so a tag put on one post entails just as much as
an inherited one -- so both sides must be final names, and they do not
chain (an implied tag that itself implies something aborts at load, like
a rename chain).

`add` and `remove` adjust specific posts, keyed by the post's slug.
Medium tags were chosen for medium.com discovery, so a post plainly
about a topic the archive tracks often never carried the tag (early
Ghost-era posts carried none at all), while a post that merely mentions
a project often carries its tag. Slugs are not guaranteed unique; an
entry applies to every post with that slug. Both sections must name
final tags -- naming a renamed tag aborts at load, so the cleanup stays
one pass -- and neither may name a dropped tag in `remove` (drop already
removed it) though `add` may, which is one way to split an over-applied
tag: drop clears the inherited uses everywhere and add re-asserts the
tag on the posts that genuinely deserve it. `remove` is the other way
round, for a tag whose uses are mostly right: it subtracts the handful
of posts the tag does not describe. The passes run in order -- drop,
rename, add, imply, remove -- so a remove has the last word, even over an
implication, and a post that both adds and removes one tag aborts at
load rather than resolving the contradiction silently.

The config fails loudly, like a fixup that no longer applies: unknown
top-level keys, malformed entries, a tag both dropped and renamed, a
rename to a dropped tag, and rename chains (a target that is itself
renamed) all abort at load; an entry that changes no post aborts a full
convert run -- a drop/rename matching no post's tags, an implication no
post's tags ever trigger, an add whose every matching post already
carries the tag, or a remove whose every matching post never had it --
so stale entries cannot rot silently. `stats --tags` lists every tag
with its post count, as a worklist for curating the file.
"""

import json
import sys
from pathlib import Path


class TagMap:
    """A loaded tags.json: apply() cleans one post's tag list, and the
    entries that changed no post over a whole run are reported by
    unused() so convert can fail loudly on stale config."""

    def __init__(self, drop: set, rename: dict, imply: dict, add: dict,
                 remove: dict, path: Path):
        self.drop = drop
        self.rename = rename
        self.imply = imply                    # tag -> [tags it entails]
        self.add = add                        # slug -> [tags to ensure]
        self.remove = remove                  # slug -> [tags to subtract]
        self.path = path
        # drop/rename tags, (tag, tag) imply pairs, (slug, tag) add/remove
        self._used = set()

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
        for tag in sorted(result):            # after add, so an added tag
            for implied in self.imply.get(tag, ()):   # entails too
                if implied not in result:     # already-carried tags don't
                    self._used.add((tag, implied))   # count as used
                    result.add(implied)
        for tag in self.remove.get(slug, ()):
            if tag in result:                 # a tag the post never had
                self._used.add((slug, tag))   # doesn't count either
                result.discard(tag)
        return sorted(result)

    def unused(self) -> list:
        stale = (self.drop | set(self.rename)) - self._used
        stale |= {f"{tag} => {target}" for tag, targets in self.imply.items()
                  for target in targets if (tag, target) not in self._used}
        stale |= {f"{slug}: +{tag}" for slug, tags in self.add.items()
                  for tag in tags if (slug, tag) not in self._used}
        stale |= {f"{slug}: -{tag}" for slug, tags in self.remove.items()
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


def _per_slug(path: Path, config: dict, key: str, rename: dict) -> dict:
    """The parsed 'add' or 'remove' section: {slug: [final tags]}."""
    section = config.get(key, {})
    if not isinstance(section, dict):
        _fail(path, f"'{key}' must be an object of {{slug: [tags]}} entries")
    for slug, tags in section.items():
        if not isinstance(slug, str) or not slug.strip():
            _fail(path, f"{key}: slugs must be non-empty strings, "
                        f"got {slug!r}")
        if slug != slug.strip():
            _fail(path, f"{key}: {slug!r} has leading/trailing whitespace")
        if not isinstance(tags, list) or not tags:
            _fail(path, f"{key} {slug!r}: must be a non-empty list of tags")
        seen = set()
        for tag in tags:
            _check_tag(path, tag, f"{key} {slug!r}")
            if tag in seen:
                _fail(path, f"{key} {slug!r}: {tag!r} listed twice")
            seen.add(tag)
            if tag in rename:
                _fail(path, f"{key} {slug!r}: {tag!r} is renamed to "
                            f"{rename[tag]!r}; {key} the final tag instead")
    return section


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
    known = {"drop", "rename", "imply", "add", "remove"}
    unknown = set(config) - known
    if unknown:
        _fail(path, f"unknown key(s) {sorted(unknown)}; only "
                    f"{', '.join(repr(k) for k in sorted(known))} "
                    "are understood")

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

    imply = config.get("imply", {})
    if not isinstance(imply, dict):
        _fail(path, "'imply' must be an object of {tag: [tags]} entries")
    for tag, implied in imply.items():
        _check_tag(path, tag, "imply")
        if not isinstance(implied, list) or not implied:
            _fail(path, f"imply {tag!r}: must be a non-empty list of tags")
        if tag in drop:
            _fail(path, f"imply: {tag!r} is dropped, so it can never imply "
                        "anything")
        if tag in rename:
            _fail(path, f"imply: {tag!r} is renamed to {rename[tag]!r}; "
                        "state the implication on the final tag instead")
        seen = set()
        for target in implied:
            _check_tag(path, target, f"imply {tag!r}")
            if target in seen:
                _fail(path, f"imply {tag!r}: {target!r} listed twice")
            seen.add(target)
            if target == tag:
                _fail(path, f"imply: {tag!r} implies itself")
            if target in drop:
                _fail(path, f"imply: {tag!r} -> {target!r}, but {target!r} "
                            "is dropped")
            if target in rename:
                _fail(path, f"imply: {tag!r} -> {target!r}, but {target!r} "
                            f"is renamed to {rename[target]!r}; imply the "
                            "final tag instead")
            if target in imply:
                _fail(path, f"imply: {tag!r} -> {target!r}, but {target!r} "
                            "itself implies "
                            f"{imply[target]!r}; implications do not chain, "
                            "so state every implied tag directly")

    add = _per_slug(path, config, "add", rename)
    remove = _per_slug(path, config, "remove", rename)
    for slug, tags in remove.items():
        for tag in tags:
            if tag in drop:
                _fail(path, f"remove {slug!r}: {tag!r} is already dropped "
                            "everywhere")
            if tag in add.get(slug, ()):
                _fail(path, f"{slug!r}: {tag!r} is both added and removed")
    return TagMap(drop, rename, imply, add, remove, path)
