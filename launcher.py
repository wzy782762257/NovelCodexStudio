#!/usr/bin/env python3
"""Stable command-line entry point for Novel Codex Studio."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "book"
PYTHON = ROOT / ".venv" / "bin" / "python"
CLI = ROOT / "vendor" / "webnovel-writer" / "webnovel-writer" / "scripts" / "webnovel.py"
BACKUP_ROOT = ROOT.parent / "NovelCodexBackups"


def require_runtime() -> None:
    if not PYTHON.exists():
        raise SystemExit(f"运行环境不存在，请执行：python3 {ROOT / 'setup.py'}")


def run(command: list[str], *, cwd: Path = ROOT) -> int:
    return subprocess.run(command, cwd=cwd, check=False).returncode


def open_codex() -> int:
    BOOK.mkdir(parents=True, exist_ok=True)
    return run(["open", "-a", "Codex", str(BOOK)])


def webnovel(*args: str) -> int:
    require_runtime()
    return run([
        str(PYTHON), "-X", "utf8", str(CLI),
        "--project-root", str(BOOK), *args
    ])


def backup_book() -> int:
    if not BOOK.exists():
        raise SystemExit("书项目尚不存在。")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_ROOT / f"book-{stamp}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(BOOK, arcname="book", filter=_backup_filter)
    print(target)
    return 0


def _backup_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    if "__pycache__" in parts or ".novel-supervisor" in parts and "lock" in parts:
        return None
    return info


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="novel-codex",
        description="Codex + webnovel-writer 长篇小说工作台",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("open", help="在 Codex 中打开固定书项目")
    sub.add_parser("where", help="显示固定安装位置")
    sub.add_parser("status", help="查看当前小说进度")
    sub.add_parser("doctor", help="运行项目体检")
    sub.add_parser("backup", help="把书项目备份到独立目录")
    pack_parser = sub.add_parser("pack", help="生成单章轻量上下文包")
    pack_parser.add_argument("--chapter", type=int, required=True)

    init_parser = sub.add_parser("init", help="初始化一本新书")
    init_parser.add_argument("title")
    init_parser.add_argument("genre")
    init_parser.add_argument("--protagonist-name", default="")
    init_parser.add_argument("--target-words", type=int, default=2_000_000)
    init_parser.add_argument("--target-chapters", type=int, default=600)
    init_parser.add_argument("--core-selling-points", default="")
    init_parser.add_argument("--platform", default="")

    run_parser = sub.add_parser("run", help="执行无人值守批次")
    run_parser.add_argument("--start", type=int)
    run_parser.add_argument("--chapters", type=int)
    run_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    command = args.command or "open"

    if command == "open":
        return open_codex()
    if command == "where":
        print(ROOT)
        print(f"book={BOOK}")
        print(f"backups={BACKUP_ROOT}")
        return 0
    if command == "status":
        return webnovel("project-status", "--format", "summary")
    if command == "doctor":
        return webnovel("doctor", "--format", "text")
    if command == "backup":
        return backup_book()
    if command == "pack":
        require_runtime()
        return run([
            str(PYTHON), str(ROOT / "context_pack.py"),
            "--chapter", str(args.chapter),
        ])
    if command == "init":
        require_runtime()
        init_command = [
            str(PYTHON), str(ROOT / "init_book.py"),
            args.title, args.genre,
            "--protagonist-name", args.protagonist_name,
            "--target-words", str(args.target_words),
            "--target-chapters", str(args.target_chapters),
            "--core-selling-points", args.core_selling_points,
            "--platform", args.platform,
        ]
        return run(init_command)
    if command == "run":
        require_runtime()
        run_command = [str(PYTHON), str(ROOT / "supervisor.py")]
        if args.start is not None:
            run_command.extend(["--start", str(args.start)])
        if args.chapters is not None:
            run_command.extend(["--chapters", str(args.chapters)])
        if args.dry_run:
            run_command.append("--dry-run")
        return run(run_command)
    parser.error(f"未知命令: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
