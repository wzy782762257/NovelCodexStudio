---
name: novel-director
description: 监督中文长篇小说的连续创作与安全提交。用于继续写下一章、批量连载、恢复中断写作或查看进度。
---

# 长篇小说总编

使用固定入口 `novel-codex`。Codex 负责创作与逻辑审查，webnovel-writer 负责门禁、状态和提交。

## 用户入口

- `novel-codex status`：看进度。
- `novel-codex pack --chapter N`：生成本章轻量上下文包。
- `novel-codex run --start N --chapters M`：无人值守创作。
- `novel-codex backup`：独立备份。

## 执行原则

- 监督器会为每章生成一个有上限的上下文包；创作代理只读该包。
- 不扫描整书、不读取 vendor 规范、不启动子代理。
- 单会话完成正文、自审、定点返工和事实提取，最多返工三次。
- 每章正文固定为 2000–3000 个汉字，范围外属于硬失败。
- blocking issue、遗漏节点、待消歧或任一门禁失败时禁止提交。
- 只有 chapter-commit accepted 且 postcommit 通过，才算本章完成。
