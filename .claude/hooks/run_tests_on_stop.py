"""Stop hook: run the pytest suite when Python files have uncommitted changes.

Exit code 2 feeds the failure back to Claude so it fixes the tests before
finishing. Skips silently when no .py file changed or when Claude is already
continuing because of this hook (avoids loops).
"""
import json
import os
import subprocess
import sys


def main() -> int:
    """Run pytest if needed; return 2 on failure, 0 otherwise."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True, encoding="utf-8", check=False)
    changed_py = [line for line in status.stdout.splitlines()
                  if line.rstrip().endswith(".py") and ".claude/" not in line]
    if not changed_py:
        return 0

    result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "-x", "--tb=short", "--no-cov"],
                            cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
                            errors="replace")
    if result.returncode == 0:
        return 0

    tail = "\n".join(result.stdout.splitlines()[-40:])
    print(f"pytest failed after your changes — fix before finishing:\n{tail}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
