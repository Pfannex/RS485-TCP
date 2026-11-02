"""PostToolUse-Hook: nach Änderungen an .py-Dateien comcheck.py ausführen."""

import json
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

payload = json.load(sys.stdin)
path = (payload.get("tool_input") or {}).get("file_path") or ""
if not path.lower().endswith(".py") or ".claude" in path.replace("\\", "/").split("/"):
    sys.exit(0)

try:
    proc = subprocess.run(
        [sys.executable, "comcheck.py"], cwd=PROJECT, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=45,
    )
    result = f"comcheck.py (exit {proc.returncode}):\n{proc.stdout}{proc.stderr}"
except subprocess.TimeoutExpired:
    result = "comcheck.py: Timeout nach 45 s"

print(json.dumps({
    "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": result},
}))
