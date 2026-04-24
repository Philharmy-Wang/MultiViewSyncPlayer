#!/usr/bin/env bash
# MultiViewSyncPlayer Linux/macOS 一键安装脚本
# 功能：检测 Python → 创建 venv → pip 安装
# 生成时间：2026-04-24
set -e

echo "============================================"
echo "  MultiViewSyncPlayer 安装脚本"
echo "============================================"
echo

command -v python3 >/dev/null 2>&1 || {
    echo '[错误] 未检测到 python3，请先安装 Python >= 3.9'
    exit 1
}
python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)' || {
    echo '[错误] Python 版本低于 3.9，请升级。'
    exit 1
}

if [ ! -d .venv ]; then
    echo "[1/3] 创建虚拟环境..."
    python3 -m venv .venv
else
    echo "[1/3] 虚拟环境已存在，跳过。"
fi

source .venv/bin/activate

echo "[2/3] 升级 pip..."
python -m pip install --upgrade pip -q

echo "[3/3] 安装依赖..."
pip install -r requirements.txt -q

echo
echo "============================================"
echo "  [完成] 运行 ./run.sh 启动"
echo "============================================"

# 创建 run.sh（幂等）
cat > run.sh <<'RUNEOF'
#!/usr/bin/env bash
dir="$(cd "$(dirname "$0")" && pwd)"
source "$dir/.venv/bin/activate"
python "$dir/run.py" "$@"
RUNEOF
chmod +x run.sh
