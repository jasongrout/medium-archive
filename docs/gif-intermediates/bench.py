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
import re
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
FF = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
# -enc_time_base: left to itself, ffmpeg gives the encoder a time base
# from a guessed frame rate (1/20 s for one gif), which rounds every
# frame's timestamp -- the site's mp4 clips carry that rounding today
PT = ["-fps_mode", "passthrough", "-enc_time_base", "1:1000", "-an",
      "-threads", "1"]

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
    "aom_ll_c2": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "2", "-g", "9999", "-row-mt", "0",
        "-crf", "0", "-aom-params", "lossless=1:tune-content=screen",
        "-pix_fmt", "gbrp", o]),
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
    # gif2webp plays delays of 10 ms or less as 100 ms, as browsers do;
    # webp_pil keeps the gif's delays exactly
    "webp_pil": (".webp", lambda i, o: [
        sys.executable, str(HERE / "pil_encode.py"), "webp", i, o]),
    "webp_ll_min": (".webp", lambda i, o: [
        "gif2webp", "-quiet", "-min_size", "-m", "6", "-q", "100",
        i, "-o", o]),
    # APNG has one palette per file: pal8 is exact only when the whole
    # animation has <= 256 colors (palettegen then keeps them as they
    # are), and fails the exactness check otherwise. ffmpeg's APNG muxer
    # also rounds frame delays (25.30 s came out 25.66 s).
    "apng_pal8": (".apng", lambda i, o: FF + ["-i", i] + PT + [
        "-filter_complex",
        "split[a][b];[a]palettegen=max_colors=256:reserve_transparent=0"
        ":stats_mode=full[p];[b][p]paletteuse=dither=none",
        "-c:v", "apng", "-pred", "mixed", "-plays", "0", "-f", "apng", o]),
    "apng_rgb": (".apng", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "apng", "-pred", "mixed", "-plays", "0", "-pix_fmt", "rgb24",
        "-f", "apng", o]),
    # cjxl 0.12 rejects gifs whose partial frames dispose to background
    # ("GIF with dispose-to-0 is not supported"), and ffmpeg has no
    # animated-jxl muxer, so the gif goes through an RGB APNG that
    # Pillow writes with the gif's exact delays (pil_encode.py)
    "jxl_e7": (".jxl", lambda i, o: via_apng(i, o, "7")),
    "jxl_e9": (".jxl", lambda i, o: via_apng(i, o, "9")),
    # lossy: smooths the gif's dither, which lossless coding has to keep
    "webp_nl60": (".webp", lambda i, o: pil(i, o, "-near_lossless", "60",
                                           "-m", "6", "-q", "100")),
    "webp_nl40": (".webp", lambda i, o: pil(i, o, "-near_lossless", "40",
                                           "-m", "6", "-q", "100")),
    "webp_q90": (".webp", lambda i, o: pil(i, o, "-lossy", "-q", "90",
                                          "-m", "6", "-sharp_yuv")),
    "jxl_d05": (".jxl", lambda i, o: via_apng(i, o, "7", "-d", "0.5")),
    "jxl_d1": (".jxl", lambda i, o: via_apng(i, o, "7", "-d", "1")),
    "x264_444_crf12": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libx264", "-crf", "12", "-preset", "slower", "-g", "9999",
        "-pix_fmt", "yuv444p", o]),
    "aom_444_crf28": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "4", "-g", "9999", "-row-mt", "0",
        "-crf", "28", "-pix_fmt", "yuv444p", o]),
    "aom_444_crf20_c6": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "6", "-g", "9999", "-row-mt", "0",
        "-crf", "20", "-pix_fmt", "yuv444p", o]),
    "aom_444_crf28_c6": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "6", "-g", "9999", "-row-mt", "0",
        "-crf", "28", "-pix_fmt", "yuv444p", o]),
    # the same with the frame rate capped near 30 fps (fpscap.py)
    "aom_444_crf20_cap": (".mkv", lambda i, o: capped(i, o, [
        "-c:v", "libaom-av1", "-cpu-used", "4", "-g", "9999", "-row-mt", "0",
        "-crf", "20", "-pix_fmt", "yuv444p"])),
    "x264_444_crf16": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libx264", "-crf", "16", "-preset", "slower", "-g", "9999",
        "-pix_fmt", "yuv444p", o]),
    # modular (not VarDCT) lossy: JPEG XL's mode for non-photographic art
    "jxl_m_d05": (".jxl", lambda i, o: via_apng(i, o, "7", "-m", "1",
                                               "-d", "0.5")),
    "aom_444_crf12": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "4", "-g", "9999", "-row-mt", "0",
        "-crf", "12", "-pix_fmt", "yuv444p", o]),
    "aom_444_crf20": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "4", "-g", "9999", "-row-mt", "0",
        "-crf", "20", "-pix_fmt", "yuv444p", o]),
    # near-lossless
    "aom_crf4": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libaom-av1", "-cpu-used", "1", "-g", "9999", "-row-mt", "0",
        "-crf", "4", "-aom-params", "tune-content=screen",
        "-pix_fmt", "gbrp", o]),
    "x264rgb_crf4": (".mkv", lambda i, o: FF + ["-i", i] + PT + [
        "-c:v", "libx264rgb", "-crf", "4", "-preset", "placebo", "-g", "9999",
        "-pix_fmt", "rgb24", o]),
}


