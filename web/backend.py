#!/usr/bin/env python3
"""Novel Codex Studio - Platform Backend
完整的写作平台后端，支持：选题、框架设计、大纲、正文生产、审查、发布
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ─── Paths ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOOK_ROOT = PROJECT_ROOT / "book"
ENGINE_DIR = PROJECT_ROOT / "engine"
PLATFORM_STATE = PROJECT_ROOT / "platform" / "state.json"
ISSUES_DIR = PROJECT_ROOT / "platform" / "issues"
LOGS_DIR = PROJECT_ROOT / "platform" / "logs"

for d in [ISSUES_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── State Management ─────────────────────────────────────
class PlatformState:
    """全局平台状态，持久化到 JSON"""
    
    DEFAULT_STATE = {
        "project_id": "ncs-default",
        "project_name": "未命名项目",
        "phase": "topic",  # topic, foundation, outline, production, review, export
        "phases_completed": [],
        "engine": {
            "status": "idle",  # idle, running, paused, stopped
            "mode": "auto",    # auto, pause, manual
            "current_chapter": 0,
            "target_chapters": 10,
            "start_time": None,
            "elapsed": 0,
        },
        "progress": {
            "topic": {"completed": False, "data": {}},
            "foundation": {"completed": False, "data": {}},
            "outline": {"completed": False, "data": {}},
            "production": {"completed": False, "chapters": []},
        },
        "issues": {
            "pending": [],
            "resolved": [],
            "total": 0,
        },
        "settings": {
            "model": "deepseek-ai/DeepSeek-V3",
            "max_tokens": 6000,
            "batch_size": 1,
            "quality_threshold": 70,
        },
        "created_at": None,
        "updated_at": None,
    }
    
    def __init__(self):
        self._data = self._load()
        self._lock = threading.Lock()
        # Sync progress chapters from disk on load
        self._sync_chapters_from_disk()
    
    def _load(self) -> dict:
        if PLATFORM_STATE.exists():
            try:
                data = json.loads(PLATFORM_STATE.read_text(encoding="utf-8"))
                # Merge with defaults
                merged = self.DEFAULT_STATE.copy()
                merged.update(data)
                return merged
            except Exception:
                pass
        return self.DEFAULT_STATE.copy()
    
    def save(self):
        with self._lock:
            self._data["updated_at"] = time.time()
            PLATFORM_STATE.parent.mkdir(parents=True, exist_ok=True)
            PLATFORM_STATE.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    
    def get(self, key: str = None):
        with self._lock:
            if key is None:
                return self._data.copy()
            return self._get_nested(self._data, key)
    
    def set(self, key: str, value):
        with self._lock:
            self._set_nested(self._data, key, value)
        self.save()
    
    def _get_nested(self, obj, key):
        keys = key.split(".")
        for k in keys:
            if isinstance(obj, dict):
                obj = obj.get(k)
            else:
                return None
        return obj
    
    def _set_nested(self, obj, key, value):
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in obj:
                obj[k] = {}
            obj = obj[k]
        obj[keys[-1]] = value
    
    def advance_phase(self, phase: str):
        """推进到下一阶段"""
        with self._lock:
            self._data["phase"] = phase
            if phase not in self._data["phases_completed"]:
                self._data["phases_completed"].append(phase)
        self.save()
    
    def add_issue(self, issue: dict):
        """添加问题到队列"""
        issue["id"] = f"issue-{int(time.time()*1000)}"
        issue["created_at"] = time.time()
        issue["status"] = "pending"
        with self._lock:
            self._data["issues"]["pending"].append(issue)
            self._data["issues"]["total"] += 1
        self.save()
        return issue
    
    def resolve_issue(self, issue_id: str, resolution: str = ""):
        """解决问题"""
        with self._lock:
            pending = self._data["issues"]["pending"]
            for i, issue in enumerate(pending):
                if issue["id"] == issue_id:
                    issue["status"] = "resolved"
                    issue["resolved_at"] = time.time()
                    issue["resolution"] = resolution
                    self._data["issues"]["resolved"].append(issue)
                    self._data["issues"]["pending"].pop(i)
                    break
        self.save()

    def _sync_chapters_from_disk(self):
        """扫描磁盘正文文件，自动导入/更新平台状态"""
        import re
        chapters = self._data.setdefault("progress", {}).setdefault("production", {}).setdefault("chapters", [])
        existing_map = {c.get("chapter"): c for c in chapters}
        text_dir = BOOK_ROOT / "正文"
        review_dir = BOOK_ROOT / ".story-system" / "reviews"
        for f in sorted(text_dir.glob("第*.md")):
            m = re.search(r"第0*(\d+)章", f.name)
            if not m:
                continue
            num = int(m.group(1))
            content = f.read_text(encoding="utf-8")
            title = ""
            for line in content.split("\n")[:5]:
                m2 = re.search(r"第\d+章\s*(.+)", line)
                if m2:
                    title = m2.group(1).strip()
                    break
            if not title:
                title = f.name.replace(".md", "").split("-")[-1] if "-" in f.name else f"第{num}章"
            wc = len(re.findall(r"[\u4e00-\u9fff]", content))
            review_file = review_dir / f"chapter_{num:03d}.review.json"
            scores, hard_pass, ai_traces = {}, False, []
            if review_file.exists():
                try:
                    rev = json.loads(review_file.read_text(encoding="utf-8"))
                    scores = rev.get("scores", {})
                    hard_pass = rev.get("hard_pass", False)
                    ai_traces = rev.get("ai_traces", [])
                except Exception:
                    pass
            if num in existing_map:
                # Update existing chapter entry
                entry = existing_map[num]
                entry["title"] = title
                entry["word_count"] = wc
                entry["scores"] = scores
                entry["hard_pass"] = hard_pass
                entry["ai_traces"] = ai_traces
            else:
                chapters.append({
                    "chapter": num,
                    "title": title,
                    "status": "committed",
                    "word_count": wc,
                    "committed": True,
                    "scores": scores,
                    "hard_pass": hard_pass,
                    "ai_traces": ai_traces,
                    "steps": [{"step": "commit", "status": "ok", "at": None, "data": {}}],
                    "last_step": "commit",
                    "last_status": "ok",
                })


state = PlatformState()


# ─── Engine State Machine ─────────────────────────────────
class EngineStateMachine:
    """引擎状态机：idle -> running -> paused -> idle/stopped"""
    
    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._watchdog: Optional[threading.Thread] = None
    
    def start(self, chapter: int, mode: str = "auto"):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return {"ok": False, "error": "引擎已在运行中"}
            
            state.set("engine.status", "running")
            state.set("engine.mode", mode)
            state.set("engine.current_chapter", chapter)
            state.set("engine.start_time", time.time())
            
            # 启动引擎进程
            try:
                log_path = LOGS_DIR / f"engine-{int(time.time())}.log"
                log_f = open(log_path, "w")
                self._proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(ENGINE_DIR / "engine.py"),
                        "--start", str(chapter),
                        "--chapters", str(state.get("settings.batch_size") or 1),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=PROJECT_ROOT,
                    start_new_session=True,
                    bufsize=1,
                    text=True,
                )
                self._start_watchdog()
                return {"ok": True, "pid": self._proc.pid, "chapter": chapter}
            except Exception as e:
                state.set("engine.status", "idle")
                return {"ok": False, "error": str(e)}
    
    def pause(self):
        with self._lock:
            state.set("engine.status", "paused")
            # 发送信号暂停引擎
            if self._proc and self._proc.poll() is None:
                # 这里可以实现更优雅的暂停机制
                pass
        return {"ok": True, "status": "paused"}
    
    def resume(self):
        with self._lock:
            state.set("engine.status", "running")
        return {"ok": True, "status": "running"}
    
    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            self._proc = None
            state.set("engine.status", "idle")
            state.set("engine.current_chapter", 0)
        return {"ok": True, "status": "idle"}
    
    def status(self):
        with self._lock:
            is_alive = self._proc and self._proc.poll() is None
            if not is_alive and self._proc:
                # 进程已结束
                self._proc = None
                if state.get("engine.status") == "running":
                    state.set("engine.status", "idle")
        
        engine_data = state.get("engine")
        return {
            "status": engine_data["status"],
            "mode": engine_data["mode"],
            "current_chapter": engine_data["current_chapter"],
            "target_chapters": engine_data["target_chapters"],
            "elapsed": engine_data.get("elapsed", 0),
            "is_alive": is_alive,
        }
    
    def _start_watchdog(self):
        """启动看门狗线程监控引擎状态并消费 stdout 事件流"""
        def consume_events():
            """读取引擎 stdout 的 JSON 事件，实时更新平台状态"""
            while True:
                if not self._proc:
                    break
                try:
                    line = self._proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._process_event(event)
                except Exception:
                    break
            # stdout 关闭后，检查进程退出状态
            if self._proc:
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                with self._lock:
                    self._proc = None
                    if state.get("engine.status") == "running":
                        state.set("engine.status", "idle")

        def watch():
            consume_events()

        self._watchdog = threading.Thread(target=watch, daemon=True)
        self._watchdog.start()

    def _process_event(self, event: dict):
        """处理引擎事件，更新平台状态"""
        step = event.get("step")
        status = event.get("status")
        chapter = event.get("chapter", 0)
        data = event.get("data", {})

        # Update current chapter
        if chapter > 0:
            state.set("engine.current_chapter", chapter)

        # Track chapter progress in production
        chapters = state.get("progress.production.chapters") or []
        chapter_entry = None
        for c in chapters:
            if c.get("chapter") == chapter:
                chapter_entry = c
                break
        if chapter_entry is None:
            chapter_entry = {"chapter": chapter, "steps": []}
            chapters.append(chapter_entry)

        # Record step
        chapter_entry["steps"].append({
            "step": step,
            "status": status,
            "at": event.get("at"),
            "data": data,
        })
        chapter_entry["last_step"] = step
        chapter_entry["last_status"] = status
        if "started_at" not in chapter_entry:
            chapter_entry["started_at"] = event.get("at")

        # Handle specific events
        if step == "write" and status == "ok":
            chapter_entry["word_count"] = data.get("chinese_chars", 0)
            chapter_entry["title"] = data.get("title", "")
            chapter_entry["status"] = "written"

        elif step == "review" and status == "ok":
            chapter_entry["scores"] = data.get("scores", {})
            chapter_entry["hard_pass"] = data.get("hard_pass", False)
            chapter_entry["ai_traces"] = data.get("ai_traces", [])
            if chapter_entry.get("status") != "written":
                chapter_entry["status"] = "reviewed"

        elif step == "fulfillment" and status == "ok":
            chapter_entry["missed_nodes"] = data.get("missed_nodes", [])
            if chapter_entry.get("missed_nodes"):
                chapter_entry["status"] = "needs_fix"
            else:
                chapter_entry["status"] = "fulfilled"

        elif step == "commit" and status == "ok":
            chapter_entry["status"] = "committed"
            chapter_entry["committed"] = True
            # Auto-advance to next chapter in auto mode
            self._maybe_advance(chapter)

        elif step == "error" and status == "exception":
            chapter_entry["status"] = "failed"
            chapter_entry["error"] = data.get("error", "")
            # Add issue if not already tracked
            issue_text = data.get("error", "")
            if issue_text and len(issue_text) > 5:
                existing = [i for i in (state.get("issues.pending") or []) if i.get("chapter") == chapter]
                if not existing:
                    state.add_issue({
                        "chapter": chapter,
                        "type": "engine_error",
                        "title": f"第{chapter}章运行异常",
                        "description": issue_text,
                        "severity": "high",
                    })

        elif status == "fail" and step in ("prewrite", "precommit", "postcommit"):
            chapter_entry["status"] = "failed"
            chapter_entry["failed_step"] = step
            # Add issue
            existing = [i for i in (state.get("issues.pending") or []) if i.get("chapter") == chapter and i.get("type") == "gate_fail"]
            if not existing:
                state.add_issue({
                    "chapter": chapter,
                    "type": "gate_fail",
                    "title": f"第{chapter}章 {step} 失败",
                    "description": json.dumps(data, ensure_ascii=False),
                    "severity": "medium",
                })

        state.set("progress.production.chapters", chapters)

        # Update elapsed time
        start_time = state.get("engine.start_time")
        if start_time:
            state.set("engine.elapsed", round(time.time() - start_time, 1))


    def _maybe_advance(self, current_chapter: int):
        """如果引擎模式是 auto，自动启动下一章"""
        engine_mode = state.get("engine.mode")
        target_chapters = state.get("engine.target_chapters") or 10
        next_chapter = current_chapter + 1

        if engine_mode != "auto":
            return
        if next_chapter > target_chapters:
            return
        # Prevent double-start race
        if state.get("engine.status") != "idle" and state.get("engine.status") != "running":
            return

        def delayed_start():
            time.sleep(3)  # brief pause between chapters
            # Double-check still in auto mode and idle
            if state.get("engine.mode") != "auto":
                return
            if state.get("engine.status") != "idle":
                return
            self.start(next_chapter, mode="auto")

        threading.Thread(target=delayed_start, daemon=True).start()


engine = EngineStateMachine()


# ─── API Routes ───────────────────────────────────────────

# Project Status
@app.route("/api/project")
def api_project():
    return jsonify(state.get())

@app.route("/api/project", methods=["POST"])
def api_project_update():
    data = request.get_json() or {}
    for key, value in data.items():
        state.set(key, value)
    return jsonify({"ok": True})


# Phase Management
@app.route("/api/phase/<phase>")
def api_phase_get(phase):
    """获取某阶段的数据"""
    return jsonify(state.get(f"progress.{phase}") or {})

@app.route("/api/phase/<phase>", methods=["POST"])
def api_phase_update(phase):
    """更新某阶段的数据"""
    data = request.get_json() or {}
    current = state.get(f"progress.{phase}") or {}
    current.update(data)
    state.set(f"progress.{phase}", current)
    return jsonify({"ok": True})

@app.route("/api/phase/<phase>/complete", methods=["POST"])
def api_phase_complete(phase):
    """标记某阶段完成，推进到下一阶段"""
    state.set(f"progress.{phase}.completed", True)
    
    phase_order = ["topic", "foundation", "outline", "production", "review", "export"]
    current_idx = phase_order.index(phase) if phase in phase_order else -1
    if current_idx >= 0 and current_idx < len(phase_order) - 1:
        next_phase = phase_order[current_idx + 1]
        state.advance_phase(next_phase)
    
    return jsonify({"ok": True, "phase": phase, "next": state.get("phase")})


# Engine Control
@app.route("/api/engine/status")
def api_engine_status():
    return jsonify(engine.status())

@app.route("/api/engine/start", methods=["POST"])
def api_engine_start():
    data = request.get_json() or {}
    chapter = data.get("chapter", 1)
    mode = data.get("mode", "auto")
    return jsonify(engine.start(chapter, mode))

@app.route("/api/engine/pause", methods=["POST"])
def api_engine_pause():
    return jsonify(engine.pause())

@app.route("/api/engine/resume", methods=["POST"])
def api_engine_resume():
    return jsonify(engine.resume())

@app.route("/api/engine/stop", methods=["POST"])
def api_engine_stop():
    return jsonify(engine.stop())


# Issues
@app.route("/api/issues")
def api_issues():
    """获取所有问题"""
    return jsonify(state.get("issues"))

@app.route("/api/issues", methods=["POST"])
def api_issue_create():
    data = request.get_json() or {}
    issue = state.add_issue(data)
    return jsonify({"ok": True, "issue": issue})

@app.route("/api/issues/<issue_id>/resolve", methods=["POST"])
def api_issue_resolve(issue_id):
    data = request.get_json() or {}
    resolution = data.get("resolution", "")
    state.resolve_issue(issue_id, resolution)
    return jsonify({"ok": True})


# Chapters
@app.route("/api/chapters")
def api_chapters():
    """获取所有章节状态（统一格式）"""
    production = state.get("progress.production") or {}
    chapters = production.get("chapters", [])

    normalized = []
    for ch in chapters:
        scores = ch.get("scores", {})
        overall = 0
        if scores:
            overall = round(sum(scores.values()) / len(scores))
        normalized.append({
            "number": ch.get("chapter", 0),
            "title": ch.get("title", f"第{ch.get('chapter', 0)}章"),
            "status": ch.get("status", "pending"),
            "scores": {"overall": overall},
            "words": ch.get("word_count", 0),
            "elapsed": ch.get("elapsed", 0),
        })
    return jsonify(normalized)

@app.route("/api/chapters/<int:n>")
def api_chapter(n):
    """获取单章详情（含审查数据、轨迹）"""
    content = get_chapter_content(n)
    production = state.get("progress.production") or {}
    chapters = production.get("chapters", [])
    chapter_entry = None
    for c in chapters:
        if c.get("chapter") == n:
            chapter_entry = c
            break

    scores = chapter_entry.get("scores", {}) if chapter_entry else {}
    overall = 0
    if scores:
        overall = round(sum(scores.values()) / len(scores))

    # Build trace from steps
    steps = chapter_entry.get("steps", []) if chapter_entry else []
    trace = []
    step_names = {
        "contracts": "契约提取",
        "context_packet": "上下文打包",
        "prewrite": "Prewrite",
        "write": "正文生成",
        "review": "质量审查",
        "revise": "修订",
        "elevate": "提升",
        "fulfillment": "Fulfillment",
        "fulfill_fix": "修复遗漏",
        "save_chapter": "保存章节",
        "artifacts": "生成审查报告",
        "precommit": "Precommit",
        "commit": "Commit",
        "postcommit": "Postcommit",
    }
    for s in steps:
        step_key = s.get("step", "")
        step_status = s.get("status", "")
        trace.append({
            "name": step_names.get(step_key, step_key),
            "ok": step_status in ("ok", "pass", "done"),
            "fail": step_status in ("fail", "halt", "exception"),
        })

    return jsonify({
        "chapter": n,
        "content": content,
        "status": chapter_entry.get("status", "pending") if chapter_entry else get_chapter_status(n).get("status", "pending"),
        "title": chapter_entry.get("title", f"第{n}章") if chapter_entry else f"第{n}章",
        "word_count": chapter_entry.get("word_count", 0) if chapter_entry else 0,
        "scores": scores,
        "overall_score": overall,
        "ai_traces": chapter_entry.get("ai_traces", []) if chapter_entry else [],
        "trace": trace,
        "missed_nodes": chapter_entry.get("missed_nodes", []) if chapter_entry else [],
        "hard_pass": chapter_entry.get("hard_pass", False) if chapter_entry else False,
    })

@app.route("/api/chapters/<int:n>/content", methods=["PUT"])
def api_chapter_content_put(n):
    data = request.get_json() or {}
    content = data.get("content", "")
    save_chapter_content(n, content)
    return jsonify({"ok": True, "chapter": n})


# Settings
@app.route("/api/settings")
def api_settings():
    return jsonify(state.get("settings"))

@app.route("/api/settings", methods=["POST"])
def api_settings_update():
    data = request.get_json() or {}
    current = state.get("settings") or {}
    current.update(data)
    state.set("settings", current)
    
    # Sync to engine config.json
    config_path = PROJECT_ROOT / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            # Map known fields
            mapping = {
                "model": "model",
                "max_tokens": "max_tokens",
                "batch_size": "batch_size",
                "quality_threshold": "quality_threshold",
            }
            for key, cfg_key in mapping.items():
                if key in data:
                    cfg[cfg_key] = data[key]
            # API key only if provided (non-empty)
            api_key = data.get("api_key", "")
            if api_key and len(api_key) > 10:
                cfg["api_key"] = api_key
            config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as e:
            return jsonify({"ok": True, "warning": f"state 已保存，但 config.json 同步失败: {e}"})
    
    return jsonify({"ok": True})


# Logs
@app.route("/api/export")
def api_export():
    """导出所有已提交章节为合并 Markdown"""
    base = BOOK_ROOT / "正文"
    files = sorted(base.glob("第*.md"))
    if not files:
        return jsonify({"ok": False, "error": "暂无正文文件"})
    
    parts = []
    for f in files:
        parts.append(f.read_text(encoding="utf-8"))
        parts.append("\n\n---\n\n")
    
    content = "".join(parts).rstrip("\n-\n ")
    return jsonify({"ok": True, "content": content, "chapters": len(files)})

@app.route("/api/export/download")
def api_export_download():
    """下载合并后的 Markdown 文件"""
    base = BOOK_ROOT / "正文"
    files = sorted(base.glob("第*.md"))
    if not files:
        return jsonify({"ok": False, "error": "暂无正文文件"})
    
    parts = []
    for f in files:
        parts.append(f.read_text(encoding="utf-8"))
        parts.append("\n\n---\n\n")
    
    content = "".join(parts).rstrip("\n-\n ")
    return (
        content,
        200,
        {
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": 'attachment; filename="零点回声.md"',
        },
    )

@app.route("/api/logs")
def api_logs():
    """获取最近的日志"""
    logs = []
    for f in sorted(LOGS_DIR.glob("*.log"))[-10:]:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            logs.append({
                "file": f.name,
                "lines": lines[-50:],  # 最近50行
            })
        except Exception:
            pass
    return jsonify(logs)


# ─── Helpers ──────────────────────────────────────────────
def get_chapter_content(n: int) -> str:
    base = BOOK_ROOT / "正文"
    for f in base.glob(f"第{n:04d}章-*.md"):
        return f.read_text(encoding="utf-8")
    return ""

def get_chapter_status(n: int) -> dict:
    content = get_chapter_content(n)
    checkpoint_path = BOOK_ROOT / ".novel-supervisor" / "checkpoint.json"
    last = 0
    if checkpoint_path.exists():
        try:
            cp = json.loads(checkpoint_path.read_text())
            last = cp.get("last_committed_chapter", 0)
        except Exception:
            pass
    
    if n <= last:
        return {"status": "committed", "committed": True}
    if content:
        return {"status": "draft", "committed": False}
    return {"status": "pending", "committed": False}

def save_chapter_content(n: int, content: str):
    base = BOOK_ROOT / "正文"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"第{n:04d}章-正文.md"
    target.write_text(content, encoding="utf-8")


# ─── Serve Pages ──────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static/pages", "index.html")

@app.route("/<page>.html")
def page(page):
    return send_from_directory("static/pages", f"{page}.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
