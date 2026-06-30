#!/usr/bin/env python3
"""Reviewer agent: quality gate, scoring, and artifact generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import EngineConfig
from .llm_client import LLMClient
from .packet_reader import PacketReader


class ReviewerAgent:
    def __init__(self, client: LLMClient, config: EngineConfig):
        self.client = client
        self.config = config

    def review(self, packet_path: Path, body: str) -> dict[str, Any]:
        reader = PacketReader(packet_path)
        directive = reader._directive()
        quality = reader._quality()

        system = """你是 Nacharium 审查委员会，由5位独立角色组成。每位角色必须给出2-3句具体反馈，不能只说"不错"或"需要改进"。

【角色1：主编 - 结构师】
关注：章节结构、节奏控制、骨架钥匙是否兑现、信息增量是否充足
输出格式：{"editor": "具体反馈...", "score": 0-100}

【角色2：文学评论家 - 深度师】
关注：意象系统、潜台词、比喻质量、情感层次、是否有"一句话让人记住"的句子
输出格式：{"critic": "具体反馈...", "score": 0-100}

【角色3：挑剔读者 - 节奏师】
关注：哪里无聊、哪里想跳过、hook是否有效、追读力、章末是否让人想翻页
输出格式：{"reader": "具体反馈...", "score": 0-100}

【角色4：语言工程师 - AI痕迹猎手】
关注：以下10项AI痕迹检查清单（每发现一项扣10分）：
1. 总结式段落（\"原来...\"\"这一切都是因为...\"）
2. 泛化情绪词堆叠（\"害怕、恐惧、绝望\"）
3. 连续短句排比（\"他害怕了。恐惧了。绝望了。\"）
4. 环境填充句（\"空气中弥漫着...\"\"仿佛预示着...\"）
5. TELL而非SHOW（\"他感到...\"\"她意识到...\"）
6. 无信息对话（只复述设定不改变关系）
7. 解释性括号或破折号过度使用
8. 三段式结构（开头-中间-结尾明显模板化）
9. 以-ing结尾的肤浅分析（\"看着窗外，他思考着...\"）
10. 结尾总结句（\"他知道，前方的路还很长...\"）
输出格式：{"engineer": "具体反馈...", "score": 0-100, "ai_traces_found": ["痕迹1", "痕迹2"]}

【角色5：连续性经理 - 逻辑师】
关注：人物一致性、时间线、因果链、与前后章衔接、知识边界
输出格式：{"continuity": "具体反馈...", "score": 0-100}

输出 JSON 格式：
{
  "scores": {
    "plot_progress": 0-100,
    "character_consistency": 0-100,
    "continuity": 0-100,
    "pacing": 0-100,
    "chapter_hook": 0-100,
    "style_naturalness": 0-100
  },
  "role_feedback": {
    "editor": "...",
    "critic": "...",
    "reader": "...",
    "engineer": "...",
    "continuity": "..."
  },
  "ai_traces": ["发现的具体AI痕迹"],
  "issues": ["问题描述1", "问题描述2"],
  "blocking_issues": ["阻塞问题1"],
  "hard_pass": true/false,
  "summary": "简短审查摘要"
}

硬门检查（任何一项失败都标记为 blocking）：
- 与世界规则、能力上限、既有事实冲突
- 时间倒流、倒计时错误、人物同时出现在不可能抵达的地点
- 人物使用其不应知道的信息
- 行为与核心动机冲突且正文没有给出转变依据
- 关键结果没有可见原因，或章纲必须节点缺失
- 遗漏 must_cover_nodes 中的节点
- 进入 forbidden_zones
- 字数不在 2000-3000 汉字范围内
- 发现严重AI痕迹（language_engineer score < 60）
"""

        user = f"""章节：第 {reader.chapter()} 章《{reader.title()}》

CBN：{directive.get('cbn', '')}
CEN：{directive.get('cen', '')}
必须覆盖节点：{directive.get('must_cover_nodes', [])}
禁区：{directive.get('forbidden_zones', [])}
字数要求：2000-3000 汉字

正文：
{body}