def via_apng(i, o, effort, *cjxl):
    """cjxl from an exact-timing RGB APNG; lossless unless cjxl options
    (a distance) are given."""
    apng = o + ".apng"
    opts = " ".join(cjxl) or "-d 0"
    return ["bash", "-c",
            '"$5" "$6" apng "$1" "$2" && cjxl --quiet ' + opts + ' -e "$4"'
            ' --num_threads=0 "$2" "$3"; r=$?; rm -f "$2"; exit $r',
            "_", i, apng, o, effort, sys.executable,
            str(HERE / "pil_encode.py")]


def capped(i, o, codec, extra_vf=None):
    """An ffmpeg encode of the gif with fpscap.py's frame selection,
    followed by extra_vf when given."""
    vf = o + ".vf"
    ff = " ".join(FF + ["-i", '"$1"', "-/vf", '"$3"'] + PT + codec + ['"$2"'])
    append = (f"sed -i '$ s#$#,{extra_vf}#' \"$3\" && " if extra_vf
              else "")
    return ["bash", "-c",
            '"$4" "$5" "$1" "$3" >/dev/null && ' + append + ff
            + '; r=$?; rm -f "$3"; exit $r',
            "_", i, o, vf, sys.executable, str(HERE / "fpscap.py")]


def pil(i, o, *img2webp):
    return [sys.executable, str(HERE / "pil_encode.py"), "img2webp", i, o,
            *img2webp]


# 4:2:0 needs even dimensions: pad by a pixel rather than scale, so the
# encode's frames line up with the gif's (quality.py crops the pad off)
EVEN = "pad=ceil(iw/2)*2:ceil(ih/2)*2"


