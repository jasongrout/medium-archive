# Animated gifs in the Pelican site source: plan and findings

Status (2026-09-23): lossless storage is ruled out for the large gifs,
which make up most of the bytes. Decided: every stored file has the
frame-rate cap (`fpscap.py`), computed on the gif's stored delays; the
format is lossy AV1 4:4:4, or a capped gif where that is smaller. Open:
the CRF, from a capped ladder (28-52) now running. On a 14-file sample
(143 MB), CRF 28 stored 24% of the gifs' bytes with text visually
intact. Nothing in `src/` has changed. The last section says where to
resume.

## Goal

`site-pelican/` is meant to become the blog's own source repository once
the archive has done its job (see `pelican.py`). Today its content holds
*display copies* of the archive's animated gifs, not the originals. The
goal is to make the checked-in file for each animation:

- faithful: pixel-exact if possible, and nearly so only if that saves a
  lot of space, with the original frame timing;
- compact: much smaller than the 587 MB of source gifs;
- an intermediate: a build step (the "second stage") transcodes it to
  whatever browsers are served. Browser support for the intermediate
  itself does not matter, but it should decode reasonably fast.

The hypotheses and candidate encodes come from an external brief. It is
summarized here, with corrections where measurement contradicted it.

## What happens today

`sites.ImagePlacer` (`src/medium_archive/sites.py`) places each gif into
every site as:

- an H.264 mp4 (`libx264`, `yuv420p`, `-crf 20 -preset fast`, frame
  timestamps passed through), scaled to 1104 px on the longest edge and
  rounded to even dimensions, plus a lossy webp poster (`-q 90`) of the
  first frame beside it; or
- the gif itself, or a gifsicle-resized copy, when the gif is shorter
  than 5 s and the clip is no smaller, when ffmpeg, Pillow or libwebp is
  missing, when the first frame is transparent, or when
  `animated_format = "gif"` is set in `site.toml`.

The mp4 is lossy three times over: chroma subsampling, CRF 20, and a
downscale for 129 of the 216 gifs. A site-source repository built from
it cannot get the originals back. Under the plan here, the site source
would hold a lossless intermediate at full resolution, and the mp4,
poster and resize would move into the second stage.

## Gif survey

The full per-file inventory is in `gif-intermediates/inventory.tsv`
(`inventory.py` regenerates it). Every `.gif` under `archive/raw/`:

| | |
|---|---|
| files | 216, in 76 posts; all unique by content hash |
| bytes | 586.6 MB total. Median 1.30 MB, p90 6.5 MB, max 22.6 MB |
| size bands | <0.5 MB: 54 files, 13.6 MB. 0.5-1 MB: 40 files, 29.7 MB. 1-5 MB: 85 files, 198.5 MB. 5-10 MB: 27 files, 174.6 MB. >10 MB: 10 files, 170.2 MB |
| frames | 61,048 total. Median 190 per file, max 2,190 |
| duration | 4,526 s total. Median 17.1 s, max 107 s. 201 of 216 run longer than 5 s |
| dimensions | median longest edge 1200 px, max 3340 px. 129 exceed the current 1104 px cap |
| animated | all 216 (none is a still under a `.gif` name) |
| transparency | none. No composited frame of any file has a pixel with alpha < 255, so RGB-only formats lose nothing |
| loop count | all 216 loop forever (`loop=0`). No loop metadata needs to be recorded |

The 47 files over 5 MB hold 345 MB, 59% of the total. Their result
decides the overall size.

### Short frame delays

Browsers play a gif delay of 0 or 1 cs (≤ 10 ms) as 100 ms. Nine
files have such frames:

| file (under `archive/raw/`) | frames ≤ 10 ms | metadata length | browser length |
|---|---|---|---|
| `11e5dab7c54/images/006-1_DQA3TQcVSJBtWxSMD-sq-g.gif` | 564 of 691 | 12.9 s | 63.7 s |
| `bd2524b247c2/images/005-1_AQTFHOwHXS3uJUC6WKR6WA.gif` | 283 of 851 (the rest 20 ms) | 14.2 s | 39.7 s |
| 7 others (`11e5dab7c54/002`, `52f9657fa7a/007`, `81f2eaad5706/002`, `9549c5dcf551/003`, `a35ce050f7f7/001`, `ae191bc6fb8e/005`, `fe9b54227d92/011`) | 1 each | | +90 ms |

For the first two, the gif's own timing and what readers saw on Medium
disagree by 3-5x. Today's mp4 already plays them at metadata speed. The
intermediate should store the delays exactly as the gif has them.
Whether stage 2 applies the browser clamp is a separate decision (open
question 2).

## Toolchain

The benchmark environment is pinned in `gif-intermediates/pixi.toml` and
`pixi.lock` (conda-forge; linux-64, osx-arm64, osx-64). Run commands
with `pixi run --manifest-path docs/gif-intermediates/pixi.toml ...`.

| component | version | note |
|---|---|---|
| ffmpeg | 9.0.2 | decodes animated webp and jxl, so every candidate is verified the same way |
| libaom | 3.14.1 | |
| SVT-AV1 | 4.2.0 | accepts `yuv420p` only, so it cannot be RGB-lossless. Excluded |
| x264 | 164.3095 | |
| x265 | 3.5 | conda-forge's ffmpeg links it, although upstream has 4.x. Its results reflect an older encoder |
| libvpx | 1.17.0 | |
| libjxl / cjxl | 0.12.0 | needs the `libjxl-tools` package for the command-line tools |
| libwebp / gif2webp | 1.6.0 | |
| gifsicle | 1.96 | |
| Pillow | 12.3.0 | |

Ubuntu 24.04's apt versions (ffmpeg 6.1, cjxl 0.7, libaom about 3.8)
were tried first and dropped as too old. In the Claude Code cloud
environment, pixi.sh and GitHub release downloads are blocked, but
conda.anaconda.org is not. pixi was installed by extracting `bin/pixi`
from the conda-forge `pixi` package.

## Benchmark harness

`gif-intermediates/bench.py OUTDIR ENC[,ENC...] GIF...` encodes each
(gif, encoder) pair single-threaded, running jobs in parallel. It then
decodes the output and compares it with the gif as a *timeline*: a list
of (rgb24 frame md5, display ms), with consecutive identical frames
merged. Formats that merge or split unchanged frames (webp, jxl) are
therefore judged on what is shown and for how long, not on frame
count. Each job appends a line to `OUTDIR/results.jsonl` with the
fields `out_bytes`, `enc_s`, `dec_s` (single-threaded ffmpeg decode),
`pixels_equal`, `timing_equal`, `max_ms_diff`, and the frame counts.

## Findings so far

1. **libaom ignores `lossless=1` without `-crf 0`.** Given
   `-aom-params lossless=1` alone, ffmpeg's wrapper applies its default
   CRF 32 and the output is lossy. With `-crf 0` (with or without
   `lossless=1`) it is bit-exact. The brief's AV1 command is wrong on
   this point, and so were the first pilot's AV1 numbers.
2. **`tune-content=screen` changes nothing.** libaom 3.14 turns its
   screen-content tools on by itself. With and without the tune, the
   full pilot gif came out byte-identical at `-cpu-used 1` (555,167
   bytes), as did its first 20 frames at `-cpu-used 4`. The tools do
   help: on raw gbrp input at `-cpu-used 1`, turning off palette mode
   (`enable-palette=0`) gave +4%, turning off intra block copy
   (`enable-intrabc=0`) +5%, and both +10%. `aom_ll_c1_noscreen` is
   therefore redundant.
3. **gif2webp 1.6 has no `-lossless` flag.** Lossless is its default.
   `-m 6 -q 100` was bit-exact on the pilot gif.
