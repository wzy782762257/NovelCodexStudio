#!/usr/bin/env python3
"""Read context packet and build writing prompts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PacketReader:
    def __init__(self, packet_path: Path):
        self.packet_path = packet_path
        self.packet = json.loads(packet_path.read_text(encoding="utf-8"))
        # Load voice kit from project supervisor dir
        self.project_root = packet_path.parent.parent.parent  # context/ -> .novel-supervisor/ -> book/
        self.voice_kit_path = self.project_root / ".novel-supervisor" / "voice-kit.json"
        self.constraints_path = self.project_root / ".novel-supervisor" / "constraints.json"
        self._voice_kit = self._load_voice_kit()
        self._constraints = self._load_constraints()

    def _load_voice_kit(self) -> dict[str, Any]:
        if self.voice_kit_path.exists():
            return json.loads(self.voice_kit_path.read_text(encoding="utf-8"))
        return {}

    def _load_constraints(self) -> dict[str, Any]:
        if self.constraints_path.exists():
            return json.loads(self.constraints_path.read_text(encoding="utf-8"))
        return {}

    def _load_memory(self) -> list[dict[str, Any]]:
        """Load lessons from previous chapters."""
        memory_path = self.project_root / ".novel-supervisor" / "memory.json"
        if memory_path.exists():
            return json.loads(memory_path.read_text(encoding="utf-8"))
        return []

    def _get_voice_kit_section(self) -> str:
        vk = self._voice_kit.get("voice_kit", {})
        lines = ["【声音DNA - 必须遵守】"]
        lines.append(f"节奏: {vk.get('rhythm', '未配置')}")
        lines.append(f"比喻密度: {vk.get('metaphor_density', '未配置')}")
        lines.append(f"标点风格: {vk.get('punctuation', '未配置')}")
        lines.append(f"感官系统: {vk.get('sensory', '未配置')}")
        lines.append(f"意象系统: {vk.get('image_system', '未配置')}")
        lines.append(f"情感基调: {vk.get('emotional_register', '未配置')}")
        lines.append(f"声音频率: {vk.get('frequency', '未配置')}")
        lines.append("")
        lines.append("【声音规则 - 不可违反】")
        for rule in vk.get("voice_rules", []):
            lines.append(f"- {rule}")
        lines.append("")
        lines.append("【DNA样本 - 写作时必须模仿此风格】")
        lines.append(vk.get("dna_sample", ""))
        return "\n".join(lines)

    def _get_skeleton_key(self) -> str:
        """Extract the one-sentence core from CBN + CEN."""
        directive = self._directive()
        cbn = directive.get("cbn", "")
        cen = directive.get("cen", "")
        goal = directive.get("goal", "")
        if cbn and cen:
            return f"从「{cbn}」到「{cen}」，核心目标：{goal}"
        return goal or "推进主线"

    def _get_tempo(self) -> str:
        """Infer tempo from chapter position and intensity."""
        directive = self._directive()
        chapter = self.chapter()
        # Simple heuristic: early chapters = build, late = peak, every 3rd = recover
        if chapter <= 3:
            intensity = "3/10"
            tempo = "蓄力"
        elif chapter % 3 == 0:
            intensity = "5/10"
            tempo = "缓冲"
        elif chapter % 5 == 0:
            intensity = "9/10"
            tempo = "高潮"
        else:
            intensity = "6/10"
            tempo = "推进"
        # Override with directive if present
        if "intensity" in directive:
            intensity = str(directive["intensity"])
        if "tempo" in directive:
            tempo = str(directive["tempo"])
        return f"强度 {intensity}，节奏 {tempo}"

    def _get_chapter_constraints(self) -> str:
        """Get 3 MUST / 3 FORBIDDEN for this chapter."""
        directive = self._directive()
        # Chapter-specific constraints from directive
        must = list(directive.get("must", []))
        forbidden = list(directive.get("forbidden", []))
        # Global constraints
        global_must = self._constraints.get("global_constraints", {}).get("must", [])
        global_forbidden = self._constraints.get("global_constraints", {}).get("forbidden", [])
        # Select chapter constraints from library based on tempo
        tempo = self._get_tempo()
        library = self._constraints.get("constraint_library", [])
        selected = None
        for item in library:
            if item.get("id") in tempo.lower() or item.get("name") in tempo:
                selected = item
                break
        # If no match, pick by chapter position
        if not selected and library:
            if "高潮" in tempo:
                selected = next((i for i in library if i.get("id") == "intensity_peak"), None)
            elif "缓冲" in tempo:
                selected = next((i for i in library if i.get("id") == "intensity_recover"), None)
            elif "蓄力" in tempo:
                selected = next((i for i in library if i.get("id") == "intensity_build"), None)
        # Build constraints
        all_must = list(global_must)
        all_forbidden = list(global_forbidden)
        if selected:
            all_must.extend(selected.get("must", []))
            all_forbidden.extend(selected.get("forbidden", []))
        all_must.extend(must)
        all_forbidden.extend(forbidden)
        # Deduplicate and limit to 3 each
        all_must = list(dict.fromkeys(all_must))[:3]
        all_forbidden = list(dict.fromkeys(all_forbidden))[:3]
        lines = ["【3 MUST - 必须做到】"]
        for i, c in enumerate(all_must, 1):
            lines.append(f"{i}. {c}")
        lines.append("")
        lines.append("【3 FORBIDDEN - 绝对禁止】")
        for i, c in enumerate(all_forbidden, 1):
            lines.append(f"{i}. {c}")
        return "\n".join(lines)

    def get(self, key: str, default: Any = None) -> Any:
        return self.packet.get(key, default)

    def chapter(self) -> int:
        return int(self.packet["chapter"])

    def title(self) -> str:
        return str(self.packet.get("title", ""))

    def chapter_file(self) -> str:
        return str(self.packet.get("chapter_file", ""))

    def _directive(self) -> dict[str, Any]:
        return self.packet.get("directive", {}) or {}

    def _outline(self) -> str:
        return self.packet.get("outline", "")

    def _setting_digest(self) -> str:
        return self.packet.get("setting_digest", "")

    def _continuity(self) -> dict[str, Any]:
        return self.packet.get("continuity", {}) or {}

    def _quality(self) -> dict[str, Any]:
        return self.packet.get("quality", {}) or {}

    def system_prompt(self) -> str:
        return f"""你是一位专业中文长篇小说写手。你的任务是根据提供的上下文包写出一章高质量的网文正文。

