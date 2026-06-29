#!/usr/bin/env python3
"""Supervisor: batch orchestrator with checkpoint, lock, retry, and halt."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import EngineConfig
from .gate_runner import GateRunner
from .llm_client import LLMClient
from .packet_reader import PacketReader
from .reviewer import ReviewerAgent
from .writer import WriterAgent


@dataclass
class Checkpoint:
    schema_version: int = 1
    last_committed_chapter: int = 0
    consecutive_failures: int = 0
    runs: list[dict[str, Any]] = None

    def __post_init__(self):
        if self.runs is None:
            self.runs = []

    @classmethod
    def load(cls, path: Path) -> "Checkpoint":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            schema_version=data.get("schema_version", 1),
            last_committed_chapter=data.get("last_committed_chapter", 0),
            consecutive_failures=data.get("consecutive_failures", 0),
            runs=data.get("runs", []),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "last_committed_chapter": self.last_committed_chapter,
                    "consecutive_failures": self.consecutive_failures,
                    "runs": self.runs,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)


class ProcessLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path

    def _is_stale(self) -> bool:
        """Check if lock file is stale (process no longer exists)."""
        if not self.lock_path.exists():
            return True
        try:
            pid = int(self.lock_path.read_text(encoding="utf-8").strip())
            # Check if process exists
            os.kill(pid, 0)
            return False  # Process exists, lock is valid
        except (ValueError, OSError, ProcessLookupError):
            return True  # Lock is stale

    def __enter__(self) -> "ProcessLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Clean stale lock
        if self.lock_path.exists() and self._is_stale():
            self.lock_path.unlink(missing_ok=True)
            
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            # Double-check if it's really stale
            if self._is_stale():
                self.lock_path.unlink(missing_ok=True)
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise RuntimeError(
                    f"监督器已在运行；若确认是残留锁，请删除 {self.lock_path}"
                ) from exc
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        return self

    def __exit__(self, *_: object) -> None:
        self.lock_path.unlink(missing_ok=True)


class Supervisor:
    def __init__(self, config: EngineConfig, max_runtime: int = 600):
        self.config = config
        self.max_runtime = max_runtime
        self.root = config.project_root
        self.supervisor_dir = config.supervisor_dir
        self.checkpoint_path = self.supervisor_dir / "checkpoint.json"
        self.lock_path = self.supervisor_dir / "lock"
        self.logs_dir = self.supervisor_dir / "logs"
        self.context_dir = self.supervisor_dir / "context"
        self.tmp_dir = config.webnovel_dir / "tmp"

        self.client = LLMClient(
            config.base_url,
            config.api_key,
            config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        self.writer = WriterAgent(self.client, config)
        self.reviewer = ReviewerAgent(self.client, config)
        self.gate = GateRunner(config)

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_context_packet(self, chapter: int) -> Path:
        """Ensure context packet exists; build it if not."""
        packet_path = self.context_dir / f"chapter-{chapter:04d}.json"
        if packet_path.exists():
            return packet_path
        # Build packet using context_pack.py
        import subprocess

        build_script = self.root.parent / "context_pack.py"
        proc = subprocess.run(
            [
                str(self.config.vendor_python),
                str(build_script),
                "--chapter",
                str(chapter),
            ],
            capture_output=True,
            text=True,
            cwd=self.root.parent,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"context_pack failed: {proc.stderr}")
        if not packet_path.exists():
            raise RuntimeError(f"context_pack did not create {packet_path}")
        return packet_path

    def _save_artifacts(self, chapter: int, artifacts: dict[str, Any]) -> dict[str, Path]:
        """Save review/fulfillment/disambiguation/extraction JSON to tmp dir."""
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for name, key in [
            ("review_results.json", "review"),
            ("fulfillment_result.json", "fulfillment"),
            ("disambiguation_result.json", "disambiguation"),
            ("extraction_result.json", "extraction"),
        ]:
            path = self.tmp_dir / name
            data = artifacts.get(key, {})
            # For review, flatten to the expected schema
            if key == "review":
                data = {
                    "blocking_count": len(data.get("blocking_issues", [])),
                    "issues": data.get("issues", []),
                    "issues_count": len(data.get("issues", [])),
                    "has_blocking": data.get("hard_pass", True) is False,
                    "summary": data.get("summary", ""),
                }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            paths[name] = path
        return paths

    def _save_chapter_file(self, chapter_file: str, body: str) -> Path:
        """Save chapter markdown to 正文/."""
        target = self.root / chapter_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body + "\n", encoding="utf-8")
        return target

    def run_chapter(self, chapter: int, dry_run: bool = False) -> dict[str, Any]:
        """Run one chapter through the full pipeline."""
        logs = self.logs_dir
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        event_path = logs / f"chapter-{chapter:04d}-{stamp}.events.jsonl"
        result_path = logs / f"chapter-{chapter:04d}-{stamp}.result.json"

        events: list[dict[str, Any]] = []
        chapter_start = time.monotonic()

        def check_timeout(step: str) -> dict[str, Any] | None:
            elapsed = time.monotonic() - chapter_start
            if elapsed > self.max_runtime:
                log_event("timeout", "halt", {"elapsed": round(elapsed, 1), "limit": self.max_runtime})
                return self._build_result(
                    chapter, "halted", False, events, event_path, result_path,
                    chapter_start,
                    issues=[f"单章运行超时 ({round(elapsed, 1)}s > {self.max_runtime}s)"],
                    next_action="增加 max_runtime 或检查 LLM 响应速度",
                    elapsed=elapsed,
                    error_category="transient",
                )
            return None

        def log_event(step: str, status: str, data: dict[str, Any] | None = None) -> None:
            entry = {
                "at": self._utc_now(),
                "chapter": chapter,
                "step": step,
                "status": status,
            }
            if data:
                entry["data"] = data
            events.append(entry)
            # Also emit to stdout for platform real-time consumption
            print(json.dumps(entry, ensure_ascii=False), flush=True)

        if dry_run:
            packet_path = self._ensure_context_packet(chapter)
            return {
                "status": "dry-run",
                "chapter": chapter,
                "packet_path": str(packet_path),
                "packet_chars": len(packet_path.read_text(encoding="utf-8")),
            }

        started = time.monotonic()

        try:
            # Step 0: Ensure contracts exist
            from .contract_builder import ContractBuilder
            builder = ContractBuilder(self.root)
            builder.ensure_contracts(chapter)
            log_event("contracts", "ok")
            if (timeout_result := check_timeout("contracts")):
                return timeout_result

            # Step 1: Ensure context packet
            packet_path = self._ensure_context_packet(chapter)
            log_event("context_packet", "ok", {"path": str(packet_path)})
            if (timeout_result := check_timeout("context_packet")):
                return timeout_result

            # Step 2: prewrite gate
            prewrite = self.gate.prewrite(chapter)
            log_event("prewrite", "pass" if prewrite.get("ok") else "fail", prewrite)
            if not prewrite.get("ok"):
                return self._build_result(
                    chapter, "retryable", False, events, event_path, result_path,
                    started, issues=["prewrite gate 失败"], next_action="修复 prewrite 错误后重试",
                    error_category="transient",
                )

            # Step 3: Write draft
            draft = self.writer.write(packet_path)
            log_event("write", "ok", {
                "chinese_chars": draft["chinese_chars"],
                "title": draft["title"],
            })
            if (timeout_result := check_timeout("write")):
                return timeout_result

            # Step 4: Review + revision loop (blocking issues)
            body = draft["body"]
            revision_count = 0
            for revision in range(self.config.max_revisions + 1):
                review_result = self.reviewer.review(packet_path, body)
                log_event("review", "ok" if review_result["hard_pass"] else "fail", {
                    "revision": revision,
                    "scores": review_result["scores"],
                    "hard_pass": review_result["hard_pass"],
                    "blocking_count": len(review_result["blocking_issues"]),
                    "ai_traces": review_result.get("ai_traces", []),
                })
                if (timeout_result := check_timeout("review")):
                    return timeout_result

                if review_result["hard_pass"]:
                    break

                if revision < self.config.max_revisions:
                    issues = review_result["blocking_issues"] + review_result["issues"]
                    body = self.writer.revise(packet_path, body, issues)["body"]
                    revision_count += 1
                    log_event("revise", "ok", {"revision": revision_count})
                else:
                    # Max revisions reached, still failing
                    return self._build_result(
                        chapter, "retryable", False, events, event_path, result_path,
                        started,
                        issues=review_result["blocking_issues"] + review_result["issues"],
                        next_action="返工次数耗尽，需要人工干预",
                        quality_gate={
                            "hard_pass": False,
                            "revision_count": revision_count,
                            "scores": review_result["scores"],
                        },
                        error_category="content",
                    )

            # Step 4a: Elevate (if any score below 70 or AI traces found)
            scores = review_result.get("scores", {})
            min_score = min(scores.values()) if scores else 100
            ai_traces = review_result.get("ai_traces", [])
            if min_score < 70 or ai_traces:
                log_event("elevate", "needed", {"min_score": min_score, "ai_traces_count": len(ai_traces)})
                elevate_prompt = f"""以下是你写的正文。审查发现以下问题：

