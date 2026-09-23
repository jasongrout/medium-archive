"""Cap an animation's frame rate without moving any frame it keeps.

usage: python fpscap.py IN.gif FILTER_SCRIPT [MIN_MS]

Writes an ffmpeg `select` filter (for `-/vf FILTER_SCRIPT` with
`-fps_mode passthrough`) that drops the frames a reader cannot see
anyway: those inside a burst faster than about 30 frames per second.
A frame is kept when it is the first or the last, when it stays on
screen for at least MIN_MS (default 29.5 ms), or when it starts at
least MIN_MS after the last frame kept; a frame kept for its start
gives way to a following frame that is kept for its length when the
two would be less than MIN_MS apart. So a burst of 10-20 ms frames
is thinned to at most ~34 fps, the frame a burst ends on is always
shown for as long as the gif shows it, and every kept frame starts at
exactly its original time -- a fixed-rate resample (`fps=30`) would
move every frame boundary by up to 17 ms instead.

Prints "kept/total" frames.
"""
import sys

from PIL import Image


def kept_frames(delays, min_ms):
    keep, starts, t = [], [], 0
    by_gap = False       # whether the last kept frame was kept only for its start
    last_i = len(delays) - 1
    for i, d in enumerate(delays):
        pinned = i == 0 or i == last_i or d >= min_ms
        if pinned or t - starts[-1] >= min_ms:
            if pinned and keep and by_gap and t - starts[-1] < min_ms:
                # the burst frame kept before this one would be on screen
                # for less than min_ms: this one, which stays, replaces it
                keep.pop()
                starts.pop()
            keep.append(i)
            starts.append(t)
            by_gap = not pinned
        t += d
    return keep


def ranges(indices):
    out = []
    for i in indices:
        if out and out[-1][1] == i - 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def balanced(terms):
    """terms joined by + as a balanced tree: ffmpeg's expression parser
    recurses on every +, and a flat sum of a few hundred terms fails
    ("Cannot allocate memory"); nested, the depth is log2 of that."""
    if len(terms) == 1:
        return terms[0]
    mid = len(terms) // 2
    return f"({balanced(terms[:mid])}+{balanced(terms[mid:])})"


def main():
    src, script = sys.argv[1], sys.argv[2]
    min_ms = float(sys.argv[3]) if len(sys.argv) > 3 else 29.5
    im = Image.open(src)
    delays = []
    for i in range(im.n_frames):
        im.seek(i)
        delays.append(im.info.get("duration", 0))
    keep = kept_frames(delays, min_ms)
    terms = balanced([f"between(n\\,{a}\\,{b})" for a, b in ranges(keep)])
    with open(script, "w") as f:
        f.write(f"select='{terms}'\n")
    print(f"{len(keep)}/{len(delays)}")


if __name__ == "__main__":
    main()
