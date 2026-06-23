#!/usr/bin/env python3
"""Engine configuration loader."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EngineConfig:
    # Batch scheduling
    batch_size: int = 5
    max_revisions: int = 1
    max_consecutive_failures: int = 2
    timeout_minutes: int = 45

    # LLM
    model: str = "deepseek-v3"
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 4000

    # Project paths
    project_root: Path = Path("book")
    supervisor_dir: Path = Path("book/.novel-supervisor")
    webnovel_dir: Path = Path("book/.webnovel")
    story_system_dir: Path = Path("book/.story-system")

    # Sandbox / safety
    sandbox: str = "workspace-write"
    stop_on_halted: bool = True

    # Derived
    vendor_python: Path = Path(".venv/bin/python")
    vendor_cli: Path = Path("vendor/webnovel-writer/webnovel-writer/scripts/webnovel.py")

    @classmethod
    def load(cls, path: Path) -> "EngineConfig":
        raw: dict[str, Any] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))

        # Resolve project root from config or default
        root = Path(raw.get("project_root", "book"))
        if not root.is_absolute():
            root = Path(__file__).resolve().parent.parent / root
        root = root.resolve()

        # API key resolution: explicit config > env var
        api_key = raw.get("api_key", "")
        if not api_key:
            for env_name in (
                "SILICONFLOW_API_KEY",
                "OPENAI_API_KEY",
                "KIMI_API_KEY",
            ):
                api_key = os.environ.get(env_name, "")
                if api_key:
                    break

        base_url = raw.get("base_url", "")
        if not base_url:
            for env_name in (
                "SILICONFLOW_BASE_URL",
                "OPENAI_BASE_URL",
            ):
                base_url = os.environ.get(env_name, "")
                if base_url:
                    break
        if not base_url:
            base_url = "https://api.siliconflow.cn/v1"

        vendor_python = Path(raw.get("vendor_python", ".venv/bin/python"))
        if not vendor_python.is_absolute():
            vendor_python = root.parent / vendor_python

        vendor_cli = Path(raw.get("vendor_cli", "vendor/webnovel-writer/webnovel-writer/scripts/webnovel.py"))
        if not vendor_cli.is_absolute():
            vendor_cli = root.parent / vendor_cli

        return cls(
            batch_size=raw.get("batch_size", 5),
            max_revisions=raw.get("max_revisions", 1),
            max_consecutive_failures=raw.get("max_consecutive_failures", 2),
            timeout_minutes=raw.get("timeout_minutes", 45),
            model=raw.get("model", "deepseek-v3"),
            base_url=base_url,
            api_key=api_key,
            temperature=raw.get("temperature", 0.7),
            max_tokens=raw.get("max_tokens", 4000),
            project_root=root,
            supervisor_dir=root / ".novel-supervisor",
            webnovel_dir=root / ".webnovel",
            story_system_dir=root / ".story-system",
            sandbox=raw.get("sandbox", "workspace-write"),
            stop_on_halted=raw.get("stop_on_halted", True),
            vendor_python=vendor_python,
            vendor_cli=vendor_cli,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "max_revisions": self.max_revisions,
            "max_consecutive_failures": self.max_consecutive_failures,
            "timeout_minutes": self.timeout_minutes,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "project_root": str(self.project_root),
            "sandbox": self.sandbox,
            "stop_on_halted": self.stop_on_halted,
        }


if __name__ == "__main__":
    import sys
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")
    cfg = EngineConfig.load(config_path)
    print(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2))
    print(f"api_key_loaded={'*' * min(len(cfg.api_key), 8)}...")