请5位角色分别审查，然后输出综合评分。"""

        result = self.client.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=3000,
        )

        # Normalize scores
        scores = result.get("scores", {})
        for key in ["plot_progress", "character_consistency", "continuity", "pacing", "chapter_hook", "style_naturalness"]:
            if key not in scores:
                scores[key] = 0
            else:
                scores[key] = max(0, min(100, int(scores[key])))

        hard_pass = bool(result.get("hard_pass", True))
        blocking_issues = result.get("blocking_issues", []) or []
        issues = result.get("issues", []) or []
        ai_traces = result.get("ai_traces", []) or []

        # Check length
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", body))
        if not 2000 <= chinese_chars <= 3000:
            hard_pass = False
            blocking_issues.append(f"字数 {chinese_chars} 不在 2000-3000 范围内")

        # Check AI traces severity
        if scores.get("style_naturalness", 100) < 60:
            hard_pass = False
            if not any("AI痕迹" in bi for bi in blocking_issues):
                blocking_issues.append("AI痕迹严重（style_naturalness < 60），需进行Grind步骤")

        return {
            "scores": scores,
            "issues": issues,
            "blocking_issues": blocking_issues,
            "ai_traces": ai_traces,
            "role_feedback": result.get("role_feedback", {}),
            "hard_pass": hard_pass and len(blocking_issues) == 0,
            "summary": result.get("summary", ""),
            "chinese_chars": chinese_chars,
        }

    def fulfillment(self, packet_path: Path, body: str) -> dict[str, Any]:
        reader = PacketReader(packet_path)
        directive = reader._directive()
        must_cover = directive.get("must_cover_nodes", [])

        # Structural markers (CBN, CEN) are structural directives, not content
        # nodes to be checked for coverage. Filter them out before asking LLM.
        structural_markers = {"CBN", "CEN"}
        real_nodes = [n for n in must_cover if n not in structural_markers]

        system = """你是一位情节分析师。你的任务是检查正文是否覆盖了所有必须节点，输出 JSON。

重要：只检查"必须覆盖节点"（must_cover_nodes）列表中的内容。CBN、CEN、章末未闭合问题等是章节的结构性信息，不是必须覆盖的节点，不要将它们列入检查范围。

输出格式：
{
  "planned_nodes": ["原始节点1", "原始节点2"],
  "covered_nodes": ["实际覆盖的节点1"],
  "missed_nodes": ["遗漏的节点1"],
  "extra_nodes": ["额外覆盖的节点1"]
}

注意：
- 如果 must_cover_nodes 中的节点在正文中被间接覆盖或暗示覆盖，也算覆盖。
- 但如果完全没有提及或暗示，则算遗漏。
- 返回的节点名称应该与原始 must_cover_nodes 保持一致。"""

        user = f"""必须覆盖节点：{real_nodes}

正文：
{body}

请分析覆盖情况。"""

        result = self.client.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        return {
            "planned_nodes": list(must_cover),
            "covered_nodes": result.get("covered_nodes", []),
            "missed_nodes": result.get("missed_nodes", []),
            "extra_nodes": result.get("extra_nodes", []),
        }

    def disambiguation(self, packet_path: Path, body: str) -> dict[str, Any]:
        reader = PacketReader(packet_path)
        continuity = reader._continuity()
        pending = continuity.get("foreshadowing", [])

        system = """你是一位设定消歧专家。你的任务是检查正文中是否引入了与已有设定矛盾的新歧义，输出 JSON。

重要：以下情况**不算**待消歧项，不要标记：
- 悬念、伏笔、未解之谜：这是正常的小说写作手法，不需要标记。
- 人物的正常行为（如帮助主角、监视、暗示等）：这是情节推进，不需要标记。
- 已知设定中的概念（如零点回声、能力代价、静默计划、陈曦、孟骁等）。
- 大纲中已规划但本章未完全揭晓的内容（如三院线索、地下二层等）。
- 角色之间的正常互动或信息差。

只标记以下情况：
- 正文中出现了与主角卡、世界观、力量体系等设定集直接矛盾的事实。
- 正文中出现了大纲中没有且明显偏离主线方向的新设定或新角色。
- 正文中出现了逻辑上无法自洽的因果关系。

输出格式：
{
  "pending": [
    {"mention": "歧义描述", "reason": "为什么需要消歧"}
  ]
}

