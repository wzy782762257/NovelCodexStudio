#!/usr/bin/env python3
"""Initialize the bundled webnovel-writer project in ./book."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "book"
CLI = ROOT / "vendor" / "webnovel-writer" / "webnovel-writer" / "scripts" / "webnovel.py"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 Codex 长篇小说工程")
    parser.add_argument("title", help="小说标题")
    parser.add_argument("genre", help="中文题材，如 玄幻、悬疑脑洞、都市异能")
    parser.add_argument("--protagonist-name", default="")
    parser.add_argument("--target-words", type=int, default=2_000_000)
    parser.add_argument("--target-chapters", type=int, default=600)
    parser.add_argument("--core-selling-points", default="")
    parser.add_argument("--platform", default="")
    args = parser.parse_args()
    if not VENV_PYTHON.exists():
        parser.error("缺少项目虚拟环境，请先运行 python3 setup.py")

    command = [
        str(VENV_PYTHON), "-X", "utf8", str(CLI),
        "--project-root", str(BOOK),
        "init", str(BOOK), args.title, args.genre,
        "--protagonist-name", args.protagonist_name,
        "--target-words", str(args.target_words),
        "--target-chapters", str(args.target_chapters),
        "--core-selling-points", args.core_selling_points,
        "--platform", args.platform,
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
