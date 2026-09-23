"""How far a lossy encode is from its gif, frame by frame.

usage: python quality.py GIF ENCODED [SNAPSHOT_DIR]

Both files are decoded to rgb24 by ffmpeg (1 ms time base) and paired by
display time: every frame of the encode is compared with the gif frame
on screen at the moment it starts. Formats that merge repeated frames
are compared on what is shown, and an encode whose frame rate was
capped (fpscap.py) is judged on the frames it keeps -- the frames it
dropped by design are not counted as errors. Prints one JSON object:

  psnr        over all compared pixels (dB; inf when identical)
  psnr_min    the worst single frame
  max_err     the largest per-channel error anywhere
  visible     fraction of pixels whose largest channel error is > 16
  worst_frame index of the encode's frame with the lowest PSNR

With SNAPSHOT_DIR, that worst frame is saved as ref.png, enc.png and
diff.png (the absolute error, amplified 8x), for looking at text.
"""
import itertools
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np


def webp_durations(path):
    """Each frame's stored duration (ms) in an animated WebP, from
    webpmux. ffmpeg's WebP decoder plays durations of 10 ms or less as
    100 ms, as browsers do, so its timestamps are not what the file
    says."""
    run = subprocess.run(["webpmux", "-info", str(path)],
                         capture_output=True, text=True, check=True)
    out = []
    for line in run.stdout.splitlines():
        f = line.split()
        if f and f[0].endswith(":") and f[0][:-1].isdigit():
            out.append(int(f[6]))
    return out


def probe(path):
    """(width, height, [pts in ms]) of the decoded frames."""
    run = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v",
         "-fps_mode", "passthrough", "-enc_time_base", "1:1000",
         "-pix_fmt", "rgb24", "-f", "framemd5", "-"],
        capture_output=True, text=True, check=True)
    tb, pts, size = None, [], None
    for line in run.stdout.splitlines():
        if line.startswith("#tb 0:"):
            tb = Fraction(line.split(":", 1)[1].strip())
        elif line.startswith("#dimensions 0:"):
            size = tuple(int(x) for x in line.split(":", 1)[1].split("x"))
        elif line and not line.startswith("#"):
            pts.append(float(int(line.split(",")[2]) * tb * 1000))
    if str(path).endswith(".webp"):
        d = webp_durations(path)
        if len(d) == len(pts):
            pts = [0.0, *map(float, itertools.accumulate(d[:-1]))]
    return size[0], size[1], pts


def frames(path, w, h):
    proc = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v",
         "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo",
         "-"], stdout=subprocess.PIPE)
    n = w * h * 3
    while True:
        buf = proc.stdout.read(n)
        if len(buf) < n:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    proc.wait()


def save(arr, path):
    from PIL import Image
    Image.fromarray(arr).save(path)


def main():
    gif, enc = sys.argv[1], sys.argv[2]
    snap = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    w, h, ref_pts = probe(gif)
    w2, h2, enc_pts = probe(enc)
    if not (0 <= w2 - w <= 1 and 0 <= h2 - h <= 1):
        sys.exit(f"size differs: {w}x{h} vs {w2}x{h2}")
    gif_frames = frames(gif, w, h)
    cur, nxt = next(gif_frames), next(gif_frames, None)
    j = 0
    sse = 0.0
    count = 0
    max_err = 0
    visible = 0
    worst = (math.inf, -1, None, None)
    # a 4:2:0 encode may carry a pixel of padding to even dimensions
    enc_frames = (f[:h, :w] for f in frames(enc, w2, h2))
    for i, (t, got) in enumerate(zip(enc_pts, enc_frames)):
        # advance to the gif frame on screen at time t
        while nxt is not None and j + 1 < len(ref_pts) and ref_pts[j + 1] <= t + 0.5:
            cur, nxt, j = nxt, next(gif_frames, None), j + 1
        d = np.abs(cur.astype(np.int16) - got.astype(np.int16))
        mse = float((d.astype(np.float64) ** 2).mean())
        sse += mse
        count += 1
        max_err = max(max_err, int(d.max()))
        visible += int((d.max(axis=2) > 16).sum())
        p = math.inf if mse == 0 else 10 * math.log10(255 ** 2 / mse)
        if p < worst[0]:
            worst = (p, i, cur.copy(), got.copy())
    mse = sse / count
    out = {
        "psnr": round(10 * math.log10(255 ** 2 / mse), 2) if mse else math.inf,
        "psnr_min": round(worst[0], 2),
        "max_err": max_err,
        "visible": round(visible / (count * w * h), 6),
        "worst_frame": worst[1],
    }
    if snap and worst[2] is not None:
        snap.mkdir(parents=True, exist_ok=True)
        save(worst[2], snap / "ref.png")
        save(worst[3], snap / "enc.png")
        diff = np.abs(worst[2].astype(np.int16) - worst[3].astype(np.int16))
        save(np.clip(diff * 8, 0, 255).astype(np.uint8), snap / "diff.png")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
