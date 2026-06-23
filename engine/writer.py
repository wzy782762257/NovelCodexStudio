#!/usr/bin/env python3
"""Writer agent: call LLM to produce chapter text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import EngineConfig
from .llm_client import LLMClient
from .packet_reader import PacketReader


class WriterAgent:
    def __init__(self, client: LLMClient, config: EngineConfig):
        self.client = client
        self.config = config

    def write(self, packet_path: Path, min_chars: int = 2000, max_chars: int = 3000, max_retries: int = 5) -> dict[str, Any]:
        reader = PacketReader(packet_path)
        system = reader.system_prompt()
        user = reader.user_prompt()

        content = self.client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        lines = content.strip().splitlines()
        title = ""
        body = content.strip()
        if lines and lines[0].lstrip().startswith("#"):
            title = lines[0].lstrip("# ").strip()
            body = "\n".join(lines[1:]).strip()

        chinese_chars = len(re.findall(r"[\u3400-\u9fff]", body))

        # 如果字数不足，用 revise 方式扩写（保留已有内容）
        for attempt in range(max_retries):
            if min_chars <= chinese_chars <= max_chars:
                break
            if attempt >= max_retries:
                break

            expand_prompt = f"""当前正文字数不足（{chinese_chars} 汉字，要求 {min_chars}-{max_chars} 汉字）。请扩写正文，严格遵循以下原则：

1. 保持原有情节和结构不变
2. 通过增加细节描写、对话、场景描写、内心独白等方式扩充
3. 严格遵守声音DNA中的风格规则（短句、感官细节、对话推进）
4. 不要添加解释性段落，不要改变原有节奏

只返回修改后的完整正文（标题+正文），不要返回任何分析或说明。"""

            content = self.client.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": body},
                    {"role": "user", "content": expand_prompt},
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            lines = content.strip().splitlines()
            body = content.strip()
            if lines and lines[0].lstrip().startswith("#"):
                title = lines[0].lstrip("# ").strip()
                body = "\n".join(lines[1:]).strip()

            chinese_chars = len(re.findall(r"[\u3400-\u9fff]", body))

        return {
            "chapter": reader.chapter(),
            "title": title or reader.title(),
            "chapter_file": reader.chapter_file(),
            "raw_content": content,
            "body": body,
            "chinese_chars": chinese_chars,
        }

    def revise(self, packet_path: Path, current_body: str, issues: list[str]) -> dict[str, Any]:
        reader = PacketReader(packet_path)
        system = reader.system_prompt()

        # 检测是否包含字数不足问题
        has_length_issue = any("字数" in issue and "不在" in issue for issue in issues)

        if has_length_issue:
            revision_prompt = f"""当前正文字数不足，请扩写。

问题：
{chr(10).join(f"- {issue}" for issue in issues)}

当前正文：
{current_body}

要求：
- 正文必须达到 2000-3000 个汉字（不含标点、空格、标题）
- 保持原有情节、人物和结构不变
- 通过增加细节描写、对话、场景描写、内心独白等方式扩充
- 严格遵守声音DNA风格（短句、感官细节、对话推进）
- 只返回修改后的完整正文（标题+正文），不要返回任何分析或说明"""
        else:
            revision_prompt = f"""以下是你之前写的正文，存在以下问题需要修改。

{chr(10).join(f"- {issue}" for issue in issues)}

当前正文：
{current_body}

修改要求（对抗性编辑 - Adversarial Editing）：
1. 把每个 TELL（\"他感到害怕\"）改为 SHOW（\"他的手在发抖\"）
2. 删除重复的词和句子，每句话必须有新的信息
3. 检查情感曲线：开头紧张→中段上升→结尾峰值，不能有平段
4. 确保章末最后一段有\"最后一击\"的力度，不是总结而是爆炸
5. 删除所有冗余段落，如果删除某段不影响理解，就删除它

请修改正文，解决上述问题。只返回修改后的完整正文（标题+正文），不要返回任何分析或说明。"""

        content = self.client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": reader.user_prompt()},
                {"role": "assistant", "content": current_body},
                {"role": "user", "content": revision_prompt},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        lines = content.strip().splitlines()
        title = ""
        body = content.strip()
        if lines and lines[0].lstrip().startswith("#"):
            title = lines[0].lstrip("# ").strip()
            body = "\n".join(lines[1:]).strip()

        chinese_chars = len(re.findall(r"[\u3400-\u9fff]", body))

        return {
            "chapter": reader.chapter(),
            "title": title or reader.title(),
            "chapter_file": reader.chapter_file(),
            "raw_content": content,
            "body": body,
            "chinese_chars": chinese_chars,
        }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import EngineConfig
    from llm_client import LLMClient

    cfg = EngineConfig.load(Path("config.json"))
    client = LLMClient(cfg.base_url, cfg.api_key, cfg.model)
    agent = WriterAgent(client, cfg)

    packet = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("book/.novel-supervisor/context/chapter-0001.json")
    result = agent.write(packet)
    print(f"Title: {result['title']}")
    print(f"Chinese chars: {result['chinese_chars']}")
    print(f"Body preview: {result['body'][:200]}...")
