"""Inventory the archive's gifs: one TSV row per file.

usage (from the repository root):
    find archive/raw -iname '*.gif' | sort > /tmp/gifs.txt
    pixi run --manifest-path docs/gif-intermediates/pixi.toml \
        python docs/gif-intermediates/inventory.py /tmp/gifs.txt > inventory.tsv

Columns: see HEADER. Durations are Pillow's per-frame "duration" (ms,
the gif's centisecond delay x 10); short_frames counts delays under
20 ms, which browsers play as 100 ms. transparent_first / transparent_any
ask whether a composited frame has any pixel with alpha < 255 (the gif
transparency index alone says nothing: it also means "unchanged").
"""
import hashlib
import os
import sys

from PIL import Image

HEADER = ("bytes\tframes\tsize\tduration_ms\tshort_frames\tloop"
          "\ttransparent_first\ttransparent_any\tduplicate\tsha256_12\tpath")


def alpha(im):
    return im.convert("RGBA").getchannel("A").getextrema()[0] < 255


def main():
    print(HEADER)
    seen = {}
    for p in open(sys.argv[1]).read().split("\n"):
        if not p:
            continue
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:12]
        dup = h in seen
        seen.setdefault(h, p)
        try:
            im = Image.open(p)
            n = getattr(im, "n_frames", 1)
            w, hh = im.size
            durs = []
            for i in range(n):
                im.seek(i)
                durs.append(im.info.get("duration", 0))
            loop = im.info.get("loop", "none")
            im.seek(0)
            tr0 = tra = alpha(im)
            for i in range(n):
                if tra:
                    break
                im.seek(i)
                tra = alpha(im)
        except Exception:
            n = w = hh = -1
            durs = []
            loop = tr0 = tra = "err"
        short = sum(1 for d in durs if d < 20)
        print(f"{os.path.getsize(p)}\t{n}\t{w}x{hh}\t{sum(durs)}\t{short}"
              f"\t{loop}\t{tr0}\t{tra}\t{int(dup)}\t{h}\t{p}")


if __name__ == "__main__":
    main()