【声音DNA - 最优先，必须严格遵守】
{self._get_voice_kit_section()}

【字数要求 - 硬性】
正文必须严格控制在 2000–3000 个汉字（不含标点、空格、标题）。这是硬性要求，必须达到。如果情节已经覆盖全部要求，请通过增加细节描写、对话、场景描写、内心独白等方式扩充到 2000 字以上。

【写作流程 - 必须遵循 FORGE+C】
1. 先列出 5-6 个 Beats（节拍），每个 Beat 用一句话概括。Beats 必须覆盖所有必须节点。
2. 然后按 Beats 顺序展开正文。每个 Beat 约 400-600 字。
3. 使用 2-Pass 写作：
   - Pass 1: 快速写出粗稿，只关注动作、决策、冲突。不解释。
   - Pass 2: 保留所有事件，提升节奏、感官细节、对话精度。削减 40% 解释性文字。

【节点覆盖要求】
正文中必须明确覆盖所有"必须覆盖节点"（must_cover_nodes）。每个节点至少需要一个独立的段落或情节来体现，不能一笔带过。

【写作铁律】
1. 自然中文叙事，避免总结腔、模板腔和重复解释。对话要推进关系、信息或决策，不能只复述设定。
2. 每章至少产生一个不可无损删除的信息增量。
3. 章末必须兑现 CEN（章节终局节点），并留下 chapter_end_open_question。
4. 不进入任何 forbidden_zones。
5. 保持人物知识边界、时间线、因果链一致。
6. 严格遵循"声音DNA"中的所有规则和DNA样本风格。

