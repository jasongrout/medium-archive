"""Encode a gif as APNG or lossless WebP through Pillow, keeping every
frame's delay exactly as the gif stores it.

usage: python pil_encode.py apng|webp IN.gif OUT

The command-line tools each change timing: ffmpeg's APNG muxer rounds
delays (a 25.30 s gif came out 25.66 s), and gif2webp plays delays of
10 ms or less as 100 ms, as browsers do (a 12.9 s gif came out 63.7 s).
Pillow writes the delays it reads.

Frames are handed over one at a time, so a long animation is never
held in memory as a whole: the APNG writer takes an iterable of RGB
frames (see RGBFrames), and the WebP writer seeks the gif itself.
The APNG writer still keeps its (cropped) frames in memory until it
writes the file.
"""
import sys

from PIL import Image


def delays(im):
    out = []
    for i in range(im.n_frames):
        im.seek(i)
        out.append(im.info.get("duration", 0))
    im.seek(0)
    return out


class RGBFrames:
    """The gif's frames from `start` on, as RGB, decoded on demand. An
    iterable rather than a generator: Pillow's PNG writer walks
    append_images twice (once for the frames' modes and sizes, then to
    write them), and a generator would be spent after the first."""

    def __init__(self, im, start):
        self.im, self.start = im, start

    def __iter__(self):
        for i in range(self.start, self.im.n_frames):
            self.im.seek(i)
            yield self.im.convert("RGB")


def main():
    kind, src, dst = sys.argv[1:4]
    im = Image.open(src)
    d = delays(im)
    if kind == "apng":
        # RGB, not the gif's P mode: APNG has one palette per file, and
        # a gif with per-frame palettes would lose colors in it. Fast
        # deflate: this APNG is only cjxl's input.
        first = im.convert("RGB")
        first.save(dst, format="PNG", save_all=True,
                   append_images=RGBFrames(im, 1), duration=d, loop=0,
                   default_image=False, compress_level=1)
    elif kind == "webp":
        im.save(dst, format="WEBP", save_all=True, duration=d, loop=0,
                lossless=True, quality=100, method=6)
    else:
        sys.exit(f"unknown kind {kind}")


if __name__ == "__main__":
    main()
