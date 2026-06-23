#!/usr/bin/env python3
"""Build a bounded, chapter-local context packet for the writing agent."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "book"
RUNTIME = BOOK / ".novel-supervisor"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def bounded(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n……（上下文包已截断）"


def chapter_outline(chapter: int) -> str:
    for path in sorted((BOOK / "大纲").glob("*详细大纲.md")):
        text = path.read_text(encoding="utf-8")
        pattern = rf"(?ms)^### 第{chapter}章：.*?(?=^### 第\d+章：|\Z)"
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return ""


def recent_summaries(chapter: int, limit: int = 3) -> list[str]:
    summary_dir = BOOK / ".webnovel" / "summaries"
    candidates: list[tuple[int, Path]] = []
    if summary_dir.exists():
        for path in summary_dir.glob("*"):
            match = re.search(r"(\d+)", path.name)
            if match and int(match.group(1)) < chapter and path.is_file():
                candidates.append((int(match.group(1)), path))
    return [
        bounded(path.read_text(encoding="utf-8", errors="replace"), 900)
        for _, path in sorted(candidates)[-limit:]
    ]


def previous_chapter_tail(chapter: int) -> str:
    if chapter <= 1:
        return ""
    candidates = sorted((BOOK / "正文").glob(f"第{chapter - 1:04d}章*.md"))
    if not candidates:
        candidates = sorted((BOOK / "正文").glob(f"第{chapter - 1}章*.md"))
    if not candidates:
        return ""
    text = candidates[-1].read_text(encoding="utf-8", errors="replace")
    return text[-700:].strip()


def setting_digest() -> str:
    parts = []
    for name, limit in (
        ("主角卡.md", 1800),
        ("力量体系.md", 1600),
        ("世界观.md", 1600),
    ):
        path = BOOK / "设定集" / name
        if path.exists():
            parts.append(f"### {name}\n{bounded(path.read_text(encoding='utf-8'), limit)}")
    return "\n\n".join(parts)


def build_packet(chapter: int) -> Path:
    contract_path = BOOK / ".story-system" / "chapters" / f"chapter_{chapter:03d}.json"
    contract = read_json(contract_path, {})
    directive = contract.get("chapter_directive", {})
    state = read_json(BOOK / ".webnovel" / "state.json", {})
    project = state.get("project_info", {})
    threads = state.get("plot_threads", {})
    title_match = re.search(rf"^### 第{chapter}章：(.+)$", chapter_outline(chapter), re.M)
    title = title_match.group(1).strip() if title_match else f"第{chapter}章"
    chapter_file = f"正文/第{chapter:04d}章-{title}.md"

    packet = {
        "packet_version": 1,
        "chapter": chapter,
        "title": title,
        "chapter_file": chapter_file,
        "project": {
            "title": project.get("title", ""),
            "genre": project.get("genre_label") or project.get("genre", ""),
            "platform": project.get("platform", ""),
            "core_selling_points": project.get("core_selling_points", ""),
        },
        "directive": directive,
        "outline": chapter_outline(chapter),
        "setting_digest": setting_digest(),
        "continuity": {
            "protagonist_state": state.get("protagonist_state", {}),
            "active_threads": threads.get("active_threads", [])[-12:],
            "foreshadowing": threads.get("foreshadowing", [])[-12:],
            "recent_summaries": recent_summaries(chapter),
            "previous_chapter_tail": previous_chapter_tail(chapter),
        },
        "quality": {
            "target_chinese_chars": [2000, 3000],
            "hard_requirements": [
                "正文汉字数必须在 2000–3000 之间，范围外禁止提交",
                "覆盖全部 must_cover_nodes，missed_nodes 必须为空",
                "不进入 forbidden_zones",
                "人物知识边界、时间线、因果链一致",
                "自然中文叙事，避免总结腔、模板腔和重复解释",
                "章末兑现 CEN 并留下 chapter_end_open_question",
            ],
            "score_threshold": 80,
        },
        "artifact_contract": {
            "review_results.json": {
                "chapter": chapter,
                "issues": [],
                "issues_count": 0,
                "blocking_count": 0,
                "has_blocking": False,
                "summary": "必须填写真实自审摘要",
            },
            "fulfillment_result.json": {
                "planned_nodes": directive.get("must_cover_nodes", []),
                "covered_nodes": "逐项填写实际覆盖节点",
                "missed_nodes": [],
                "extra_nodes": [],
            },
            "disambiguation_result.json": {"pending": []},
            "extraction_result.json": {
                "accepted_events": [
                    {
                        "event_id": f"evt-ch{chapter:03d}-001",
                        "chapter": chapter,
                        "event_type": "open_loop_created",
                        "subject": "稳定实体ID",
                        "payload": {
                            "content": "悬念事实",
                            "unanswered_question": "未解问题",
                        },
                    }
                ],
                "state_deltas": [
                    {
                        "entity_id": "稳定实体ID",
                        "field": "location.current",
                        "old": "旧值",
                        "new": "新值",
                    }
                ],
                "entity_deltas": [
                    {
                        "entity_id": "稳定实体ID",
                        "action": "upsert",
                        "entity_type": "角色",
                        "payload": {"name": "实体名"},
                    }
                ],
                "entities_appeared": [
                    {
                        "id": "稳定实体ID",
                        "type": "角色",
                        "mentions": ["正文称呼"],
                        "confidence": 0.95,
                    }
                ],
                "scenes": [
                    {
                        "index": 1,
                        "start_line": 1,
                        "end_line": 1,
                        "location": "地点",
                        "summary": "场景摘要",
                        "characters": ["稳定实体ID"],
                    }
                ],
                "summary_text": "100-150字事实摘要",
            },
        },
        "commands": {
            "cli": "../.venv/bin/python -X utf8 ../vendor/webnovel-writer/webnovel-writer/scripts/webnovel.py --project-root \"$PWD\"",
            "prewrite": f"write-gate --chapter {chapter} --stage prewrite --format json",
            "precommit": f"write-gate --chapter {chapter} --stage precommit --format json",
            "commit": (
                f"chapter-commit --chapter {chapter} "
                "--review-result .webnovel/tmp/review_results.json "
                "--fulfillment-result .webnovel/tmp/fulfillment_result.json "
                "--disambiguation-result .webnovel/tmp/disambiguation_result.json "
                "--extraction-result .webnovel/tmp/extraction_result.json"
            ),
            "postcommit": f"write-gate --chapter {chapter} --stage postcommit --format json",
        },
    }
    target = RUNTIME / "context" / f"chapter-{chapter:04d}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="生成轻量章节上下文包")
    parser.add_argument("--chapter", type=int, required=True)
    args = parser.parse_args()
    path = build_packet(args.chapter)
    print(path)
    print(f"chars={len(path.read_text(encoding='utf-8'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
