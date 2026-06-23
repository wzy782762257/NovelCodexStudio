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
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    cwd=PROJECT_ROOT,
                    start_new_session=True,
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
        """启动看门狗线程监控引擎状态"""
        def watch():
            while True:
                time.sleep(5)
                if not self._proc or self._proc.poll() is not None:
                    break
                # 检查引擎是否卡住或异常
        
        self._watchdog = threading.Thread(target=watch, daemon=True)
        self._watchdog.start()


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
    """获取所有章节状态"""
    production = state.get("progress.production") or {}
    chapters = production.get("chapters", [])
    return jsonify(chapters)

@app.route("/api/chapters/<int:n>")
def api_chapter(n):
    """获取单章详情"""
    content = get_chapter_content(n)
    return jsonify({
        "chapter": n,
        "content": content,
        "status": get_chapter_status(n),
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
    return jsonify({"ok": True})


# Logs
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
