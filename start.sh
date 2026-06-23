#!/bin/bash
# Novel Codex Studio — 统一启动脚本
# 一键启动后端服务 + 前端控制面板

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo "  Novel Codex Studio · 小说自动创作平台"
echo "═══════════════════════════════════════════════════"

# ─── 1. 检查环境 ──────────────────────────────────
echo ""
echo "[1/4] 检查环境..."

if ! python3 -c "import flask" 2>/dev/null; then
    echo "  → 安装 Flask..."
    python3 -m pip install flask flask-cors -q
fi

if [ ! -f "config.json" ]; then
    echo "  ⚠ 未找到 config.json，请创建配置文件"
    echo "    cp config.example.json config.json"
    echo "    编辑 config.json 添加 API Key"
    exit 1
fi

# ─── 2. 清理残留状态 ──────────────────────────────
echo ""
echo "[2/4] 清理残留状态..."
rm -f book/.novel-supervisor/lock
rm -f book/.novel-supervisor/.running
rm -f book/.novel-supervisor/.paused
echo "  ✓ 已清理"

# ─── 3. 启动后端 ──────────────────────────────────
echo ""
echo "[3/4] 启动后端服务..."

# 停止旧进程
pkill -f "python3 web/backend.py" 2>/dev/null || true
sleep 1

# 启动新进程
python3 launch.py
echo "  ✓ 后端 PID: $BACKEND_PID"
echo "  ✓ 日志: /tmp/novel-codex-backend.log"

# 等待后端启动
for i in {1..10}; do
    if curl -s http://localhost:8080/api/project/status > /dev/null 2>&1; then
        echo "  ✓ 后端已就绪 (http://localhost:8080)"
        break
    fi
    sleep 0.5
done

# ─── 4. 保存 PID 文件 ─────────────────────────────
echo "$BACKEND_PID" > /tmp/novel-codex.pid
echo ""
echo "[4/4] 启动完成"

# ─── 5. 使用说明 ──────────────────────────────────
echo ""
echo "───────────────────────────────────────────────────"
echo "  控制面板: http://localhost:8080"
echo "  后端日志: tail -f /tmp/novel-codex-backend.log"
echo "  引擎日志: tail -f /tmp/engine_live.log"
echo ""
echo "  停止服务:  ./stop.sh"
echo "  或手动:    kill $(cat /tmp/novel-codex.pid)"
echo "───────────────────────────────────────────────────"

# 尝试打开浏览器（macOS/Linux）
if command -v open > /dev/null 2>&1; then
    open "http://localhost:8080" &
elif command -v xdg-open > /dev/null 2>&1; then
    xdg-open "http://localhost:8080" &
fi

wait
