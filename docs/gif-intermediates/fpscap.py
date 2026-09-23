"""Cap an animation's frame rate without moving any frame it keeps.

usage: python fpscap.py IN.gif FILTER_SCRIPT [MIN_MS]
       python fpscap.py --gif IN.gif OUT.gif [MIN_MS]

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

With --gif, the same frames are kept in a gif instead, for a gif kept
because no encode undercuts it. Dropping a frame from a gif breaks the
partial frames after it, and gifsicle cannot unoptimize a gif with
per-frame color tables ("GIF too complex to unoptimize"), so each kept
frame is composited by Pillow and written whole with a palette of
exactly its own colors, its delay extended over the frames dropped
after it; gifsicle -O3 then re-optimizes. That is exact only when no
composited frame has more than 256 colors, so a gif that does is
refused (exit status 3) rather than quantized.

Prints "kept/total" frames.
"""
import itertools
import subprocess
import tempfile

import numpy as np
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


class TooManyColors(Exception):
    pass


class KeptFrames:
    """The kept frames as P images, each with a palette of exactly its
    own colors; iterable more than once, as Pillow's writers need."""

    def __init__(self, im, keep):
        self.im, self.keep = im, keep

    def __iter__(self):
        for i in self.keep:
            self.im.seek(i)
            rgb = np.asarray(self.im.convert("RGB"))
            flat = rgb.reshape(-1, 3).astype(np.uint32)
            key = flat[:, 0] << 16 | flat[:, 1] << 8 | flat[:, 2]
            colors, index = np.unique(key, return_inverse=True)
            if len(colors) > 256:
                raise TooManyColors(f"frame {i}: {len(colors)} colors")
            p = Image.fromarray(index.reshape(rgb.shape[:2]).astype(np.uint8), "P")
            pal = np.stack([colors >> 16, colors >> 8 & 255, colors & 255], 1)
            p.putpalette(pal.astype(np.uint8).ravel().tolist())
            yield p


def capped_gif(im, dst, delays, keep):
    starts = [0, *itertools.accumulate(delays)]
    ends = keep[1:] + [len(delays)]
    durations = [starts[b] - starts[a] for a, b in zip(keep, ends)]
    first = next(iter(KeptFrames(im, keep[:1])))
    with tempfile.NamedTemporaryFile(suffix=".gif") as tmp:
        first.save(tmp.name, save_all=True,
                   append_images=KeptFrames(im, keep[1:]),
                   duration=durations, loop=0, optimize=False)
        subprocess.run(["gifsicle", "--no-conserve-memory", "-O3", tmp.name,
                        "-o", dst], check=True)


def main():
    as_gif = sys.argv[1] == "--gif"
    args = sys.argv[2:] if as_gif else sys.argv[1:]
    src, out = args[0], args[1]
    min_ms = float(args[2]) if len(args) > 2 else 29.5
    im = Image.open(src)
    delays = []
    for i in range(im.n_frames):
        im.seek(i)
        delays.append(im.info.get("duration", 0))
    keep = kept_frames(delays, min_ms)
    print(f"{len(keep)}/{len(delays)}")
    if as_gif:
        try:
            capped_gif(im, out, delays, keep)
        except TooManyColors as e:
            print(f"not exact as a gif: {e}", file=sys.stderr)
            sys.exit(3)
        return
    script = out
    terms = balanced([f"between(n\\,{a}\\,{b})" for a, b in ranges(keep)])
    with open(script, "w") as f:
        f.write(f"select='{terms}'\n")


if __name__ == "__main__":
    main()
