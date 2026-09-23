# Animated gifs in the sites: findings and decisions

Status (2026-09-23): implemented in `ImagePlacer` (`src/medium_archive/sites.py`).
This page summarizes the measurements behind it. The per-run tables
are in this file's git history, and the tools are in
`docs/gif-intermediates/`.

## What the exporters do now

Each animated gif in `archive/raw/` stays the master. Every site gets:

- **An H.264 clip for every animation**, in a `<video>` a reader can
  pause, even where the clip is larger than the gif. The exceptions,
  which stay gifs, are gifs with real transparency and machines
  without ffmpeg or Pillow.
- **Settings:** 4:2:0, High profile, `-crf 24 -preset slower`, one
  thread per encode (`warm()` encodes gifs in parallel).
- **Full resolution:** `animated_max_edge` defaults to 0. Odd sizes
  are padded by a pixel rather than rescaled.
- **A frame-rate cap near 30 fps:** `kept_frames` drops frames inside
  faster bursts, and every kept frame starts exactly when the gif
  shows it.
- **Exact timing:** timestamps use a millisecond time base, taken
  from the gif's stored delays.
- **A poster:** the clip's first frame as webp, at the clip's size.

Clips are encoded on the fly into `.image-cache/`, keyed by the gif's
hash and the settings (`CACHE_SCHEME` v6). CI restores that cache
between builds, so nothing encoded is committed.

## The gifs

- **Count:** 216 gifs in 76 posts, 587 MB, all unique. The 47 over
  5 MB hold 59% of the bytes.
- **Content:** screen recordings, some with embedded video or
  dithered backgrounds. All are opaque and all loop forever.
- **Length:** a median of 17 s. 15 run under 5 s (18 MB in total).
- **Size:** longest edge median 1,200 px, maximum 3,340 px. 129 are
  wider or taller than 1,104 px.
- **Short delays:** two gifs store 10 ms delays that browsers play as
  100 ms, so they ran 3-5 times longer on Medium than their stored
  timing. `bd2524b247c2/005` is stored as 14.2 s and played as
  39.7 s; `11e5dab7c54/006` as 12.9 s and 63.7 s.
- **Fast recordings:** one post (`cda20dc15a21`) has nine 40 fps
  recordings.

`gif-intermediates/inventory.tsv` has the per-file survey.

## Findings

**1. Lossless storage does not pay on the large gifs.** On the four
largest, no lossless format beat the gif:

| format | size vs the gif |
|---|---|
| WebP lossless | 73-150% |
| JPEG XL | 82-582% |
| AV1 lossless | 257-597% |

A gif stores per-frame palettes compressed with LZW, and only the
rectangle that changed in each frame. That is hard to beat without
loss on screen content. Libaom's lossless mode was also not reliably
exact: single pixels came out off by one at `-cpu-used` 1, 2 and 4.

**2. Browsers set the quality ceiling, through 4:2:0 color.** Video
stores brightness at full resolution. 4:4:4 keeps color at full
resolution too; 4:2:0, the only format every browser plays, keeps one
color sample per 2x2 block of pixels. On screen content that makes
red code strings pinkish and soft, dulls 1-pixel saturated lines, and
erases dither dots, whatever the codec or CRF. Every 4:2:0 encode sat
at 36-38 dB median PSNR against the gif; 4:4:4 encodes reached
41-48 dB. The site's earlier clips had this loss too.

**3. Codecs compared.** Seven difficult files (68 MB of gifs), all
frame-rate capped:

| encode | plays in | size vs gifs | median PSNR |
|---|---|---|---|
| H.264 4:2:0 CRF 20 | all browsers | 40% | 37.3 dB |
| H.264 4:2:0 CRF 24 (chosen) | all browsers | 28% | 36.6 dB |
| AV1 4:2:0 CRF 24 (libaom `-cpu-used 6`) | not Safari before Apple M3 | 20% | 36.6 dB |
| AV1 4:2:0 CRF 28 (libaom) | not Safari before Apple M3 | 17% | 36.2 dB |
| AV1 4:4:4 CRF 28 (libaom) | Chrome and Firefox | 27% | 47.6 dB |
| H.264 4:4:4 CRF 20 | no browser | 48% | 41.6 dB |
| SVT-AV1 4:2:0 CRF 30, preset 6 | not Safari before Apple M3 | 38% | 36.5 dB |

- **Two-step chain:** making H.264 from an AV1 master was slightly
  smaller than H.264 straight from the gif, but lower quality on every
  file (0.2-1.2 dB). So nothing is stored between the gif and the clip.
- **SVT-AV1** is fast, but it lost badly on 1-pixel line content, and
  it does not keep the last frame's duration.

**4. CRF.**
- **H.264 4:2:0:** CRF 16, 20 and 24 looked alike in crops of text at
  3x zoom. What differed from the gif was the 4:2:0 color, the same at
  each CRF. CRF 24 is about a third smaller than CRF 20.
- **AV1:** a ladder from CRF 28 to 52 found where small text breaks.
  First artifacts appear at CRF 34, damage is clear at 40, and CRF 52
  shows text copied from the wrong place.

**5. Resolution.** H.264 CRF 24 at a limit on the longest edge,
against full resolution:

| limit | size vs gifs | vs full resolution |
|---|---|---|
| none (full resolution) | 28% | 100% |
| 1,472 px (twice the body column) | 22% | 79% |
| 1,104 px (the old default) | 17% | 61% |

