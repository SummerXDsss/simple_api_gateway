#!/usr/bin/env bash
set -e

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║      Local AI API Gateway            ║"
echo "  ║      正在启动服务...                  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# 检查虚拟环境是否存在
if [ ! -f ".venv/bin/uvicorn" ]; then
    echo "[错误] 未找到虚拟环境，请先执行："
    echo ""
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    echo ""
    exit 1
fi

# 确保 data 目录存在
mkdir -p data

echo "[信息] 服务地址：http://127.0.0.1:8000"
echo "[信息] 管理界面：http://127.0.0.1:8000/"
echo "[信息] 按 Ctrl+C 停止服务"
echo ""

.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

echo ""
echo "[信息] 服务已停止。"
