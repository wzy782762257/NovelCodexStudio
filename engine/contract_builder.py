#!/usr/bin/env python3
"""Build chapter contracts from outline if missing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ContractBuilder:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.outline_dir = self.project_root / "大纲"
        self.chapters_dir = self.project_root / ".story-system" / "chapters"
        self.reviews_dir = self.project_root / ".story-system" / "reviews"

    def _find_outline(self) -> Path | None:
        for path in sorted(self.outline_dir.glob("*详细大纲.md")):
            return path
        return None

    def _extract_chapter_section(self, text: str, chapter: int) -> str:
        pattern = rf"(?ms)^### 第{chapter}章[：:].*?(?=^### 第\d+章[：:]|\Z)"
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
        return ""

    def _parse_field(self, section: str, field_name: str) -> str:
        pattern = rf"(?m)^-?\s*{re.escape(field_name)}[：:]\s*(.+)$"
        match = re.search(pattern, section)
        if match:
            return match.group(1).strip()
        return ""

    def _parse_cpn_list(self, section: str) -> list[str]:
        lines = section.splitlines()
        in_cpns = False
        cpns = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("CPNs") or stripped.startswith("- CPNs"):
                in_cpns = True
                continue
            if in_cpns:
                # CPN items are indented (2+ spaces or tab); stop at top-level bullet
                if line.startswith("  - ") or line.startswith("\t- "):
                    cpns.append(line.strip()[2:].strip())
                elif line.startswith("- "):
                    break
                elif stripped == "":
                    continue
                else:
                    break
        return cpns

    def _parse_key_entities(self, section: str) -> list[str]:
        val = self._parse_field(section, "关键实体")
        if not val:
            return []
        items = [item.strip().rstrip("。.") for item in re.split(r"[、，；;]", val) if item.strip()]
        return items

    def _parse_nodes(self, section: str) -> list[str]:
        val = self._parse_field(section, "必须覆盖节点")
        if not val:
            return []
        return [item.strip() for item in re.split(r"[、，]", val) if item.strip()]

    def _parse_forbidden(self, section: str) -> list[str]:
        val = self._parse_field(section, "本章禁区")
        if not val:
            val = self._parse_field(section, "禁区")
        if not val:
            return []
        return [item.strip() for item in re.split(r"[；;]", val) if item.strip()]

    def build_chapter_contract(self, chapter: int) -> dict[str, Any] | None:
        outline_path = self._find_outline()
        if not outline_path:
            return None
        text = outline_path.read_text(encoding="utf-8")
        section = self._extract_chapter_section(text, chapter)
        if not section:
            return None

        # Extract title
        title_match = re.search(rf"(?m)^### 第{chapter}章[：:]\s*(.+)$", section)
        title = title_match.group(1).strip() if title_match else f"第{chapter}章"

        directive = {
            "time_anchor": self._parse_field(section, "时间锚点"),
            "chapter_span": self._parse_field(section, "章内跨度"),
            "countdown": self._parse_field(section, "倒计时状态"),
            "goal": self._parse_field(section, "目标"),
            "strand": self._parse_field(section, "Strand"),
            "antagonist_tier": self._parse_field(section, "反派层级"),
            "key_entities": self._parse_key_entities(section),
            "chapter_end_open_question": self._parse_field(section, "章末未闭合问题"),
            "cbn": self._parse_field(section, "CBN"),
            "cpns": self._parse_cpn_list(section),
            "cen": self._parse_field(section, "CEN"),
            "must_cover_nodes": self._parse_nodes(section),
            "forbidden_zones": self._parse_forbidden(section),
            "source": "chapter_outline",
        }

        # Clean empty values
        for key in list(directive.keys()):
            if directive[key] == "" or directive[key] == []:
                if key in ("key_entities", "cpns", "must_cover_nodes", "forbidden_zones"):
                    directive[key] = []
                else:
                    directive.pop(key, None)

        return {
            "meta": {
                "schema_version": "story-system/v1",
                "contract_type": "CHAPTER_BRIEF",
                "generator_version": "outline_extractor",
                "chapter": chapter,
            },
            "override_allowed": {
                "chapter_focus": directive.get("goal", "")
            },
            "chapter_directive": directive,
        }

    def build_review_contract(self, chapter: int) -> dict[str, Any] | None:
        outline_path = self._find_outline()
        if not outline_path:
            return None
        text = outline_path.read_text(encoding="utf-8")
        section = self._extract_chapter_section(text, chapter)
        if not section:
            return None

        blocking_rules = self._parse_forbidden(section)
        must_cover = self._parse_nodes(section)

        return {
            "meta": {
                "schema_version": "story-system/v1",
                "contract_type": "REVIEW_CONTRACT",
                "generator_version": "outline_extractor",
                "chapter": chapter,
            },
            "must_cover_nodes": must_cover,
            "blocking_rules": blocking_rules,
        }

    def ensure_contracts(self, chapter: int) -> tuple[Path, Path]:
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        self.reviews_dir.mkdir(parents=True, exist_ok=True)

        chapter_path = self.chapters_dir / f"chapter_{chapter:03d}.json"
        review_path = self.reviews_dir / f"chapter_{chapter:03d}.review.json"

        if not chapter_path.exists():
            contract = self.build_chapter_contract(chapter)
            if contract:
                chapter_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                raise RuntimeError(f"无法从大纲提取第 {chapter} 章契约")

        if not review_path.exists():
            review = self.build_review_contract(chapter)
            if review:
                review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                raise RuntimeError(f"无法从大纲提取第 {chapter} 章审查契约")

        return chapter_path, review_path


if __name__ == "__main__":
    import sys
    builder = ContractBuilder(Path("book"))
    chapter = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    cp, rp = builder.ensure_contracts(chapter)
    print(f"Chapter contract: {cp}")
    print(f"Review contract: {rp}")
    print(f"Chapter content preview:")
    print(json.dumps(json.loads(cp.read_text(encoding="utf-8")), ensure_ascii=False, indent=2)[:1000])
