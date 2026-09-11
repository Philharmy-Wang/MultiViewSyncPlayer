#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

python3 -m venv .venv-linux
source .venv-linux/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,hardware]' pyinstaller psutil
python -m pytest -q
python -m PyInstaller --noconfirm packaging/mvsp_linux.spec
tar -C dist -czf dist/MultiViewSyncPlayer-v0.2.3-test-linux-x86_64.tar.gz \
  MultiViewSyncPlayer-v0.2.3-test-linux-x86_64
sha256sum dist/MultiViewSyncPlayer-v0.2.3-test-linux-x86_64.tar.gz
