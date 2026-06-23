#!/usr/bin/env python3
"""Launcher for Novel Codex Studio backend — keeps process alive in background."""

import subprocess
import sys
import time
from pathlib import Path

PID_FILE = Path("/tmp/novel-codex.pid")
LOG_FILE = Path("/tmp/novel-codex-backend.log")

def main():
    # Check if already running
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process exists
            import os
            os.kill(pid, 0)
            print(f"Backend already running (PID: {pid})")
            print(f"  http://localhost:8080")
            return 0
        except (ValueError, OSError, ProcessLookupError):
            PID_FILE.unlink(missing_ok=True)

    # Clean stale state
    project_root = Path(__file__).resolve().parent
    for f in [
        project_root / "book" / ".novel-supervisor" / "lock",
        project_root / "book" / ".novel-supervisor" / ".running",
        project_root / "book" / ".novel-supervisor" / ".paused",
    ]:
        f.unlink(missing_ok=True)

    # Start backend
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as log_f:
        proc = subprocess.Popen(
            [sys.executable, str(project_root / "web" / "backend.py")],
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    
    PID_FILE.write_text(str(proc.pid))
    
    # Wait for it to be ready
    for i in range(20):
        time.sleep(0.5)
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:8080/api/project/status")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    print(f"✓ Backend started (PID: {proc.pid})")
                    print(f"  http://localhost:8080")
                    return 0
        except Exception:
            pass
    
    print("✗ Backend failed to start. Check logs:")
    print(f"  tail -f {LOG_FILE}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