4. **cjxl 0.12 rejects gifs that dispose partial frames to background**
   ("GIF with dispose-to-0 is not supported for non-full or blended
   frames"). The pilot gif is one of them. ffmpeg's `libjxl_anim`
   encoder avoids the gif reader but needs an explicit output muxer;
   the attempt with a `.jxl` name went to the image2 muxer and failed.
   Unresolved.
5. **The harness's first PSNR was broken** (25.018 dB for every inexact
   encode). `quality.py` replaces it: it pairs frames by display time
   and reports PSNR overall and for the worst frame, the largest
   per-channel error, and the share of pixels changed by more than 16
   levels, and saves the worst frame (reference, encode, error x8).
6. **MKV preserved the gif's timing exactly**, last frame included
   (`max_ms_diff` 0), for every lossless video encode. The brief's
   `-fps_mode passthrough` + MKV approach works.
7. **libaom lossless is not reliably exact.** With `-crf 0`, the pilot
   gif at `-cpu-used 4` came back with 10 pixels off by 1 in one channel
   (9 in frame 24, 1 in frame 40), and at `-cpu-used 1` with 1 pixel
   (frame 40). dav1d and libaom's own decoder agree, so the fault is in
   the encoder. It is not ffmpeg's bgra-to-gbrp conversion, and not
   palette mode or intra block copy: encoding from raw gbrp at a
   constant 10 fps, `-cpu-used 4` still differed in 42 bytes with those
   tools on or off, while `-cpu-used 1` was exact in all five tool
   combinations. The gif's variable frame timing changes the encoder's
   decisions (528,236 bytes from constant-rate raw input against
   555,167 from the gif), and some paths hit the fault. Any AV1
   intermediate would need every file verified, with a fallback for
   files that fail. `-cpu-used 4` is dropped. `-cpu-used 2` was exact
   on the large file below.
8. **Lossless video codecs lose badly on dithered photographic
   content.** The large file below is a screen recording of a notebook
   playing a video clip. The clip area is photographic, quantized to the
   gif's 256-color palette with dithering: 255 colors per frame, about
   10% of pixels changing per frame. Reproducing that dither exactly in
   RGB costs every video codec more than the gif's own palette indices
   do. Only formats that can code a palette beat the gif there: WebP
   lossless (73%), against 190-257% for x264rgb, x265 and AV1.
