#!/usr/bin/env python3
"""Create an isolated runtime and install webnovel-writer dependencies."""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / "bin" / "python"
REQUIREMENTS = ROOT / "vendor" / "webnovel-writer" / "requirements.txt"


def main() -> int:
    if sys.version_info < (3, 10):
        print("需要 Python 3.10 或更高版本", file=sys.stderr)
        return 1
    if not PYTHON.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    subprocess.run(
        [str(PYTHON), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [str(PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [str(PYTHON), "-c", "import aiohttp,filelock,pydantic,fastapi,uvicorn,watchdog"],
        check=True,
        cwd=ROOT,
    )
    print(f"运行环境已就绪: {PYTHON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
