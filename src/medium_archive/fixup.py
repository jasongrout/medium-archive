"""Reproducible hand-fixes for authored defects in the raw sources.

Unified patches placed in <out>/fixups/*.patch are applied to the
in-memory text of raw files before conversion or comparison, so a broken
href in a Ghost capture or a mangled paragraph in an account export can
be corrected without ever editing the archived bytes. Each file diff's
target path is matched by its last two components (<medium_id>/<name>),
so patches generated with any a/ b/ prefix convention work.

A hunk that no longer applies aborts the run: a silently skipped fixup
would defeat the point of keeping them reproducible.
"""

import re
import sys
from pathlib import Path

HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _key(path: str) -> str:
    """<medium_id>/<name> from a patch header path, any prefix convention."""
    return "/".join(path.strip().split("\t")[0].split("/")[-2:])


def load_fixups(out_dir: Path) -> dict:
    """Parse every <out>/fixups/*.patch into {'<medium_id>/<name>':
    [(start_line, old_lines, new_lines), ...]}, in file-name order."""
    fixups = {}
    fix_dir = out_dir / "fixups"
    for patch in sorted(fix_dir.glob("*.patch")) if fix_dir.is_dir() else []:
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
                fixups.setdefault(target, []).append(hunk)
            # anything else (---, diff --git, index, # comments) is header
    return fixups


def _apply(text: str, hunks: list, label: str) -> str:
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


def read_raw(path: Path, fixups: dict = None) -> str:
    """The raw file's text with any fixup hunks applied."""
    text = path.read_text(encoding="utf-8")
    key = f"{path.parent.name}/{path.name}"
    if fixups and key in fixups:
        text = _apply(text, fixups[key], key)
    return text