输出格式：
只返回正文 Markdown。标题用 # 开头，后面直接跟正文。不要返回任何分析、评论、JSON、Beats列表或额外说明。"""

    def user_prompt(self) -> str:
        p = self.packet
        directive = self._directive()
        continuity = self._continuity()
        quality = self._quality()
        project = p.get("project", {}) or {}

        lines: list[str] = []
        lines.append(f"# 项目信息")
        lines.append(f"书名：{project.get('title', '')}")
        lines.append(f"题材：{project.get('genre', '')}")
        lines.append(f"平台：{project.get('platform', '')}")
        lines.append(f"核心卖点：{project.get('core_selling_points', '')}")
        lines.append("")
        lines.append(f"# 章节信息")
        lines.append(f"第 {self.chapter()} 章：{self.title()}")
        lines.append("")
        lines.append(f"# 骨架钥匙 (Skeleton Key)")
        lines.append(f"一句话：{self._get_skeleton_key()}")
        lines.append(f"整章存在的理由：从CBN到CEN，只为此一句话。")
        lines.append("")
        lines.append(f"# 节奏脚本 (Tempo Script)")
        lines.append(f"当前章：{self._get_tempo()}")
        lines.append(f"位置：全书第 {self.chapter()} 章，请根据位置调整节奏和悬念强度。")
        lines.append("")
        lines.append(f"# 每章约束")
        lines.append(self._get_chapter_constraints())
        lines.append("")
        lines.append(f"# 章节指令")
        lines.append(f"时间锚点：{directive.get('time_anchor', '')}")
        lines.append(f"章内跨度：{directive.get('chapter_span', '')}")
        lines.append(f"倒计时：{directive.get('countdown', '')}")
        lines.append(f"目标：{directive.get('goal', '')}")
        lines.append(f"Strand：{directive.get('strand', '')}")
        lines.append(f"反派层级：{directive.get('antagonist_tier', '')}")
        lines.append(f"CBN：{directive.get('cbn', '')}")
        lines.append(f"CEN：{directive.get('cen', '')}")
        lines.append(f"章末钩子：{directive.get('chapter_end_open_question', '')}")
        lines.append("")
        lines.append(f"# 必须覆盖节点")
        for node in directive.get("must_cover_nodes", []):
            lines.append(f"- {node}")
        lines.append("")
        lines.append(f"# 禁区")
        for zone in directive.get("forbidden_zones", []):
            lines.append(f"- {zone}")
        lines.append("")
        lines.append(f"# 关键实体")
        for ent in directive.get("key_entities", []):
            lines.append(f"- {ent}")
        lines.append("")
        lines.append(f"# CPNs")
        for cpn in directive.get("cpns", []):
            lines.append(f"- {cpn}")
        lines.append("")
        lines.append(f"# 大纲")
        lines.append(self._outline())
        lines.append("")
        lines.append(f"# 设定摘要")
        lines.append(self._setting_digest())
        lines.append("")
        lines.append(f"# 连续性")
        lines.append(f"主角状态：{json.dumps(continuity.get('protagonist_state', {}), ensure_ascii=False)}")
        lines.append(f"活跃线索：{continuity.get('active_threads', [])}")
        lines.append(f"伏笔：{continuity.get('foreshadowing', [])}")
        recent = continuity.get("recent_summaries", [])
        if recent:
            lines.append(f"近期摘要：")
            for i, s in enumerate(recent, 1):
                lines.append(f"--- 摘要 {i} ---")
                lines.append(str(s))
        prev_tail = continuity.get("previous_chapter_tail", "")
        if prev_tail:
            lines.append(f"前一章结尾（700字）：")
            lines.append(prev_tail)
        lines.append("")
        lines.append(f"# 质量要求")
        for req in quality.get("hard_requirements", []):
            lines.append(f"- {req}")
        lines.append(f"评分阈值：{quality.get('score_threshold', 80)}")
        lines.append("")
        lines.append(f"# 前章教训（Self-Absorption）")
        memory = self._load_memory()
        if memory:
            # Show last 3 chapters' lessons
            for lesson in memory[-3:]:
                lines.append(f"--- 第{lesson.get('chapter', '?')}章 ---")
                for l in lesson.get("lessons", [])[:3]:
                    lines.append(f"- {l}")
        else:
            lines.append("暂无")
        lines.append("")
        lines.append(f"# 写作任务")
        lines.append(f"请写第 {self.chapter()} 章《{self.title()}》的完整正文。")
        lines.append(f"标题：# 第{self.chapter():04d}章-{self.title()}")
        lines.append(f"只返回标题和正文，不返回任何其他内容。")

        return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    packet = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("book/.novel-supervisor/context/chapter-0001.json")
    reader = PacketReader(packet)
    print(f"Chapter: {reader.chapter()}, Title: {reader.title()}")
    print(f"System prompt chars: {len(reader.system_prompt())}")
    print(f"User prompt chars: {len(reader.user_prompt())}")
