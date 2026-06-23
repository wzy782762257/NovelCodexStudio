#!/usr/bin/env python3
"""Novel Codex Engine — standalone supervisor replacing Codex exec."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure engine/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.config import EngineConfig
from engine.supervisor import Supervisor


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="novel-codex-engine",
        description="Codex + webnovel-writer 长篇小说无人值守引擎（替代 codex exec）",
    )
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="配置文件路径")
    parser.add_argument("--start", type=int, help="起始章；默认从 checkpoint 的下一章开始")
    parser.add_argument("--chapters", type=int, help="本批章数；默认读取 batch_size")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不调用 LLM")
    parser.add_argument("--max-runtime", type=int, default=600, help="单章最大运行时间(秒)，超时自动退出")
    parser.add_argument("--doctor", action="store_true", help="运行项目体检后退出")
    parser.add_argument("--status", action="store_true", help="显示项目状态后退出")
    parser.add_argument("--check", action="store_true", help="检查环境配置后退出")
    args = parser.parse_args()

    config = EngineConfig.load(args.config)

    if args.check:
        print("=" * 40)
        print("环境检查")
        print("=" * 40)
        print(f"项目根目录: {config.project_root}")
        print(f"模型: {config.model}")
        print(f"API base URL: {config.base_url}")
        print(f"API Key: {'已加载 (' + '*' * min(len(config.api_key), 8) + '...)' if config.api_key else '未加载'}")
        print(f"Python 运行时: {config.vendor_python}")
        print(f"webnovel CLI: {config.vendor_cli}")
        print(f"webnovel CLI 存在: {config.vendor_cli.exists()}")
        print(f"project_root 存在: {config.project_root.exists()}")
        print(f"state.json 存在: {(config.project_root / '.webnovel' / 'state.json').exists()}")
        if not config.api_key:
            print("\n[阻塞] 未找到 LLM API Key。请配置以下之一：")
            print("  1. 环境变量: SILICONFLOW_API_KEY 或 OPENAI_API_KEY")
            print("  2. config.json: {\"api_key\": \"sk-...\"}")
            return 1
        if not config.vendor_cli.exists():
            print("\n[阻塞] 未找到 webnovel-writer CLI。请运行: python3 setup.py")
            return 1
        print("\n[通过] 环境检查完成，可以运行引擎。")
        return 0

    if args.doctor:
        from engine.gate_runner import GateRunner
        runner = GateRunner(config)
        print(json.dumps(runner.doctor(), ensure_ascii=False, indent=2))
        return 0

    if args.status:
        from engine.gate_runner import GateRunner
        runner = GateRunner(config)
        print(json.dumps(runner.project_status(), ensure_ascii=False, indent=2))
        return 0

    supervisor = Supervisor(config, max_runtime=args.max_runtime)
    checkpoint = supervisor.checkpoint_path
    if checkpoint.exists():
        cp = json.loads(checkpoint.read_text(encoding="utf-8"))
        last = cp.get("last_committed_chapter", 0)
    else:
        last = 0

    start = args.start or (last + 1)
    count = args.chapters or config.batch_size
    if start < 1 or not 1 <= count <= 20:
        parser.error("start >= 1，chapters 必须在 1-20 之间")

    print(f"Starting batch: chapter {start} -> {start + count - 1} (dry_run={args.dry_run}, max_runtime={args.max_runtime}s)")
    results = supervisor.run_batch(start, count, dry_run=args.dry_run)
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if r.get("status") == "halted" and config.stop_on_halted:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
