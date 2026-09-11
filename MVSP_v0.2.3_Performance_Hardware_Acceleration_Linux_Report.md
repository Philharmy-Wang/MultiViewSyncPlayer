# MVSP v0.2.3 Performance / Hardware Acceleration / Linux Report

Date: 2026-09-11  
Branch: `perf/cross-platform-hwaccel`  
Baseline: `e6716419676890d002b3ebcacaf403e62293d38e`

This report separates verified results from prototypes and unavailable-host results. All Three-Chamber source videos were opened read-only. No source video was modified, renamed, or transcoded.

## A. Windows console popup root cause

The popup was not one single `cmd.exe` launch. It was the accumulation of synchronous media-tool subprocesses and incomplete Windows hiding flags:

| File/function | Original work | Root cause | Fix |
|---|---|---|---|
| `main_window.py::_resolve_session_data` / `_apply_session_data` | OpenCV metadata and identity work for every view | Repeated work ran on the Qt GUI thread during session open | `SessionLoadThread` now resolves and probes off the GUI thread, reports progress, and supports generation cancellation |
| `video_decoder.py::probe_keyframe_index` | Full-file `ffprobe` packet scan | Startup waited for the complete scan before the first frame | First frame starts immediately; indexing runs in a background daemon and is persisted |
| `video_cell.py::load_audio` | `ffmpeg` extraction and waveform reduction | Up to 60 seconds of synchronous GUI-thread work per view | Cancellable `AudioLoadThread`; one waveform job at a time with progress |
| media probe and library reveal call sites | `ffprobe`, `ffmpeg`, Explorer | No uniform window-hiding policy | Central `process_utils.py` uses argument arrays, `shell=False`, `stdin=DEVNULL`, `CREATE_NO_WINDOW`, and hidden `STARTUPINFO` on Windows; Linux receives no Windows flags |

The frozen EXE was run for 20 seconds with a real six-view session. It remained alive, reported version `0.2.3.0-test`, created zero new `conhost.exe` processes, and left no direct child process at sampling time.

## B. Startup performance

The old code had no persistent cache, so a fresh process repeated full packet scans even for a reopen. An identical old-GUI first-frame measurement could not be completed within the practical run because the GUI call itself performed all scans synchronously. The baseline decoder harness measured **40,377.34 ms** for the first full-file keyframe index; this is a lower bound rather than a comparable six-view GUI-open number.

| Six-view GUI session | Old baseline | New cold | New warm |
|---|---:|---:|---:|
| `_load_session()` return | Blocked by synchronous probing/indexing | 2.28 ms | 3.02 ms |
| First displayed frame | Not validly captured; blocked startup | 836.37 ms | 517.94 ms |
| All views ready | Not validly captured | 1,718.21 ms | 1,243.98 ms |
| `ffprobe` processes observed | Repeated full scans; no disk cache | 7 | 1 |
| Metadata cache | None | 6 misses + 6 post-write hits | 6 hits, 0 misses |
| Keyframe cache | Process-only | 6 scans | 6 hits, 0 scans |

The offscreen benchmark cannot verify screen painting or the visibility of the progress label. It does verify that session loading returns to the event loop in about 2–3 ms. The packaged-process smoke is the authoritative console-window check.

## C. Profiling

The top bottleneck is codec decode, followed by random seek and keyframe fast-forward. On the two 2560×1440 HEVC accuracy-gate clips:

| Stage | Cage 2 median / p95 | Cage 3 median / p95 |
|---|---:|---:|
| `cap.read()` decode | 39.082 / 51.897 ms | 34.474 / 46.577 ms |
| Resize | 3.790 / 6.507 ms | 3.275 / 5.444 ms |
| BGR→RGB | 0.689 / 1.602 ms | 0.595 / 1.610 ms |
| NumPy→QImage safe copy | 0.470 / 1.185 ms | 0.369 / 1.028 ms |
| Total image conversion | 5.111 / 8.692 ms | 4.364 / 7.751 ms |
| Random container seek | 124.962 / 165.014 ms | 111.415 / 153.566 ms |
| Keyframe fast-forward | 409.211 / 772.877 ms | 343.714 / 691.572 ms |

In the final six-view mixed H.264/HEVC run, H.264 decode medians were about 9.5 ms and HEVC about 22–23 ms. QImage→QPixmap medians during GUI startup were 0.215–0.313 ms warm. Offscreen Qt produced no real paint-event samples, so no paint-time claim is made.

## D. CPU optimizations