Scaling saves most on dithered or video content and least on screen
text, which it blurs. Full resolution keeps code readable when a
reader takes a clip full screen. That is the same reasoning by which
`sites.py` keeps still line art at full resolution.

**6. Frame-rate cap.** It affects 11 of the 216 gifs (3,749 of 61,048
frames):
- **Delays:** the stored delays are used, as the author made them,
  not the 100 ms browsers substituted.
- **ffmpeg's own options don't fit:** `-r` and `-fpsmax` require
  constant-rate output, and `fps=30` moves frame boundaries onto its
  grid.
- **Filter form:** the `select` expression is nested as a balanced
  tree, because ffmpeg's parser fails on a flat sum of a few hundred
  terms.
- **Savings:** a clip of `11e5dab7c54/006` came out 43% of the gif
  capped against 60% uncapped (AV1 CRF 20, 4:4:4).

**7. Clips that are larger than their gifs.** The 40 fps
`cda20dc15a21` recordings are particle simulations: hundreds of
triangles drawn with aliased 1-pixel pure-green lines, each moving on
its own. A gif codes these almost for free. A video codec gets little
from motion prediction here and pays heavily to transform-code
1-pixel edges, and 4:2:0 cannot represent the thin green lines. H.264
comes out at 155-211% of the gif. These are placed as clips anyway,
for the pause control.

**8. Timing traps** (all avoided now):
- **ffmpeg's guessed time base:** left alone, ffmpeg gives the encoder
  a time base from a guessed frame rate and rounds every timestamp to
  it; one 25.3 s gif played 25.5 s. `-enc_time_base 1:1000` fixes it.
- **x264 threading:** splitting one encode across threads made one
  clip 39% larger.
- **gif2webp** stores delays of 10 ms or less as 100 ms.
- **ffmpeg's WebP decoder** plays stored delays of 10 ms or less as
  100 ms.
- **ffmpeg's APNG muxer** rounds delays.
- **cjxl** rejects gifs whose partial frames dispose to background.
- **gifsicle** cannot drop frames from gifs with per-frame color
  tables.

## Later: re-encoding to AV1

AV1 is not served now because Safari plays it only on Apple M3 or
later hardware (2026-09). Once it plays broadly, re-encoding from the
gif masters is a change to the codec arguments and `CACHE_SCHEME`,
plus a longer cold cache.

What AV1 gains, from the seven-file sample:

- **About 30% smaller in 4:2:0 at equal quality:** libaom CRF 24 was
  20% of the gifs against H.264 CRF 24's 28%, both at 36.6 dB median.
  CRF 28 is 17% for a small drop.
- **Much smaller on line-drawing content:** libaom 4:2:0 was 70-74% of
  the particle gifs against 155% for H.264. Its screen-content tools
  (palette mode and intra block copy) work in 4:2:0 too.
- **Full color (4:4:4), if browsers decode it:** Chrome and Firefox do
  today. AV1 4:4:4 CRF 28 was 27% of the gifs at 47.6 dB median, and
  it keeps colored text, 1-pixel lines and dither that 4:2:0 loses.
  CRF 28 was clean on small text; CRF 34 showed the first artifacts.

What it costs:

- **Encode time:** libaom at `-cpu-used 6` encodes about 2.5 times
  slower than H.264 `-preset slower`, and `-cpu-used 4` is slower
  still with no gain in size. The image cache absorbs this, as it does
  H.264.
- **SVT-AV1** is fast, but it is not the encoder to use (finding 3).

A possible intermediate step: a `<video>` can list several
`<source>` elements, and the browser plays the first one it
supports. The site could serve AV1 with an H.264 fallback before AV1
is universal, at the cost of encoding and storing both.

## Tools (`docs/gif-intermediates/`)

- `pixi.toml`, `pixi.lock`: the pinned conda-forge toolchain (ffmpeg
  9.0.2, libaom 3.14.1, SVT-AV1 4.2.0, x264, libjxl 0.12, libwebp 1.6,
  gifsicle 1.96). Run tools with `pixi run --manifest-path
  docs/gif-intermediates/pixi.toml ...`. In a Claude Code cloud
  session, pixi.sh and GitHub downloads are blocked, but
  conda.anaconda.org is reachable, so pixi was installed by extracting
  it from its conda-forge package.
- `inventory.py`, `inventory.tsv`: the survey of all 216 gifs.
- `bench.py`: encodes gif × encoder jobs in parallel and checks each
  against the gif (timeline of frame hashes and display time). It
  calls `quality.py` for inexact encodes. Encoders are named by their
  settings, for example `x264_420_crf24_cap`, `aom420_c6_crf28_cap`
  or `svt420_p6_crf30_cap`.
- `quality.py`: PSNR (overall and worst frame), largest error and the
  share of visibly changed pixels. It pairs each encoded frame with
  the gif frame on screen at the same moment, and saves the worst
  frame for inspection.
- `fpscap.py`: the frame-rate cap as an ffmpeg filter script, and
  `--gif` for an exact capped gif (Pillow, then gifsicle).
- `pil_encode.py`: APNG and WebP with exact delays (Pillow and
  img2webp).

## Still to do

1. **Full-archive build.** Build the sites from the whole archive,
   and record the total clip size and the cold-cache build time. CI's
   comment gives about 20 minutes cold on four cores for the old
   settings; full resolution with `-preset slower` will take longer.
2. **Browser check.** Watch clips from a built site in browsers,
   including the largest (3,340x1,517) and a `cda20dc15a21` particle
   clip.