注意：
- 如果正文没有引入与设定矛盾的新歧义，pending **必须**为空列表。
- 不要把悬念、伏笔、人物行为或已知设定标记为待消歧。"""

        user = f"""正文：
{body}

请检查是否有新的待消歧项。"""

        result = self.client.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        pending_list = result.get("pending", [])
        if not isinstance(pending_list, list):
            pending_list = []

        return {"pending": pending_list}

    def extraction(self, packet_path: Path, body: str) -> dict[str, Any]:
        reader = PacketReader(packet_path)
        chapter = reader.chapter()

        system = """你是一位事件提取专家。你的任务是从一章正文中提取结构化事件和状态变更，输出 JSON。

输出格式：
{
  "accepted_events": [
    {
      "event_id": "evt-ch001-001",
      "chapter": 1,
      "event_type": "open_loop_created",
      "subject": "实体名",
      "payload": {"content": "事件内容", "unanswered_question": "未解问题"}
    }
  ],
  "state_deltas": [
    {"entity_id": "实体ID", "field": "location.current", "old": "旧值", "new": "新值"}
  ],
  "entity_deltas": [
    {"entity_id": "实体ID", "action": "upsert", "entity_type": "角色", "payload": {"name": "实体名"}}
  ],
  "entities_appeared": [
    {"id": "实体ID", "type": "角色", "mentions": ["正文称呼"], "confidence": 0.95}
  ],
  "scenes": [
    {"index": 1, "start_line": 1, "end_line": 1, "location": "地点", "summary": "场景摘要", "characters": ["实体ID"]}
  ],
  "summary_text": "100-150字事实摘要"
}

注意：
- event_type 必须是以下之一：character_state_changed, relationship_changed, world_rule_revealed, world_rule_broken, power_breakthrough, artifact_obtained, open_loop_created, open_loop_closed, promise_created, promise_paid_off
- summary_text 必须是 100-150 字的客观事实摘要，不要评价或煽情。"""

        user = f"""章节：第 {chapter} 章

正文：
{body}

请提取结构化事件。"""

        result = self.client.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=3000,
        )

        # Ensure required fields exist
        for key in ["accepted_events", "state_deltas", "entity_deltas"]:
            if key not in result or not isinstance(result[key], list):
                result[key] = []
        for key in ["entities_appeared", "scenes"]:
            if key not in result or not isinstance(result[key], list):
                result[key] = []
        if "summary_text" not in result or not isinstance(result["summary_text"], str):
            result["summary_text"] = ""

        # Normalize event IDs
        for i, event in enumerate(result.get("accepted_events", [])):
            if not event.get("event_id"):
                event["event_id"] = f"evt-ch{chapter:03d}-{i+1:03d}"
            if not event.get("chapter"):
                event["chapter"] = chapter

        return result

    def full_review(self, packet_path: Path, body: str) -> dict[str, Any]:
        """Run all review steps and return combined artifacts.
        
        Each step is wrapped in try/except so a single failure doesn't crash the whole review.
        """
        def safe_step(name, fn):
            try:
                return fn()
            except Exception as e:
                return {"error": str(e), "step": name, "ok": False}

        review = safe_step("review", lambda: self.review(packet_path, body))
        fulfillment = safe_step("fulfillment", lambda: self.fulfillment(packet_path, body))
        disambiguation = safe_step("disambiguation", lambda: self.disambiguation(packet_path, body))
        extraction = safe_step("extraction", lambda: self.extraction(packet_path, body))

        return {
            "review": review,
            "fulfillment": fulfillment,
            "disambiguation": disambiguation,
            "extraction": extraction,
        }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import EngineConfig
    from llm_client import LLMClient

    cfg = EngineConfig.load(Path("config.json"))
    client = LLMClient(cfg.base_url, cfg.api_key, cfg.model)
    agent = ReviewerAgent(client, cfg)

    packet = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("book/.novel-supervisor/context/chapter-0001.json")
    body = (Path("book/正文") / "第0001章-妹妹死后三年，我接到了她的求救电话.md").read_text(encoding="utf-8")
    result = agent.full_review(packet, body)
    print(json.dumps(result, ensure_ascii=False, indent=2))
