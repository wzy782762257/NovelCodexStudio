# Codex 长篇连载规则

本目录是一部由 Codex 监督、webnovel-writer 管理长期状态的中文长篇小说。

- 交互式写作管理使用 `$novel-director`。
- 若提示词给出 `.novel-supervisor/context/chapter-*.json`，这是监督器的轻量单章运行：
  读取项目级 `novel-director` 短版 skill 后只读该上下文包，不再读取其他 skill、
  vendor 文档或整书文件，不启动子代理。
- `../vendor/webnovel-writer` 是只读上游依赖，不要修改。
- `.story-system/` 是事实真源；`.webnovel/` 是派生状态和运行数据。
- 只有通过质量门的章节才能调用 `chapter-commit`。
- 不得为追求无人值守而猜测关键设定。遇到互斥事实、方向性选择或三次返工失败时安全停机。
- 所有运行日志写入 `.novel-supervisor/`，草稿和审查报告保留在书项目内。
- 验证优先使用上游 `preflight`、`write-gate`、`project-status` 和 `doctor`。
