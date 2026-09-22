"""Benchmark lossless / near-lossless intermediates for animated gifs.

usage: python bench.py OUTDIR ENCODER[,ENCODER...] GIF [GIF...]

For each (gif, encoder) job: encode (single-threaded, jobs run in
parallel), then decode the result and compare it with the gif on a
timeline of (rgb24 frame hash, display ms), consecutive identical frames
merged -- so formats that merge or split unchanged frames (webp, jxl) are
judged on what is shown and for how long, not on frame count. Appends
one JSON line per job to OUTDIR/results.jsonl.
"""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

FF = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
PT = ["-fps_mode", "passthrough", "-an", "-threads", "1"]

ENCODERS = {
    # lossless GIF re-optimization: the "stay a gif" baseline
    "gifsicle_O3": (".gif", lambda i, o: [
        "gifsicle", "--no-conserve-memory", "-O3", i, "-o", o]),
    "aom_ll_c1": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "1", "-g", "9999", "-row-mt", "0",
        "-crf", "0", "-aom-params", "lossless=1:tune-content=screen",
        "-pix_fmt", "gbrp", o]),
    "aom_ll_c1_noscreen": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "1", "-g", "9999", "-row-mt", "0",
        "-crf", "0", "-aom-params", "lossless=1", "-pix_fmt", "gbrp", o]),
    "aom_ll_c4": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "4", "-g", "9999", "-row-mt", "0",
        "-crf", "0", "-aom-params", "lossless=1:tune-content=screen",
        "-pix_fmt", "gbrp", o]),
    "x264rgb_ll": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libx264rgb", "-qp", "0", "-preset", "placebo", "-g", "9999",
        "-pix_fmt", "rgb24", o]),
    "x265_ll": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libx265", "-preset", "placebo", "-pix_fmt", "gbrp",
        "-x265-params", "lossless=1:keyint=9999:pools=1:frame-threads=1:log-level=error",
        o]),
    "vp9_ll": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libvpx-vp9", "-lossless", "1", "-cpu-used", "0",
        "-g", "9999", "-row-mt", "0", "-pix_fmt", "gbrp", o]),
    "ffv1": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "ffv1", "-level", "3", "-coder", "range_def",
        "-context", "1", "-g", "1", "-slices", "4", "-pix_fmt", "bgr0", o]),
    "webp_ll": (".webp", lambda i, o: [
        "gif2webp", "-quiet", "-m", "6", "-q", "100", i, "-o", o]),
    "webp_ll_min": (".webp", lambda i, o: [
        "gif2webp", "-quiet", "-min_size", "-m", "6", "-q", "100",
        i, "-o", o]),
    # cjxl 0.12 rejects gifs whose partial frames dispose to background
    # ("GIF with dispose-to-0 is not supported"); see the plan's open items
    "jxl_ll_e9": (".jxl", lambda i, o: [
        "cjxl", "--quiet", "-d", "0", "-e", "9", "--num_threads=0", i, o]),
    # near-lossless
    "aom_crf4": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "1", "-g", "9999", "-row-mt", "0",
        "-crf", "4", "-aom-params", "tune-content=screen",
        "-pix_fmt", "gbrp", o]),
    "x264rgb_crf4": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libx264rgb", "-crf", "4", "-preset", "placebo", "-g", "9999",
        "-pix_fmt", "rgb24", o]),
}


def timeline(path):
    """[(hash, ms)] of what is shown, consecutive identical frames merged,
    plus the raw frame count."""
    run = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v",
         "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "framemd5",
         "-"], capture_output=True, text=True)
    tb = None
    rows = []
    for line in run.stdout.splitlines():
        if line.startswith("#tb 0:"):
            tb = Fraction(line.split(":", 1)[1].strip())
        elif line and not line.startswith("#"):
            f = [x.strip() for x in line.split(",")]
            rows.append((int(f[2]), int(f[3]), f[5]))
    if not rows or tb is None:
        return None, 0, run.stderr.strip()[-300:]
    out = []
    for k, (pts, dur, h) in enumerate(rows):
        end = rows[k + 1][0] if k + 1 < len(rows) else pts + dur
        ms = float((end - pts) * tb * 1000)
        if out and out[-1][0] == h:
            out[-1][1] += ms
        else:
            out.append([h, ms])
    return out, len(rows), ""


