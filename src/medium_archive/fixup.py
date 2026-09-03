"""Reproducible hand-fixes for authored defects in the raw sources.

Two formats, applied to the in-memory text of raw files before conversion
or comparison, so a broken href in a Ghost capture or a mangled paragraph
in an account export can be corrected without ever editing the archived
bytes:

* <out>/fixups/*.sub -- substitutions, the format of choice: raw HTML
  files are often a single enormous line, so a unified diff of even a
  one-character fix embeds the whole line twice and cannot be reviewed.
  A substitution shows exactly what changes. '#' lines are comments:

      # why this fix exists
      file: <medium_id>/<name>          (or <medium_id>/media/<name>)
      count: 2
      old: one sentence.The next
      new: one sentence. The next

  `file:` names the target (sticky for the pairs that follow); `old:` /
  `new:` is one literal, single-line substitution (`old-regex:` instead
  of `old:` makes it a Python regex, with `new:` its replacement
  template); `count:` (optional, default 1) is the exact number of
  occurrences expected -- applying to more or fewer aborts the run.

* <out>/fixups/*.patch -- unified patches, for structural edits that
  substitutions cannot express. Each file diff's target path is matched
  by its last two components (<medium_id>/<name>), so patches generated
  with any a/ b/ prefix convention work.

Fixup files apply in file-name order. A hunk or substitution that no
longer applies aborts the run, as does a fixup naming a file the
archive does not have: a silently skipped fixup would defeat the point
of keeping them reproducible.
"""

import re
import sys
from pathlib import Path

HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")


SUBDIRS = ("media", "images")      # a post's subdirectories fixups can target


def _key(path: str) -> str:
    """<medium_id>/<name> from a patch header path, any prefix convention
    -- or <medium_id>/media/<name> for a file in one of the post's
    subdirectories (an archived gist, tweet or Carbon snippet)."""
    parts = path.strip().split("\t")[0].split("/")
    n = 3 if len(parts) >= 3 and parts[-2] in SUBDIRS else 2
    return "/".join(parts[-n:])


def raw_key(path: Path) -> str:
    """The fixup key of a raw file: its path under raw/ (see _key)."""
    if path.parent.name in SUBDIRS:
        return f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
    return f"{path.parent.name}/{path.name}"


def _parse_patch(patch: Path, fixups: dict):
    """Append one ('hunks', [(start, old, new), ...]) op per target file."""
    per_target = {}
    target = hunk = None
    need_old = need_new = 0
    for line in patch.read_text(encoding="utf-8").splitlines():
        if need_old or need_new:            # inside a hunk: all lines prefixed
            if line.startswith("\\"):       # "\ No newline at end of file"
                continue
            tag, body = line[:1] or " ", line[1:]
            if tag not in " -+":
                sys.exit(f"fixups: malformed hunk line in {patch}: {line!r}")
            if tag in " -":
                hunk[1].append(body)
                need_old -= 1
            if tag in " +":
                hunk[2].append(body)
                need_new -= 1
            continue
        if line.startswith("+++ "):
            target = _key(line[4:])
            continue
        m = HUNK_RE.match(line)
        if m:
            if target is None:
                sys.exit(f"fixups: hunk before '+++' header in {patch}")
            hunk = (int(m.group(1)), [], [])
            need_old = int(m.group(2) or 1)
            need_new = int(m.group(3) or 1)
            per_target.setdefault(target, []).append(hunk)
        # anything else (---, diff --git, index, # comments) is header
    for target, hunks in per_target.items():
        fixups.setdefault(target, []).append(("hunks", hunks))


def _parse_subs(path: Path, fixups: dict):
    """Append ('sub', kind, pattern, replacement, count) ops."""
    target = None
    count = None
    pending = None                          # (kind, pattern) awaiting new:
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or key not in ("file", "count", "old", "old-regex", "new"):
            sys.exit(f"fixups: malformed line {n} in {path}: {line!r}")
        value = value[1:] if value.startswith(" ") else value
        if pending is None and key == "new":
            sys.exit(f"fixups: 'new' without 'old' at line {n} in {path}")
        if pending is not None and key != "new":
            sys.exit(f"fixups: 'old' without 'new' at line {n} in {path}")
        if key == "file":
            target = value.strip()
        elif key == "count":
            if not value.strip().isdigit():
                sys.exit(f"fixups: bad count at line {n} in {path}: {line!r}")
            count = int(value)
        elif key in ("old", "old-regex"):
            pending = ("regex" if key == "old-regex" else "literal", value)
        else:                               # new
            if target is None:
                sys.exit(f"fixups: substitution before 'file:' in {path}")
            kind, pattern = pending
            fixups.setdefault(target, []).append(
                ("sub", kind, pattern, value, 1 if count is None else count))
            pending = count = None
    if pending is not None:
        sys.exit(f"fixups: 'old' without 'new' at end of {path}")


def load_fixups(out_dir: Path) -> dict:
    """Parse every <out>/fixups/*.patch and *.sub into
    {'<medium_id>/<name>': [op, ...]}, in fixup-file-name order."""
    fixups = {}
    fix_dir = out_dir / "fixups"
    files = sorted([*fix_dir.glob("*.patch"), *fix_dir.glob("*.sub")]) \
        if fix_dir.is_dir() else []
    for f in files:
        (_parse_patch if f.suffix == ".patch" else _parse_subs)(f, fixups)
    # a fixup naming a file the archive does not have would never apply,
    # and a silently unused fixup defeats the point of keeping them
    raw_dir = out_dir / "raw"
    if raw_dir.is_dir():
        missing = [k for k in fixups if not (raw_dir / k).is_file()]
        if missing:
            sys.exit("fixups: no such raw file to patch: " + ", ".join(missing)
                     + " (a target is <medium_id>/<name>, or "
                     "<medium_id>/media/<name> for archived embed media)")
    return fixups


def _apply_hunks(text: str, hunks: list, label: str) -> str:
    lines = text.split("\n")
    offset = 0
    for start, old, new in hunks:
        if not old:                     # pure insertion: after line <start>
            lines[start + offset:start + offset] = new
            offset += len(new)
            continue
        pos = start - 1 + offset
        if lines[pos:pos + len(old)] != old:
            hits = [i for i in range(len(lines) - len(old) + 1)
                    if lines[i:i + len(old)] == old]
            if len(hits) != 1:
                sys.exit(f"fixups: hunk @@ -{start} @@ for {label} "
                         f"{'matches nowhere' if not hits else 'is ambiguous'}; "
                         "the raw file changed since the patch was made")
            pos = hits[0]
        lines[pos:pos + len(old)] = new
        offset += len(new) - len(old)
    return "\n".join(lines)


def _apply_sub(text: str, kind: str, pattern: str, repl: str, count: int,
               label: str) -> str:
    found = len(re.findall(pattern, text)) if kind == "regex" \
        else text.count(pattern)
    if found != count:
        sys.exit(f"fixups: {label}: {pattern!r} matches {found} time(s), "
                 f"expected {count}; the raw file changed since the fixup "
                 "was made")
    return re.sub(pattern, repl, text) if kind == "regex" \
        else text.replace(pattern, repl)


def read_raw(path: Path, fixups: dict = None) -> str:
    """The raw file's text with any fixup operations applied."""
    text = path.read_text(encoding="utf-8")
    key = raw_key(path)
    for op in (fixups or {}).get(key, []):
        if op[0] == "hunks":
            text = _apply_hunks(text, op[1], key)
        else:
            _, kind, pattern, repl, count = op
            text = _apply_sub(text, kind, pattern, repl, count, key)
    return text
