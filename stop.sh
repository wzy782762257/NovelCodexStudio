#!/bin/bash
# Novel Codex Studio — 停止脚本

echo "═══════════════════════════════════════════════════"
echo "  Novel Codex Studio · 停止服务"
echo "═══════════════════════════════════════════════════"

# 1. 调用后端 API 停止引擎
echo ""
echo "[1/3] 通知后端停止引擎..."
curl -s -X POST http://localhost:8080/api/batch/stop > /dev/null 2>&1 || true
sleep 1

# 2. 停止后端进程
echo ""
echo "[2/3] 停止后端进程..."
if [ -f /tmp/novel-codex.pid ]; then
    PID=$(cat /tmp/novel-codex.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
        sleep 1
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null || true
        fi
        echo "  ✓ 已停止后端 (PID: $PID)"
    else
        echo "  ℹ 后端进程已不存在"
    fi
    rm -f /tmp/novel-codex.pid
else
    # 尝试通过名称查找
    pkill -f "python3 web/backend.py" 2>/dev/null || true
    echo "  ✓ 已尝试停止后端"
fi

# 3. 清理状态文件
echo ""
echo "[3/3] 清理状态文件..."
cd "$(dirname "$0")"
rm -f book/.novel-supervisor/lock
rm -f book/.novel-supervisor/.running
rm -f book/.novel-supervisor/.paused
echo "  ✓ 已清理"

echo ""
echo "───────────────────────────────────────────────────"
echo "  服务已停止"
echo "───────────────────────────────────────────────────"
