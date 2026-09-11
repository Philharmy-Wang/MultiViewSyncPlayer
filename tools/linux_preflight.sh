#!/usr/bin/env bash
set -u

uname -a
cat /etc/os-release
python3 --version
nvidia-smi || true
ffmpeg -version | head -n 1
ffprobe -version | head -n 1
mpv --version | head -n 2 || true
ldconfig -p | grep -i mpv || true
printf 'XDG_SESSION_TYPE=%s\n' "${XDG_SESSION_TYPE:-}"
printf 'WAYLAND_DISPLAY=%s\n' "${WAYLAND_DISPLAY:-}"
printf 'DISPLAY=%s\n' "${DISPLAY:-}"