- Resize now happens in BGR before BGR→RGB, so conversion and the mandatory owned QImage copy operate on the preview-sized image. The owned copy remains in place to preserve frame lifetime and correctness.
- Redundant widget scaling is cached by pixmap cache key and widget size.
- FFmpeg decoder threads are capped at four per view; OpenCV's nested internal worker pool is capped at four. Direct tuning showed this to be the best balanced point on this host.
- Metadata/keyframe work is deduplicated across threads and persisted using path, size, nanosecond mtime, quick fingerprint, tool versions, and cache schema. Cache replacement is atomic.
- The full packet scan is delayed until after initial display. Its packet count corrects optimistic OpenCV frame totals, including the HEVC last-frame off-by-one case.

Compared with baseline for six views, the final tuned run changed effective playback from 12.596 to 23.998 FPS (**+90.5%**), startup from 600.15 to 175.61 ms (**−70.7%**), single-step latency from 68.77 to 27.97 ms (**−59.3%**), random-seek latency from 597.61 to 187.54 ms (**−68.6%**), and peak RAM from 1,243.30 to 716.18 MiB (**−42.4%**). Aggregate CPU increased from 276.90% to 728.52% because the candidate decodes substantially more frames in parallel; this is reported explicitly and is not presented as a CPU-usage reduction.

## E. MPV audit

The existing MPV path can be reused for per-view `wid` embedding, play/pause, speed, `time-pos`, and `hwdec=auto`. It was not a Strict backend: it acknowledged the requested nominal frame without observing the actually displayed frame, and it did not previously expose `hwdec-current` or drop counters.

The new backend selector provides `Auto`, `Precision`, and explicit `GPU Prototype` modes. Auto remains OpenCV Precision/Strict until a target host passes the exact-frame gate. An explicitly requested MPV backend is labeled **GPU Prototype**, never Realtime or Strict. Runtime status includes codec, `hwdec-current`, whether hardware decode is actually active, and decoder/VO drop counts.

The current `wid` integration works through Win32 or X11/XWayland. It does not claim native Wayland embedding. No forced desktop-wide switch to X11 was made.

## F. Hardware decode

| Host | Requested | Actual runtime backend | Hardware decode | NVDEC |
|---|---|---|---|---|
| Windows 11 test host, Intel UHD Graphics 730 | Auto | OpenCV Precision / Strict | No | No NVIDIA device |
| Windows 11 test host | GPU | OpenCV fallback | No; `python-mpv`/libmpv unavailable | No |
| Ubuntu NVIDIA | Not run | Not verified | Not verified | Not verified |

GPU activity is never inferred from a request flag. It is true only when the runtime backend reports a non-empty/non-`none` `hwdec-current` value.

## G. Frame accuracy

Two real 2560×1440 HEVC clips were checked independently. Each gate covered initial frame, twenty `+1`, twenty `−1`, `±25`, fifty seeded random targets, three keyframes and nearby frames, and near-end frames.

| Clip | Targets | Off-by-one | Gray | Corrupt | Blank | Timeout | Stale displayed | MAD vs linear reference |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `intrinsics_top_cage2.mp4` | 104/104 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0010–0.0015 |
| `intrinsics_top_cage3.mp4` | 104/104 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0013–0.0015 |

The MPV prototype did not run because libmpv was unavailable; consequently it did not pass the hard gate and Auto did not select it. FFmpeg emitted occasional `Could not find ref with POC 80` diagnostics during adversarial HEVC seeks, but every returned frame matched the linear reference within the MAD ranges above and no visible corruption was detected.

## H. 6-view sync

The final mixed Three-Chamber run used OpenCV Precision with Strict synchronization:

- Effective FPS: **23.998**
- Strict inter-view drift: **0 frames**
- Individual frame misses: **0**
- Strict stall ticks: **4** over the five-second measured playback window
- Single step: **27.97 ms**
- Rapid `+1 × 10`: **277.97 ms**
- Random seek: **187.54 ms**

Existing linked/unlinked and participant-selection tests remain passing. No synchronization-core rewrite and no offset change was made.

## I. Windows benchmark table

All CPU percentages are process aggregate and may exceed 100% on a multicore CPU. GPU/VRAM counters were unavailable on this Intel-only test host.

| OpenCV Precision | Views | Startup ms | Step ms | Rapid ×10 ms | Random seek ms | Effective FPS | CPU % | RAM MiB | Misses | Stalls | Drift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 1 | 239.71 | 21.37 | 200.69 | 160.93 | 24.198 | 179.22 | 347.43 | 0 | 3 | 0 |
| Baseline | 2 | 196.21 | 21.54 | 229.80 | 240.18 | 23.999 | 215.17 | 470.83 | 0 | 4 | 0 |
| Baseline | 4 | 360.90 | 42.51 | 445.91 | 405.83 | 19.391 | 263.84 | 860.47 | 0 | 28 | 0 |
| Baseline | 6 | 600.15 | 68.77 | 549.71 | 597.61 | 12.596 | 276.90 | 1,243.30 | 0 | 61 | 0 |
| Candidate warm | 1 | 98.49 | 10.72 | 107.24 | 91.78 | 24.598 | 80.35 | 187.62 | 0 | 1 | 0 |
| Candidate warm | 2 | 98.51 | 13.13 | 124.14 | 117.89 | 24.398 | 131.41 | 283.19 | 0 | 2 | 0 |
| Candidate warm | 4 | 165.43 | 19.59 | 221.33 | 166.30 | 24.200 | 408.02 | 501.69 | 0 | 3 | 0 |
| Candidate warm | 6 | 194.84 | 30.60 | 317.87 | 207.84 | 22.798 | 683.02 | 721.50 | 0 | 10 | 0 |
| Final threads=4 | 6 | 175.61 | 27.97 | 277.97 | 187.54 | 23.998 | 728.52 | 716.18 | 0 | 4 | 0 |