def encoder(name):
    """ENCODERS[name], or an encode named by its settings:
    aom444_c6_crf34[_cap]  libaom 4:4:4, -cpu-used 6, CRF 34
    aom420_c6_crf34[_cap]  the same in 4:2:0 (what browsers play)
    svt420_p6_crf30[_cap]  SVT-AV1 (4:2:0 only), preset 6, CRF 30,
                           screen-content detection, one thread
    x264_420_crf20[_cap]   libx264 4:2:0 High profile (what browsers
                           play), -preset slower, CRF 20
    x264_444_crf20[_cap]   libx264 4:4:4 (High 4:4:4), for reference
    _cap applies fpscap.py's frame selection."""
    if name in ENCODERS:
        return ENCODERS[name]
    m = re.fullmatch(r"aom(420|444)_c(\d+)_crf(\d+)(_cap)?", name)
    if m:
        codec = ["-c:v", "libaom-av1", "-cpu-used", m[2], "-g", "9999",
                 "-row-mt", "0", "-crf", m[3], "-pix_fmt", f"yuv{m[1]}p"]
        vf, cap = (EVEN if m[1] == "420" else None), m[4]
    elif m := re.fullmatch(r"svt420_p(\d+)_crf(\d+)(_cap)?", name):
        codec = ["-c:v", "libsvtav1", "-preset", m[1], "-crf", m[2],
                 "-g", "9999", "-svtav1-params", "scm=2:lp=1",
                 "-pix_fmt", "yuv420p"]
        vf, cap = EVEN, m[3]
    else:
        m = re.fullmatch(r"x264_(420|444)_crf(\d+)(_cap)?", name)
        if not m:
            raise KeyError(name)
        codec = ["-c:v", "libx264", "-preset", "slower", "-crf", m[2],
                 "-pix_fmt", f"yuv{m[1]}p",
                 "-profile:v", "high" if m[1] == "420" else "high444"]
        vf, cap = (EVEN if m[1] == "420" else None), m[3]
    if cap:
        return ".mkv", lambda i, o: capped(i, o, codec, vf)
    return ".mkv", lambda i, o: (FF + ["-i", i] + PT
                                 + (["-vf", vf] if vf else []) + codec + [o])


def timeline(path):
    """[(hash, ms)] of what is shown, consecutive identical frames merged,
    plus the raw frame count. The 1 ms time base matters: left to
    itself, ffmpeg picks one from a guessed frame rate (3/20 s for one
    gif), which rounds every delay."""
    run = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v",
         "-fps_mode", "passthrough", "-enc_time_base", "1:1000",
         "-pix_fmt", "rgb24", "-f", "framemd5", "-"],
        capture_output=True, text=True)
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
    if str(path).endswith(".webp"):
        # ffmpeg reads WebP delays of 10 ms or less as 100 ms; use the
        # file's own (see quality.webp_durations)
        from quality import webp_durations
        d = webp_durations(path)
        if len(d) == len(rows):
            ms = Fraction(1, 1000) / tb
            t = 0
            for k, (pts, dur, h) in enumerate(rows):
                rows[k] = (int(t * ms), int(d[k] * ms), h)
                t += d[k]
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


def quality(gif, out, snap):
    """quality.py's numbers for an inexact encode, and its worst frame
    saved under snap for looking at."""
    run = subprocess.run([sys.executable, str(HERE / "quality.py"), str(gif),
                          str(out), str(snap)], capture_output=True, text=True)
    try:
        return json.loads(run.stdout)
    except ValueError:
        return {"quality_error": (run.stderr or "").strip()[-200:]}


def decode_seconds(out):
    t = time.perf_counter()
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "1",
                    "-i", str(out), "-f", "null", "-"], capture_output=True)
    return time.perf_counter() - t


_refs = {}


def job(outdir, gif, enc):
    ext, cmd = encoder(enc)
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
        rec.update(quality(gif, out, Path(outdir) / enc / (name + ".worst")))
    return rec


def main():
    outdir, encs, gifs = sys.argv[1], sys.argv[2].split(","), sys.argv[3:]
    for g in gifs:
        tl, n, err = timeline(g)
        _refs[g] = (tl, n)
    jobs = [(g, e) for g in gifs for e in encs]
    # slowest encoders first so the pool drains evenly
    jobs.sort(key=lambda j: (not j[1].startswith(("aom", "x265", "vp9", "jxl",
                                                  "webp")),
                             -Path(j[0]).stat().st_size))
    res = Path(outdir) / "results.jsonl"
    Path(outdir).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(int(os.environ.get("JOBS", os.cpu_count()))) as pool:
        futures = [pool.submit(job, outdir, *j) for j in jobs]
        for fut in as_completed(futures):   # record each job as it ends
            rec = fut.result()
            with open(res, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(rec["enc"], rec["name"][:50], rec.get("out_bytes"),
                  rec.get("pixels_equal"), rec.get("error", "")[:80],
                  flush=True)


if __name__ == "__main__":
    main()