AI痕迹：{ai_traces}
最低分维度：{[k for k, v in scores.items() if v < 70]}

请执行 Elevate 步骤：
1. 找出正文中最好的3个句子
2. 把全章剩余部分提升到同一水平
3. 消除所有AI痕迹（TELL→SHOW、删除填充句、削减解释）
4. 保持原有情节和结构不变

正文：
{body}

只返回修改后的完整正文（标题+正文），不要返回分析。"""
                body = self.writer.revise(packet_path, body, ["Elevate: " + elevate_prompt[:200]])["body"]
                log_event("elevate", "ok")
                # Re-review after elevate
                review_result = self.reviewer.review(packet_path, body)
                log_event("review_post_elevate", "ok" if review_result["hard_pass"] else "fail", {
                    "scores": review_result["scores"],
                    "hard_pass": review_result["hard_pass"],
                })

            # Step 4b: Fulfillment check + fix loop (missed nodes)
            for fix_attempt in range(3):
                fulfillment = self.reviewer.fulfillment(packet_path, body)
                missed = fulfillment.get("missed_nodes", [])
                log_event("fulfillment", "ok" if not missed else "fix_needed", {
                    "missed_nodes": missed,
                    "attempt": fix_attempt,
                })
                if not missed:
                    break
                if fix_attempt < 2:
                    fix_prompt = f"正文中遗漏了以下关键节点，请补充：{missed}。保持原有情节和风格不变，只增加必要的段落来覆盖这些节点。"
                    body = self.writer.revise(packet_path, body, [fix_prompt])["body"]
                    log_event("fulfill_fix", "ok", {"attempt": fix_attempt + 1, "missed": missed})
                else:
                    return self._build_result(
                        chapter, "retryable", False, events, event_path, result_path,
                        started,
                        issues=[f"遗漏节点: {missed}"],
                        next_action="修复遗漏节点后重试",
                        quality_gate={
                            "hard_pass": False,
                            "revision_count": revision_count,
                            "scores": review_result["scores"],
                        },
                        error_category="content",
                    )

            # Step 5: Save chapter file
            self._save_chapter_file(draft["chapter_file"], body)
            log_event("save_chapter", "ok", {"path": draft["chapter_file"], "chars": review_result["chinese_chars"]})

            # Step 6: Disambiguation / extraction
            artifacts = self.reviewer.full_review(packet_path, body)
            log_event("artifacts", "ok", {
                "missed_nodes": artifacts["fulfillment"].get("missed_nodes", []),
                "pending": artifacts["disambiguation"].get("pending", []),
                "ai_traces": artifacts["review"].get("ai_traces", []),
            })
            if (timeout_result := check_timeout("artifacts")):
                return timeout_result

            # Step 6a: Self-Absorption (learn from this chapter)
            self._self_absorb(chapter, review_result, artifacts)
            log_event("self_absorb", "ok")

            # Check disambiguation pending only
            pending = artifacts["disambiguation"].get("pending", [])
            if pending:
                return self._build_result(
                    chapter, "retryable", False, events, event_path, result_path,
                    started,
                    issues=[f"待消歧: {pending}"],
                    next_action="修复消歧后重试",
                    quality_gate={
                        "hard_pass": False,
                        "revision_count": revision_count,
                        "scores": review_result["scores"],
                    },
                    error_category="content",
                )

            # Step 7: Save artifacts to tmp
            artifact_paths = self._save_artifacts(chapter, artifacts)
            log_event("save_artifacts", "ok", {k: str(v) for k, v in artifact_paths.items()})
            if (timeout_result := check_timeout("save_artifacts")):
                return timeout_result

            # Step 8: precommit gate
            precommit = self.gate.precommit(chapter)
            log_event("precommit", "pass" if precommit.get("ok") else "fail", precommit)
            if not precommit.get("ok"):
                return self._build_result(
                    chapter, "retryable", False, events, event_path, result_path,
                    started, issues=["precommit gate 失败"], next_action="修复 precommit 错误后重试",
                    quality_gate={
                        "hard_pass": False,
                        "revision_count": revision_count,
                        "scores": review_result["scores"],
                    },
                    error_category="config",
                )

            # Step 9: chapter-commit
            commit = self.gate.commit(
                chapter,
                artifact_paths["review_results.json"],
                artifact_paths["fulfillment_result.json"],
                artifact_paths["disambiguation_result.json"],
                artifact_paths["extraction_result.json"],
            )
            log_event("commit", "ok" if commit.get("returncode") == 0 else "fail", commit)
            if commit.get("returncode") != 0:
                return self._build_result(
                    chapter, "retryable", False, events, event_path, result_path,
                    started, issues=["chapter-commit 失败"], next_action="修复 commit 错误后重试",
                    quality_gate={
                        "hard_pass": False,
                        "revision_count": revision_count,
                        "scores": review_result["scores"],
                    },
                    error_category="config",
                )

            # Step 10: postcommit gate
            postcommit = self.gate.postcommit(chapter)
            log_event("postcommit", "pass" if postcommit.get("ok") else "fail", postcommit)
            if not postcommit.get("ok"):
                return self._build_result(
                    chapter, "retryable", False, events, event_path, result_path,
                    started, issues=["postcommit gate 失败"], next_action="修复 postcommit 错误后重试",
                    quality_gate={
                        "hard_pass": False,
                        "revision_count": revision_count,
                        "scores": review_result["scores"],
                    },
                    error_category="transient",
                )

            # Success
            elapsed = round(time.monotonic() - started, 2)
            return self._build_result(
                chapter, "committed", True, events, event_path, result_path,
                started,
                issues=[],
                next_action="继续下一章",
                quality_gate={
                    "hard_pass": True,
                    "revision_count": revision_count,
                    "scores": review_result["scores"],
                },
                elapsed=elapsed,
                commit=commit,
                error_category=None,
            )

        except Exception as exc:
            elapsed = round(time.monotonic() - started, 2)
            log_event("error", "exception", {"error": str(exc)})
            return self._build_result(
                chapter, "retryable", False, events, event_path, result_path,
                started,
                issues=[f"异常: {exc}"],
                next_action=f"检查日志 {event_path}",
                elapsed=elapsed,
                error_category="transient",
            )

    def _self_absorb(self, chapter: int, review_result: dict[str, Any], artifacts: dict[str, Any]) -> None:
        """Save chapter lessons to memory for future chapters."""
        memory_path = self.supervisor_dir / "memory.json"
        memory: list[dict[str, Any]] = []
        if memory_path.exists():
            memory = json.loads(memory_path.read_text(encoding="utf-8"))
        
        # Extract lessons from review
        scores = review_result.get("scores", {})
        ai_traces = review_result.get("ai_traces", [])
        role_feedback = review_result.get("role_feedback", {})
        
        lesson = {
            "chapter": chapter,
            "at": self._utc_now(),
            "scores": scores,
            "ai_traces": ai_traces,
            "lessons": [],
        }
        
        # Build lessons from low scores
        for dim, score in scores.items():
            if score < 70:
                lesson["lessons"].append(f"{dim}: {score}分 - 需要改进")
        
        # Add AI trace lessons
        for trace in ai_traces:
            lesson["lessons"].append(f"AI痕迹: {trace}")
        
        # Add role feedback as lessons
        for role, feedback in role_feedback.items():
            if feedback and len(feedback) > 10:
                lesson["lessons"].append(f"{role}: {feedback}")
        
        # Add fulfillment lessons
        missed = artifacts.get("fulfillment", {}).get("missed_nodes", [])
        if missed:
            lesson["lessons"].append(f"遗漏节点: {missed}")
        
        memory.append(lesson)
        memory = memory[-20:]  # Keep last 20 chapters
        memory_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_memory(self) -> list[dict[str, Any]]:
        """Load memory for next chapter."""
        memory_path = self.supervisor_dir / "memory.json"
        if memory_path.exists():
            return json.loads(memory_path.read_text(encoding="utf-8"))
        return []
    def _build_result(
        self,
        chapter: int,
        status: str,
        committed: bool,
        events: list[dict[str, Any]],
        event_path: Path,
        result_path: Path,
        started: float,
        issues: list[str] | None = None,
        next_action: str = "",
        quality_gate: dict[str, Any] | None = None,
        elapsed: float = 0,
        commit: dict[str, Any] | None = None,
        error_category: str | None = None,
    ) -> dict[str, Any]:
        if elapsed == 0:
            elapsed = round(time.monotonic() - started, 2)
        if issues is None:
            issues = []
        if quality_gate is None:
            quality_gate = {
                "hard_pass": False,
                "revision_count": 0,
                "scores": {},
            }

        result = {
            "status": status,
            "chapter": chapter,
            "committed": committed,
            "quality_gate": quality_gate,
            "issues": issues,
            "summary": f"第 {chapter} 章 {status}",
            "next_action": next_action,
            "elapsed_seconds": elapsed,
            "event_log": str(event_path),
            "commit": commit or {},
            "error_category": error_category,
        }

        # Save result
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Save events
        with event_path.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

        return result

    def run_batch(self, start: int, count: int, dry_run: bool = False) -> list[dict[str, Any]]:
        """Run a batch of chapters with automatic retry for transient failures."""
        checkpoint = Checkpoint.load(self.checkpoint_path)
        if start < 1:
            start = checkpoint.last_committed_chapter + 1
        if not 1 <= count <= 20:
            raise ValueError("count must be 1-20")

        results: list[dict[str, Any]] = []

        with ProcessLock(self.lock_path):
            for chapter in range(start, start + count):
                max_retries = 3 if not dry_run else 0
                attempt = 0
                result = None

                while attempt <= max_retries:
                    result = self.run_chapter(chapter, dry_run=dry_run)

                    # Retry only transient errors
                    if result.get("status") == "committed":
                        break
                    category = result.get("error_category")
                    if category != "transient":
                        break
                    attempt += 1
                    if attempt <= max_retries:
                        print(json.dumps({
                            "at": self._utc_now(),
                            "chapter": chapter,
                            "step": "retry",
                            "status": "scheduled",
                            "data": {"attempt": attempt, "max": max_retries, "reason": category},
                        }, ensure_ascii=False), flush=True)

                results.append(result)

                if dry_run:
                    continue

                # Update checkpoint
                committed = result.get("status") == "committed" and result.get("committed") is True
                checkpoint.runs.append({
                    "chapter": chapter,
                    "status": result.get("status"),
                    "at": self._utc_now(),
                    "result": result,
                })
                checkpoint.runs = checkpoint.runs[-100:]
                if committed:
                    checkpoint.last_committed_chapter = chapter
                    checkpoint.consecutive_failures = 0
                else:
                    checkpoint.consecutive_failures += 1
                checkpoint.save(self.checkpoint_path)

                # Halt conditions
                if result.get("status") == "halted" and self.config.stop_on_halted:
                    break
                if checkpoint.consecutive_failures >= self.config.max_consecutive_failures:
                    break

        return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Novel Codex Engine Supervisor")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--start", type=int, help="起始章；默认从 checkpoint 下一章")
    parser.add_argument("--chapters", type=int, help="本批章数")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不调用 LLM")
    args = parser.parse_args()

    config = EngineConfig.load(args.config)
    supervisor = Supervisor(config)

    start = args.start or 1
    count = args.chapters or config.batch_size
    results = supervisor.run_batch(start, count, dry_run=args.dry_run)
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))