The benchmark harness did not collect OS GPU %, VRAM, or a single global frame-time p50/p95. Per-stage p50/p95 measurements are reported in section C. The `±25` exactness operations are included in the frame gate; a separate local/global UI latency split was not instrumented.

## J. Ubuntu benchmark table

| Backend | Views 1/2/4/6 | FPS | CPU | GPU decode | GPU/VRAM | Dropped | Drift | Result |
|---|---|---|---|---|---|---|---|---|
| OpenCV Precision | Not run | N/A | N/A | No | N/A | N/A | N/A | No Ubuntu host |
| MPV software | Not run | N/A | N/A | No | N/A | N/A | N/A | libmpv/Linux runtime unavailable |
| MPV `hwdec=auto` | Not run | N/A | N/A | Not verified | N/A | N/A | N/A | NVIDIA host unavailable |
| MPV NVDEC | Not run | N/A | N/A | Not verified | N/A | N/A | N/A | `nvidia-smi` unavailable |

Preflight found Windows 11, no installed WSL distribution, no Docker/Podman, no `nvidia-smi`, and only Intel UHD Graphics 730 plus a virtual display adapter. Installing WSL or changing a GPU driver was outside this run.

## K. Linux package

No Linux binary/tarball was produced, so there is no honest size or SHA256. A native Linux PyInstaller spec, executable build script, dependency declaration, and preflight script are committed. The build intentionally uses system `ffmpeg`, `ffprobe`, and `libmpv` and never bundles Windows EXE/DLL files. It must be built and validated on an actual Ubuntu x86_64 host; building a Linux executable on Windows would not be a native verification.

Planned output name: `MultiViewSyncPlayer-v0.2.3-test-linux-x86_64`.

## L. Windows package

- Directory: `dist/MultiViewSyncPlayer-v0.2.3-test-win64`
- Directory contents: 402 files, 646,818,587 bytes
- ZIP: `dist/MultiViewSyncPlayer-v0.2.3-test-win64.zip`
- ZIP size: 250,567,562 bytes
- SHA256: `43CDB2CC0337473C086C00D6F82219250D890F3B17DC551EA821E011C21979CF`
- File version: `0.2.3.0-test`
- Frozen-process smoke: passed; zero new `conhost.exe`

This is a local test artifact only. It was not released.

## M. Tests

- Previous baseline: **109 passed**
- Final: **121 passed** in 12.67 seconds
- Added coverage: Windows hidden flags, Linux flag exclusion, cache hit/miss/invalidation and packet count, async session load, backend capability and Auto fallback, GPU target mapping, Precision status, native-Wayland non-claim, and display scaling-cache reuse.
- Python compileall: passed
- Windows/Linux spec AST parse: passed
- Linux shell scripts `bash -n`: passed
- HEVC exact-frame gates: 208/208 targets passed

## N. Git

- Start: `e6716419676890d002b3ebcacaf403e62293d38e`
- Implementation commit: `30592309ae1da7b105141288ded9bac4881ccc77`
- Packaging commit: `f8b3c0424111a8803eee125b43dd840c60a4b2a7`
- Report commit: this document's local commit / final branch HEAD
- Branch: `perf/cross-platform-hwaccel`
- Push: **NO**
- Tag: **NO**
- Release: **NO**

Benchmark caches, extracted waveforms, build intermediates, and large benchmark data are not added to Git.

## O. Known limitations

- Ubuntu/NVIDIA/NVDEC execution and native Linux packaging remain unverified because no Linux or NVIDIA runtime exists on this host.
- MPV remains a prototype and cannot be selected by Auto until actual displayed-frame acknowledgement passes the full gate.
- Native Wayland embedding is not implemented; current MPV `wid` support requires X11/XWayland.
- GUI paint timings cannot be concluded from the offscreen Qt benchmark.
- Windows CPU throughput reaches approximately 24 FPS for the measured six-view workload by using more multicore CPU. A verified NVDEC path is still needed for the intended CPU reduction on an NVIDIA Ubuntu host.
- Random HEVC seeks can emit decoder reference warnings even though the validated output frames were correct in this gate.
