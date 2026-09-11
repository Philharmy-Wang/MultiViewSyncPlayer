# Windows Child Process Audit

Audit date: 2026-09-11. Baseline: `e6716419676890d002b3ebcacaf403e62293d38e`.

| File / function | Executable | Frequency | Execution | GUI thread before fix | Console before fix | Estimated cold cost |
|---|---|---:|---|---|---|---:|
| `video_decoder.py::probe_keyframe_index` | ffprobe | once per video per process | synchronous packet scan | No, but decoder startup waited before first frame | Partially hidden by `CREATE_NO_WINDOW` only | ~6.7 s/video uncached in the measured six-file run |
| `video_cell.py::load_audio` | ffmpeg | once per loaded view | synchronous | **Yes** | **Visible** | up to the 60 s timeout; full audio decode |
| `media_cache.py::tool_version` | ffmpeg / ffprobe | once per executable per process | synchronous, cached | background during session probe | Hidden | <100 ms typical |
| `library/browser.py` reveal action | Explorer / open / xdg-open | explicit user action | asynchronous | launch initiated on GUI thread | platform shell could inherit a console | small |
| `packaging/build_windows.bat` | PowerShell Compress-Archive | packaging only | synchronous | No application runtime | build console expected | build-only |

No `os.system`, `check_output`, `check_call`, `QProcess`, `cmd.exe`, or runtime
`shell=True` entry was found. PyInstaller already uses `console=False`; the
observed popups came from runtime media child processes, not the main EXE.

## Fix

All runtime children now use `process_utils.py`. On Windows it combines
`CREATE_NO_WINDOW`, `STARTF_USESHOWWINDOW`, and `SW_HIDE`; every platform uses
`shell=False` and `stdin=DEVNULL`. Linux never references Windows-only flags.
ffprobe indexing is persistent and deferred until after first-frame delivery.
ffmpeg waveform extraction runs in a cancellable background QThread and is
serialized across views. Session identity and metadata probing also moved off
the GUI thread, with status-bar progress and generation-based cancellation.

Automated coverage: Windows hidden flags, Linux absence of Windows flags,
cache hit/miss/invalidation, and non-blocking session probe tests.
