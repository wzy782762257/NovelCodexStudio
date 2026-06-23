# Novel Codex Studio

把 Codex 作为总编监督层，把 webnovel-writer v6.2.0 作为长篇小说的事实、记忆、审查和提交系统。

正式安装后的统一入口是：

```bash
novel-codex
```

不带参数会在 Codex 中打开固定书项目。常用命令：

```bash
novel-codex where
novel-codex init "书名" "玄幻" --protagonist-name "主角名"
novel-codex status
novel-codex doctor
novel-codex pack --chapter 1
novel-codex run --chapters 5
novel-codex backup
```

`pack` 会生成有长度上限的单章上下文包。无人值守运行只读取该包，并禁用
用户级 Codex 配置、仓库扫描和子代理，以控制长篇连载的上下文消耗。

固定目录为 `~/Documents/Codex/NovelCodexStudio`，独立备份目录为
`~/Documents/Codex/NovelCodexBackups`。

## 1. 安装隔离运行环境

```bash
cd /Users/wangzhiyuan/Documents/Codex/2026-06-22/git/outputs/novel-codex-studio
python3 setup.py
```

依赖只安装到本工程的 `.venv`，不会修改全局 Python。

## 2. 初始化一本书

```bash
cd /Users/wangzhiyuan/Documents/Codex/2026-06-22/git/outputs/novel-codex-studio
python3 init_book.py "书名" "题材" \
  --protagonist-name "主角名" \
  --target-words 2000000 \
  --target-chapters 600 \
  --core-selling-points "核心卖点"
```

初始化脚本保留 `book/.codex` 和 `book/AGENTS.md`，并在同一目录生成上游所需的设定、大纲、Story System 与运行状态。

## 3. 完成设定与首卷规划

用 Codex 打开 `book/`，让它执行：

```text
使用 $novel-director，根据我的创意补全设定、总纲和第一卷章纲。在写正文前运行 doctor。
```

首版仍建议由作者确认一次核心设定和第一卷方向。确认后才进入无人值守批次。

## 4. 配置监督器

```bash
cp config.example.json config.json
```

默认每批 5 章、每章最多返工 3 次、连续失败 2 章停机。监督器不会使用 `danger-full-access`。

## 5. 先试运行

```bash
python3 supervisor.py --dry-run --start 1 --chapters 1
```

正式运行：

```bash
python3 supervisor.py
```

断点保存在 `book/.novel-supervisor/checkpoint.json`，每章事件和结构化结果保存在 `book/.novel-supervisor/logs/`。

## 安全边界

- 只有质量门通过并完成上游 postcommit gate 的章节才算成功。
- 失败草稿不会被监督器当成已提交章节。
- 三轮返工、历史事实冲突、方向性歧义或数据库异常会触发停机。
- “无人值守”适合已确认设定后的批量连载，不等于无限期无人审美把关。建议每 5-8 章人工抽检一次。
