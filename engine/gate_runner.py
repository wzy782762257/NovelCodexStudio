#!/usr/bin/env python3
"""Gate runner: call webnovel-writer CLI for prewrite / precommit / commit / postcommit."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import EngineConfig


class GateRunner:
    def __init__(self, config: EngineConfig):
        self.config = config

    def _run(self, args: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        """Run a CLI command and return parsed output."""
        python = str(self.config.vendor_python)
        cli = str(self.config.vendor_cli)
        command = [python, "-X", "utf8", cli, "--project-root", str(self.config.project_root), *args]
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd or self.config.project_root,
            timeout=120,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        try:
            result = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            result = {"raw_stdout": stdout, "raw_stderr": stderr}
        result["returncode"] = proc.returncode
        if stderr:
            result["stderr"] = stderr
        return result

    def prewrite(self, chapter: int) -> dict[str, Any]:
        return self._run(["write-gate", "--chapter", str(chapter), "--stage", "prewrite", "--format", "json"])

    def precommit(self, chapter: int) -> dict[str, Any]:
        return self._run(["write-gate", "--chapter", str(chapter), "--stage", "precommit", "--format", "json"])

    def postcommit(self, chapter: int) -> dict[str, Any]:
        return self._run(["write-gate", "--chapter", str(chapter), "--stage", "postcommit", "--format", "json"])

    def commit(
        self,
        chapter: int,
        review_path: Path,
        fulfillment_path: Path,
        disambiguation_path: Path,
        extraction_path: Path,
    ) -> dict[str, Any]:
        return self._run([
            "chapter-commit",
            "--chapter", str(chapter),
            "--review-result", str(review_path),
            "--fulfillment-result", str(fulfillment_path),
            "--disambiguation-result", str(disambiguation_path),
            "--extraction-result", str(extraction_path),
        ])

    def preflight(self) -> dict[str, Any]:
        return self._run(["preflight", "--format", "json"])

    def project_status(self) -> dict[str, Any]:
        return self._run(["project-status", "--format", "summary"])

    def doctor(self, chapter: int | None = None) -> dict[str, Any]:
        args = ["doctor", "--format", "text"]
        if chapter is not None:
            args.extend(["--chapter", str(chapter)])
        return self._run(args)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import EngineConfig

    cfg = EngineConfig.load(Path("config.json"))
    runner = GateRunner(cfg)

    print("=== preflight ===")
    print(json.dumps(runner.preflight(), ensure_ascii=False, indent=2))

    print("\n=== prewrite chapter 1 ===")
    print(json.dumps(runner.prewrite(1), ensure_ascii=False, indent=2))
