# Ubuntu / Linux Preflight Status

Prepared: 2026-09-11.

The current execution host is Windows 11. It has no installed WSL distribution,
Docker, or Podman, so an Ubuntu-native binary and runtime NVDEC evidence cannot
be produced honestly on this host. `nvidia-smi` is unavailable and Windows
reports Intel UHD Graphics 730 plus a virtual display adapter; there is no
local NVIDIA runtime to validate.

`packaging/mvsp_linux.spec`, `packaging/build_linux.sh`, and
`tools/linux_preflight.sh` are ready to run on the target Ubuntu RTX machine.
The Linux build installs python-mpv but intentionally requires system ffmpeg,
ffprobe, and libmpv. The current `wid` prototype may work under X11/XWayland;
native Wayland GPU embedding remains unverified and is never reported as PASS.

Required target-host sequence:

1. Run `tools/linux_preflight.sh` and retain its output.
2. Validate the same read-only HEVC clips with MPV `hwdec=auto`, then `nvdec`.
3. Run the OpenCV CPU 1/2/4/6-view matrix.
4. Run the MPV software/auto/nvdec matrix and inspect `hwdec-current`.
5. Run the MPV frame-accuracy gate against Precision before enabling Auto.
6. Run `packaging/build_linux.sh` natively and record size/SHA256.

No instruction in this repository requires switching the entire desktop from
Wayland to X11.
