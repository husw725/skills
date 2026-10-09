"""Verify that a GitHub-delivered script runs on the Windows host."""

import getpass
import json
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone


def main():
    if platform.system() != "Windows":
        raise SystemExit("Run this script on the Windows execution host.")
    project_dir = Path(__file__).resolve().parent
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_dir, text=True
    ).strip()
    result = {
        "status": "ok",
        "message": "Mac -> GitHub -> Windows execution succeeded",
        "host": platform.node(),
        "user": getpass.getuser(),
        "system": platform.system(),
        "python": platform.python_version(),
        "executable": sys.executable,
        "project_dir": str(project_dir),
        "git_commit": commit,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "smoke-result.json"
    payload = json.dumps(result, ensure_ascii=True, indent=2)
    output_file.write_text(payload + "\n", encoding="utf-8")
    saved = json.loads(output_file.read_text(encoding="utf-8"))
    if saved != result:
        raise RuntimeError("Result file verification failed")
    print(payload)
    print(f"Result saved to: {output_file}")


if __name__ == "__main__":
    main()
