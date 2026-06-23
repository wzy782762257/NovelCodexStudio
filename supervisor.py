#!/usr/bin/env python3
"""Batch supervisor for Codex + webnovel-writer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from context_pack import build_packet


ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "book"
SCHEMA = ROOT / "schemas" / "chapter-result.schema.json"
RUNTIME = BOOK / ".novel-supervisor"
CHECKPOINT = RUNTIME / "checkpoint.json"
LOCK = RUNTIME / "lock"


@dataclass(frozen=True)
class Config:
    batch_size: int = 5
    max_revisions_per_chapter: int = 1
    max_consecutive_failures: int = 2
    timeout_minutes_per_chapter: int = 45
    codex_model: str = "gpt-5.5"
    sandbox: str = "workspace-write"
    ephemeral_sessions: bool = False
    stop_on_halted: bool = True

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"未知配置项: {', '.join(sorted(unknown))}")
        config = cls(**raw)
        if not 1 <= config.batch_size <= 20:
            raise ValueError("batch_size 必须在 1-20 之间")
        if not 0 <= config.max_revisions_per_chapter <= 1:
            raise ValueError("低用量模式每章最多返工 1 次")
        if config.sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("无人值守模式只允许 read-only 或 workspace-write sandbox")
        return config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_checkpoint() -> dict[str, Any]:
    if not CHECKPOINT.exists():
        return {
            "schema_version": 1,
            "last_committed_chapter": 0,
            "consecutive_failures": 0,
            "runs": []
        }
    return json.loads(CHECKPOINT.read_text(encoding="utf-8"))


class ProcessLock:
    def __enter__(self) -> "ProcessLock":
        RUNTIME.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"监督器已在运行；若确认是残留锁，请删除 {LOCK}") from exc
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        return self

    def __exit__(self, *_: object) -> None:
        LOCK.unlink(missing_ok=True)


def codex_command(config: Config, output_file: Path) -> list[str]:
    command = [
        "codex", "exec",
        "--ignore-user-config",
        "-c", 'service_tier="fast"',
        "--cd", str(BOOK),
        "--sandbox", config.sandbox,
        "--output-schema", str(SCHEMA),
        "--output-last-message", str(output_file),
        "--color", "never",
    ]
    if config.codex_model:
        command.extend(["--model", config.codex_model])
    if config.ephemeral_sessions:
        command.append("--ephemeral")
    command.append("-")
    return command


def prompt_for(chapter: int, config: Config, packet_path: Path | None = None) -> str:
    packet_path = packet_path or (
        RUNTIME / "context" / f"chapter-{chapter:04d}.json"
    )
    return f"""执行第 {chapter} 章无人值守创作。唯一上下文文件：
{packet_path}

严格限制：
1. 读取项目级 `.codex/skills/novel-director/SKILL.md` 后，只读取上述章节包；
   不要读取其他 SKILL.md、vendor 文档或其他大纲/设定。
2. 不得使用子代理，不得扫描仓库，不得联网。
3. 只可写章节包指定的 chapter_file、.webnovel/tmp 四份 JSON 和上游命令自动生成的文件。
4. 先跑 prewrite；失败即安全停止。根据章节包写正文并自行做事实审查与文风审查，
   最多定点返工 {config.max_revisions_per_chapter} 次。
   正文必须严格控制在 2000–3000 个汉字，范围外不得进入提交。
5. 将真实审查和事实提取写入四份 artifact；不得伪造覆盖节点或分数。
6. 只有正文覆盖全部节点、无禁区、无 blocking issue、无 pending 时，才依次运行
   precommit、chapter-commit、postcommit。任一失败都不得声称已提交。
7. 最终只返回符合指定 JSON Schema 的结果。硬门全过且 commit accepted 才能
   status=committed、committed=true。"""


def run_chapter(chapter: int, config: Config, dry_run: bool) -> dict[str, Any]:
    logs = RUNTIME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_path = logs / f"chapter-{chapter:04d}-{stamp}.result.json"
    event_path = logs / f"chapter-{chapter:04d}-{stamp}.events.jsonl"
    packet_path = build_packet(chapter)
    command = codex_command(config, result_path)
    if dry_run:
        return {
            "status": "dry-run",
            "chapter": chapter,
            "command": command,
            "prompt": prompt_for(chapter, config, packet_path),
            "context_packet": str(packet_path),
            "context_chars": len(packet_path.read_text(encoding="utf-8")),
        }

    started = time.monotonic()
    with event_path.open("w", encoding="utf-8") as events:
        completed = subprocess.run(
            command,
            input=prompt_for(chapter, config, packet_path),
            text=True,
            stdout=events,
            stderr=subprocess.STDOUT,
            timeout=config.timeout_minutes_per_chapter * 60,
            check=False,
        )
    elapsed = round(time.monotonic() - started, 2)
    if completed.returncode != 0:
        log_tail = event_path.read_text(encoding="utf-8", errors="replace")[-20000:]
        usage_limited = "You've hit your usage limit" in log_tail
        return {
            "status": "retryable",
            "chapter": chapter,
            "committed": False,
            "quality_gate": {"hard_pass": False, "revision_count": 0, "scores": {}},
            "issues": [
                "Codex 使用额度已耗尽，等待额度恢复后重试。"
                if usage_limited else f"codex exec 退出码 {completed.returncode}"
            ],
            "summary": (
                "外部额度阻塞，正文和正式状态均未提交。"
                if usage_limited else "Codex 执行失败，正式状态未确认写入。"
            ),
            "next_action": (
                "额度恢复后重新运行同一章节。"
                if usage_limited else f"检查日志 {event_path}"
            ),
            "external_blocker": usage_limited,
            "elapsed_seconds": elapsed,
        }
    if not result_path.exists():
        raise RuntimeError("Codex 成功退出但未生成结构化结果")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["elapsed_seconds"] = elapsed
    result["event_log"] = str(event_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex 长篇小说无人值守监督器")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--start", type=int, help="起始章；默认从 checkpoint 的下一章开始")
    parser.add_argument("--chapters", type=int, help="本批章数；默认读取 batch_size")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不调用 Codex")
    args = parser.parse_args()

    config = Config.load(args.config)
    checkpoint = load_checkpoint()
    start = args.start or int(checkpoint["last_committed_chapter"]) + 1
    count = args.chapters or config.batch_size
    if start < 1 or not 1 <= count <= 20:
        parser.error("start >= 1，chapters 必须在 1-20 之间")

    with ProcessLock():
        for chapter in range(start, start + count):
            result = run_chapter(chapter, config, args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            if args.dry_run:
                continue

            committed = result.get("status") == "committed" and result.get("committed") is True
            checkpoint["runs"].append({
                "chapter": chapter,
                "status": result.get("status"),
                "at": utc_now(),
                "result": result,
            })
            checkpoint["runs"] = checkpoint["runs"][-100:]
            external_blocker = result.get("external_blocker") is True
            if committed:
                checkpoint["last_committed_chapter"] = chapter
                checkpoint["consecutive_failures"] = 0
            elif external_blocker:
                pass
            else:
                checkpoint["consecutive_failures"] += 1
            atomic_json(CHECKPOINT, checkpoint)

            if result.get("status") == "halted" and config.stop_on_halted:
                return 2
            if checkpoint["consecutive_failures"] >= config.max_consecutive_failures:
                return 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        print(f"章节执行超时，已安全停止: {exc}", file=sys.stderr)
        raise SystemExit(4)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"监督器错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
