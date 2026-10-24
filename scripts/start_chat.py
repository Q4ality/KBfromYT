"""Start chat from any working directory, without activating its venv."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__:
    from .local_environment import ROOT, venv_python
else:
    from local_environment import ROOT, venv_python


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=Path(".venv-live"))
    parser.add_argument("--port", type=int, choices=range(1, 65536), metavar="1..65535")
    parser.add_argument("--lexical-only", action="store_true")
    args = parser.parse_args()
    python = venv_python((ROOT / args.venv).resolve())
    if not python.is_file():
        print("Run scripts/setup_live.py first (or select its --venv path).", file=sys.stderr)
        return 1
    command = [str(python), "-m", "kbfromyt", "chat", "--host", "127.0.0.1"]
    if args.port is not None:
        command += ["--port", str(args.port)]
    if args.lexical_only:
        command += ["--lexical-only"]
    try:
        return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"Could not start chat: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