9. **Timing: every tool except Pillow and gifsicle changed it at first.**
   - ffmpeg encodes (and the harness's own reference decode) used a time
     base guessed from the frame rate: 3/20 s or 1/20 s, which rounds
     every delay. The pilot gif's 25.30 s came out 25.50 s. `-enc_time_base
     1:1000` fixes both. **The site's current mp4 clips have this
     rounding** (checked with `sites.py`'s exact arguments); queued as a
     separate fix. The earlier "timing exact" results in the tables above
     were measured against a rounded reference, and the x264rgb/x265/AV1
     files had rounded timestamps.
   - gif2webp stores delays of 10 ms or less as 100 ms, as browsers play
     them (checked with `webpmux -info`: the 564-short-delay gif came out
     with 570 frames of 100 ms, 63.7 s instead of 12.9 s). Pillow's WebP
     writer (`pil_encode.py webp`, the same libwebp encoder and settings)
     and img2webp store the delays as given.
   - ffmpeg's WebP *decoder* plays stored delays of 10 ms or less as
     100 ms. The harness therefore reads WebP delays with `webpmux`
     (`quality.webp_durations`); before that fix, WebP encodes of the
     short-delay gifs were wrongly reported as mistimed.
   - ffmpeg's GIF demuxer does *not* alter short delays in 9.0.2 (its
     `min_delay` option notwithstanding): the same gif reads as 12.9 s.
   - ffmpeg's APNG muxer rounds delays even with a 1/100 time base
     (25.30 s came out 25.66 s).
10. **JPEG XL works through an APNG written by Pillow.** ffmpeg has no
    animated-JPEG XL muxer and cjxl rejects some gifs directly, but cjxl
    reads APNG. `pil_encode.py apng` writes one with exact delays (RGB,
    fast deflate), and cjxl encodes it losslessly. On the pilot gif:
    493,941 bytes (60%) at effort 7 in 6 s, 479,626 (58%) at effort 9 in
    19 s, both exact in pixels and timing.
11. **APNG itself is not a candidate.** It allows one palette per file.
    The pilot gif uses 1,140 colors across its frames (per-frame
    palettes), so `pal8` loses colors, and RGB APNG is 196% of the gif.
    Only an animation with 256 colors or fewer in total (the large file
    has 255) could use `pal8`.
12. **AV1 at `-cpu-used 2` is not reliably exact either**: 606,475 bytes
    on the pilot gif, with pixels differing. Exactness failures are now
    seen at `-cpu-used` 1, 2 and 4.
13. **No lossless format is smaller than the gif on the large files.**
    On the four largest sample files, WebP lossless was 73-150% of the
    gif, JPEG XL 82-582%, AV1 lossless 257-597% (several inexact). The
    gif's per-frame palettes, LZW and changed-rectangle frames are hard
    to beat losslessly on this content. Lossless would at best shrink
    the small, plain screencasts (x264rgb 51% on the pilot).
14. **JPEG XL lost no colors going through the APNG.** Pillow writes the
    APNG in RGB, not with a palette; the JPEG XL was pixel-exact against
    the gif's 1,140 colors. (The color loss was only in the separate
    ffmpeg `pal8` APNG test.) Pillow's APNG writer holds every frame in
    memory, which killed the effort-9 encode of the 851-frame
    1798x1390 gif.
15. **Lossy AV1 4:4:4 is the strongest option.** See the lossy sweep
    below. JPEG XL lossy (VarDCT or modular) came out larger than the
    gif with the worst quality in the sweep; WebP lossy (4:2:0 only) was
    up to 217% of the gif; WebP near-lossless keeps the error at 4 or
    less but saves only 27-40%.

### Pilot numbers (one file, not a conclusion)

`9549c5dcf551/images/003-1_BIDimBvS_g8QH5fuHS_QRQ.gif`: 1000x600, 72
frames, 25.3 s, 821,378 bytes.

| encode | bytes | vs gif | encode s | decode s | exact |
|---|---|---|---|---|---|
| libx264rgb `-qp 0 -preset placebo` | 422,719 | 51% | 7.6 | 0.19 | yes |
| libx265 lossless `placebo` | 479,004 | 58% | 73.6 | 0.28 | yes |
| gif2webp `-m 6 -q 100` | 511,574 | 62% | 124 | not measured | yes |
| gifsicle `-O3` | 788,532 | 96% | 0.5 | 0.12 | yes |
| libvpx-vp9 lossless `-cpu-used 0` | 1,231,696 | 150% | 35 | 0.25 | yes |
| ffv1 (intra only) | 3,344,058 | 407% | 1.2 | 1.32 | yes |
| libaom lossless `-crf 0 -cpu-used 1` | 555,167 | 68% | 92 | 0.21 | no: 1 pixel off by 1 (finding 7) |
| libaom lossless `-crf 0 -cpu-used 4` | 607,292 | 74% | 21 | 0.23 | no: 10 pixels off by 1 (finding 7) |
| libaom `-crf 4` | 236,770 | 29% | 103 | 0.18 | no, PSNR unknown |
| libx264rgb `-crf 4` | 562,054 | 68% | 18 | 0.21 | no, and larger than its lossless encode |

On this file, x264rgb lossless beats x265, webp and AV1, contrary to
the brief's expectation that AV1 would win. One file is not a sample:
the large-file run below tests whether that holds where the bytes are.

### Large file (the least favourable case for video so far)

`2e432df402c8/images/013-0_ArP2iU5tKYDHvvZd.gif`: 1836x970, 101 frames
(60 after merging repeated frames), 10.1 s, 17,564,258 bytes. Five
jobs shared four cores for part of the run, so encode times are
slightly inflated.

| encode | bytes | vs gif | encode s | decode s | exact |
|---|---|---|---|---|---|
| gif2webp `-m 6 -q 100` | 12,851,572 | 73% | 1057 | 0.80 | yes |
| gifsicle `-O3` | 17,131,328 | 98% | 5 | 0.55 | yes |
| libx264rgb `-qp 0 -preset placebo` | 33,341,342 | 190% | 70 | 4.40 | yes |
| libx265 lossless `placebo` | 41,332,559 | 235% | 633 | 4.41 | yes |
| libaom `-crf 0 -cpu-used 1` | 44,791,394 | 255% | 1819 | 4.58 | yes |
| libaom `-crf 0 -cpu-used 2` | 45,059,073 | 257% | 751 | 4.62 | yes |

Together with the pilot, no single format wins: x264rgb was best on a
plain screencast, WebP on a screencast that contains video. The winner
depends on content. Two outcomes are possible: one format that is
never much worse than the gif (WebP is the candidate), or a choice per
file between a video codec and a palette format, taking the smaller
exact result.

### Lossy sweep

Five files: the pilot (text screencast, `9549`), a 2642x1872 screencast
(`164eb/007`), the median-size gif (`388d05`), the notebook playing
video (`013`), and the largest gif (`bd2524`: a notebook whose cell
background is a faint two-color dither, recorded at 50-100 frames per
second). Size as % of the gif, then overall PSNR. AV1 used
`-cpu-used 4`, H.264 `-preset slower`, both `yuv444p`.

| file | AV1 CRF 20 | AV1 CRF 12 | H.264 CRF 16 | H.264 CRF 12 | WebP near-lossless 40 |
|---|---|---|---|---|---|
| `9549` | 11%, 51.5 dB | 13%, 52.0 | 30%, 50.9 | 35%, 51.7 | 63%, 58.1 |
| `164eb/007` | 12%, 55.2 | 19%, 57.2 | 18%, 50.9 | 27%, 53.7 | 60%, 51.7 |
| `388d05` | 13%, 50.5 | 19%, 52.5 | 25%, 49.5 | 38%, 52.0 | 65%, 46.6 |
| `013` | 27%, 41.6 | 53%, 44.5 | 57%, 42.7 | 92%, 45.7 | 73%, 65.4 |
| `bd2524` | 98%, 47.7 | 128%, 50.4 | 76%, 38.9 | 119%, 42.3 | 66%, 63.3 |

Also tried and dropped: JPEG XL `-d 1` (48-1111%), JPEG XL modular
`-m 1 -d 0.5` (71-1252%), WebP `-lossy -q 90 -sharp_yuv` (49-217%),
WebP near-lossless 60 (no saving over lossless).

PSNR undercounts quality where a codec smooths dither: the smoothing
is a large pixel error that is invisible. The worst frame of each AV1
CRF 20 encode was inspected at 2x at its highest-error spot: code, a
clock readout and small monospace text were visually unchanged (the
error is faint edge noise); the video region of `013` lost its dither
and grain, which is acceptable here.

AV1 encode times at `-cpu-used 4` were 20-650 s, and 1900 s on
`bd2524`; decoding took 0.2-13.6 s per file. A one-time conversion can
afford that; `-cpu-used 6` is being measured.

### AV1 on the 14-file sample

`aom_444_*` is libaom, `yuv444p`, `-g 9999`, single-threaded; `c6` is
`-cpu-used 6`, otherwise 4. Size as % of the gif, overall PSNR, and
the share of pixels changed by more than 16 levels.

| file | MB | gifsicle `-O3` | CRF 20 | CRF 28 | CRF 20 c6 |
|---|---|---|---|---|---|
| `bd2524b247c2/005` | 22.6 | 93% | 98%, 47.7 dB, 0.083% | 66%, 45.2, 0.296% | 98%, 46.2, 0.168% |
| `77df24c8db80/002` | 22.5 | 118% | 36%, 42.8, 0.264% | 17%, 40.6, 0.790% | 31%, 41.6, 0.422% |
| `164eb2eae102/003` | 19.9 | 121% | 15%, 41.8, 0.254% | 8%, 40.5, 0.447% | 12%, 41.0, 0.340% |
| `2e432df402c8/013` | 17.6 | 98% | 27%, 41.6, 0.224% | 12%, 39.6, 0.588% | 16%, 39.4, 0.618% |
| `701e7b9841e6/002` | 16.1 | 98% | 18%, 46.4, 0.010% | 12%, 44.5, 0.045% | 18%, 44.6, 0.024% |
| `164eb2eae102/007` | 13.6 | 108% | 12%, 55.2, 0.001% | 9%, 53.4, 0.003% | 11%, 53.5, 0.002% |
| `c9d93542f20b/014` | 12.0 | 98% | 16%, 46.7, 0.020% | 9%, 45.4, 0.037% | 13%, 45.5, 0.031% |
| `cda20dc15a21/005` | 6.5 | 67% | 96%, 62.6, 0.000% | 86%, 59.4, 0.001% | 75%, 59.6, 0.002% |
| `11e5dab7c54/006` | 6.0 | 96% | 60%, 50.4, 0.015% | 45%, 48.7, 0.038% | 56%, 49.0, 0.024% |
| `03e6b78bacc0/003` | 3.3 | 96% | 25%, 45.0, 0.028% | 17%, 42.9, 0.083% | 26%, 44.3, 0.043% |
| `388d05e03442/002` | 1.3 | 98% | 13%, 50.5, 0.006% | 10%, 48.4, 0.015% | 15%, 49.9, 0.008% |
| `9549c5dcf551/003` | 0.8 | 96% | 11%, 51.5, 0.000% | 10%, 50.7, 0.001% | 13%, 51.0, 0.001% |
| `8096b8b223d0/007` | 0.5 | 95% | 58%, 52.0, 0.000% | 46%, 51.3, 0.002% | 55%, 51.6, 0.003% |
| `2e432df402c8/009` | 0.2 | 93% | 30%, 63.1, 0.000% | 25%, 60.5, 0.000% | 30%, 62.3, 0.000% |
| **total** | 142.9 | 103% | 39% | 25% | 35% |

With the gif (gifsicle `-O3`) kept wherever it is smaller: CRF 28
24%, CRF 20 c6 34%, CRF 20 37%. At CRF 28 only `cda20dc15a21/005`
keeps its gif.

Encode times at `-cpu-used 4` were 18-1911 s per file, at
`-cpu-used 6` 8-669 s; c6 was also slightly *smaller* at CRF 20, with
somewhat lower PSNR on some files.

Visual check at CRF 28: from each file's worst frame, the region with
the most error on flat backgrounds (where text damage shows) was
inspected at 2x. Text ("Name: chevrolet", code) and chart lines are
intact, with faint edge noise; dithered backgrounds, video and
satellite imagery are smoothed.

### Frame-rate cap

`fpscap.py` writes an ffmpeg `select` filter script that drops frames
inside bursts faster than about 30 fps. It keeps the first and last
frame, every frame on screen for 29.5 ms or longer, and every frame
starting 29.5 ms or more after the last kept one; a frame kept for its
start gives way to a following long frame when the two would be under
29.5 ms apart. Kept frames keep their exact timestamps and the total
length is unchanged (checked on three files). The expression is nested
as a balanced tree: ffmpeg's parser fails on a flat sum of a few
hundred terms.

ffmpeg's own options do not do this: `-r`/`-fpsmax` require
constant-rate output ("contradictory" with `-fps_mode vfr`), and
`fps=30` resamples, moving 284 of 426 kept frames of `bd2524` onto a
33 ms grid, with higher pixel error than `fpscap.py`.

The cap affects 11 of the 216 gifs (3,749 of 61,048 frames). Nine are
from one post (`cda20dc15a21`), recorded at a steady 40 fps (25 ms
frames), where it drops about half the frames. The other two are the
gifs with 10 ms frames, which depend on the timing policy (open
question 2): browsers play those frames at 100 ms, so readers saw
every one of them.

| file | dropped, stored timing | dropped, browser timing |
|---|---|---|
| `bd2524b247c2/005` | 425 of 851 | 283 of 851 |
| `11e5dab7c54/006` | 403 of 691 | 0 of 691 |

### Decisions (2026-09-23)

- **Timing is the gif's stored delays**, as the author made it, not
  what browsers played (≤ 10 ms as 100 ms).
- **Every stored file has the frame-rate cap**, applied before
  encoding as the `select` filter in the same ffmpeg run (capping after
  encoding would need a second lossy encode). On a gif without bursts
  the cap keeps every frame, and the encode's video stream is
  identical to an uncapped one (checked: same packets, only container
  metadata differs), so uncapped results on such files stand.
- **A gif kept as the fallback is capped too** (`fpscap.py --gif`).
  gifsicle cannot drop frames from a gif with per-frame color tables
  ("GIF too complex to unoptimize"; the result was 11 dB off), so
  Pillow composites each kept frame, writes it whole with a palette of
  exactly its colors and the merged delay, and gifsicle `-O3`
  re-optimizes. Exact (verified: infinite PSNR, same length) when no
  composited frame has over 256 colors; otherwise refused. All nine
  40 fps gifs of `cda20dc15a21` and `bd2524` qualify; `11e5dab7c54/006`
  (up to 6,141 colors per frame) does not, and its capped AV1 is 43%
  of the gif anyway. Capped gifs: `cda20dc15a21/005` 67% of the
  original (the same as uncapped `-O3`: whole frames with their own
  color tables cost what the dropped frames saved), `bd2524` 64%.
- `quality.py` now pairs from the encode's side (each encoded frame
  against the gif frame on screen at its start), so frames the cap
  drops by design are not counted as errors. Uncapped scores are
  unchanged.
- Capped AV1 CRF 20 (`-cpu-used 4`): `11e5dab7c54/006` 43% of the gif
  (60% uncapped), `cda20dc15a21/005` 89% (96% uncapped).

## Open questions

1. **Container and codec.** Lossless is ruled out for the large files
   (finding 13). The working proposal is two formats: AV1 4:4:4 at
   CRF 28 in MKV, and the original gif (gifsicle-optimized) wherever
   that is smaller. `-cpu-used 6` at CRF 28 is being measured.
2. **Short delays.** Decided: the gif's stored delays (see Decisions).
3. **Where stage 2 runs.** It could run in the Pelican build (a plugin
   step, with a cache) or in the exporter as today. Since the site
   source is meant to outlive this repository, stage 2 probably belongs
   with the site: a plugin plus a pinned ffmpeg.
4. **Decoder trust.** The reference frames are ffmpeg's gif decode. They
   have not yet been cross-checked against Pillow's compositing on the
   sample. The brief warns of past ffmpeg disposal bugs.

## Resume here

1. Record the capped CRF ladder (running when this was written):
   `aom444_c6_crf{28,34,40,46,52}_cap` on `bd2524b247c2/005`,
   `2e432df402c8/013`, `164eb2eae102/007`, `cda20dc15a21/005`,
   `11e5dab7c54/006`, `388d05e03442/002` and `9549c5dcf551/003`.
   Put the same text region of each file side by side across the CRFs
   and find where text visibly degrades; pick the CRF a step below.
2. Check `-cpu-used 6` against 4 at the chosen CRF on a few files.
3. Convert the whole archive: capped AV1 at the chosen CRF, and a
   capped gif (`fpscap.py --gif`) wherever that is smaller, including
   `3ee42dfdc54f/002` (2190 frames, not in the sample). Verify every
   output (timing, quality.py) and inspect the worst frames.
4. Change the pelican exporter to place the intermediate instead of
   the display copy, and add stage 2.
