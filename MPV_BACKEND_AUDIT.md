# MPV Backend Audit

Audit date: 2026-09-11. The existing implementation is an experimental backend,
not a Precision replacement.

| Question | Finding |
|---|---|
| Is the normal UI using MPV? | No. Previously only `--backend mpv`; v0.2.3 `Auto` remains OpenCV until a host-specific exact-frame gate passes. |
| Embedded render? | Yes, via a native Qt widget `winId` passed as MPV `wid`; it is not libmpv render API integration. |
| Per-view seek? | Nominally yes: each view owns an MPV instance and writes `time-pos = frame / fps`. |
| Reliable paused frame-step? | **Not proven.** No `video-frame-info`/actual displayed-frame acknowledgment is used. |
| Offset support? | Targets include offsets, but only nominal target numbers are acknowledged. |
| Strict barrier integration? | **No.** The old path emitted the requested number with a `None` image immediately; the barrier therefore certified a request, not the rendered frame. |
| Read frame / time position? | `time-pos` is read; exact displayed frame is not currently read. |
| Read dropped frames? | MPV exposes `decoder-frame-drop-count` and `vo-drop-frame-count`, but the UI did not consume them. |
| Read `hwdec-current`? | MPV exposes it, but the UI did not consume it. |
| Windows libmpv? | Not present in the source environment or existing v0.2.2-test4 package. Python `mpv` is also absent. |
| Linux libmpv? | Can use system libmpv when installed; no Ubuntu distribution is currently available on this host for runtime verification. |
| Wayland? | Current `wid` embedding is X11/XWayland-oriented. Native Wayland is **not PASS**; render API work is required. |

## v0.2.3 safety decision

The new selection layer exposes `Auto`, `Precision`, and `GPU` (legacy aliases
remain accepted). `Auto` falls back to Precision/Strict unless capability and
frame-accuracy certification are both true. An explicit available GPU backend
is labeled `GPU Prototype`; it is not represented as Strict or as the optional
globally-dropping Realtime mode (that mode has not been implemented). Capability
reporting includes the MPV properties required for codec, current hwdec, and
drop counters.

The existing MPV prototype is retained for follow-up testing rather than
rewriting the stable synchronization core. It must not become the Precision
backend until two real HEVC sequences pass: 0 off-by-one, gray, corrupt, stale,
and an image-consistency comparison against the OpenCV reference.
