# Novel Codex Studio - 平台架构

## 阶段划分

### Phase 1: 选题（Pre-production）
- 用户输入主题/类型偏好
- AI生成多个选题方案
- 用户选择并确认方向
- 状态：选题 → 框架设计

### Phase 2: 框架设计（Foundation）
- 世界观构建：背景设定、规则体系、势力分布
- 角色塑造：主角卡、配角卡、关系网络
- 剧情脉络：主线、支线、冲突点、高潮节点
- 状态：框架设计 → 大纲编写

### Phase 3: 大纲（Outline）
- 卷纲：每卷的主题、起承转合
- 章纲：每章的契约、节点、情感节拍
- 节拍表：细纲级别的场景设计
- 状态：大纲编写 → 正文生产

### Phase 4: 正文生产（Production）
- 引擎状态机驱动
- 单章流水线：契约→上下文→写作→审查→修订→Fulfillment→Commit
- 问题中心：集中处理异常
- 状态：正文生产 → 审查完成

### Phase 5: 发布（Distribution）
- 多格式导出：Markdown、TXT、Word、PDF
- 平台适配：番茄小说、起点等
- 一键上传/自动上传
- 状态：发布

## 引擎状态机

```
IDLE
  ↓ 用户启动/配置完成
RUNNING
  ├─ 全自动模式：每章完成→自动Commit→下一章
  ├─ 暂停模式：每章完成→暂停→用户审批→继续
  └─ 发现异常：RUNNING → PAUSED → 问题中心
PAUSED
  ├─ 用户处理决策 → RESUME → RUNNING
  └─ 用户停止 → STOP
STOP
  ↓ 用户重新启动 → IDLE
```

## 文件结构

```
web/
  backend.py          # Flask 主后端
  engine.py           # 引擎状态机
  static/
    css/
      common.css      # 公共样式
      page-*.css      # 页面样式
    js/
      common.js       # 公共工具（路由、状态、API）
      page-*.js       # 页面逻辑
    pages/
      index.html      # 选题入口（默认页）
      dashboard.html  # 指挥中心
      pipeline.html   # 流水线视图
      chapter.html    # 单章工作区
      issues.html     # 问题中心
      foundation.html # 框架设计
      outline.html    # 大纲管理
      settings.html   # 全局设置
      export.html     # 导出与发布
  templates/          # Flask 模板（如有需要）
```

## 状态持久化

```json
{
  "project_id": "",
  "project_name": "",
  "phase": "foundation|outline|production|review|export",
  "engine_mode": "auto|pause|manual",
  "current_chapter": 0,
  "target_chapters": 0,
  "foundation_complete": false,
  "outline_complete": false,
  "running": false,
  "paused": false,
  "issues": [],
  "logs": []
}
```