def compare(ref, got):
    """(pixels_equal, timing_equal, max_abs_ms_diff, total_ms_ref, total_ms_got)"""
    same_px = [h for h, _ in ref] == [h for h, _ in got]
    tr = sum(ms for _, ms in ref)
    tg = sum(ms for _, ms in got)
    if not same_px:
        return False, None, None, tr, tg
    diffs = [abs(a[1] - b[1]) for a, b in zip(ref, got)]
    # the last frame's length is what containers most often lose
    body = diffs[:-1]
    return True, all(d <= 1 for d in body), max(diffs), tr, tg


def psnr(gif, out):
    # KNOWN BROKEN: reported ~25.018 dB for every non-exact encode of the
    # pilot gif, crf 4 and crf 32 alike -- the psnr filter is not pairing
    # frames. Replace before trusting any near-lossless number.
    run = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(out), "-i", str(gif),
         "-lavfi", "[0:v]format=rgb24[a];[1:v]format=rgb24[b];[a][b]psnr",
         "-fps_mode", "passthrough", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"average:(\S+)", run.stderr)
    return m.group(1) if m else None


def decode_seconds(out):
    t = time.perf_counter()
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "1",
                    "-i", str(out), "-f", "null", "-"], capture_output=True)
    return time.perf_counter() - t


_refs = {}


def job(outdir, gif, enc):
    ext, cmd = ENCODERS[enc]
    gif = Path(gif)
    name = f"{gif.parent.parent.name[:40]}__{gif.stem}"
    out = Path(outdir) / enc / (name + ext)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    run = subprocess.run(cmd(str(gif), str(out)), capture_output=True, text=True)
    enc_s = time.perf_counter() - t
    rec = {"gif": str(gif), "name": name, "enc": enc,
           "in_bytes": gif.stat().st_size, "enc_s": round(enc_s, 2)}
    if run.returncode or not out.exists() or not out.stat().st_size:
        rec["error"] = (run.stderr or "").strip()[-300:]
        return rec
    rec["out_bytes"] = out.stat().st_size
    rec["dec_s"] = round(decode_seconds(out), 3)
    ref = _refs[str(gif)]
    got, nframes, err = timeline(out)
    if got is None:
        rec["error"] = "decode: " + err
        return rec
    px, timing, maxdiff, tr, tg = compare(ref[0], got)
    rec.update(frames_ref=ref[1], frames_out=nframes, pixels_equal=px,
               timing_equal=timing, max_ms_diff=maxdiff,
               ms_ref=round(tr), ms_out=round(tg))
    if not px:
        rec["psnr"] = psnr(gif, out)
    return rec


def main():
    outdir, encs, gifs = sys.argv[1], sys.argv[2].split(","), sys.argv[3:]
    for g in gifs:
        tl, n, err = timeline(g)
        _refs[g] = (tl, n)
    jobs = [(g, e) for g in gifs for e in encs]
    # slowest encoders first so the pool drains evenly
    jobs.sort(key=lambda j: (not j[1].startswith(("aom", "x265", "vp9", "jxl")),
                             -Path(j[0]).stat().st_size))
    res = Path(outdir) / "results.jsonl"
    with ThreadPoolExecutor(int(os.environ.get("JOBS", os.cpu_count()))) as pool:
        for rec in pool.map(lambda j: job(outdir, *j), jobs):
            with open(res, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(rec["enc"], rec["name"][:50], rec.get("out_bytes"),
                  rec.get("pixels_equal"), rec.get("error", "")[:80],
                  flush=True)


if __name__ == "__main__":
    main()
