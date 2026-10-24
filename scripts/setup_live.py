"""Install the local chat runtime using the Python that invokes this script."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

if __package__:
    from .local_environment import ROOT, constraint_file, create_env_file, preflight, venv_python
else:
    from local_environment import ROOT, constraint_file, create_env_file, preflight, venv_python


def install_command(python: Path, constraints: Path | None, dev: bool) -> list[str]:
    command = [str(python), "-m", "pip", "install"]
    if constraints:
        command += ["-c", str(constraints)]
    return command + ["-e", ".[semantic,chat,dev]" if dev else ".[semantic,chat]"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=Path(".venv-live"))
    parser.add_argument("--dev", action="store_true", help="also install pytest and Ruff")
    parser.add_argument("--check", action="store_true", help="preflight only; change no files")
    args = parser.parse_args()
    try:
        preflight()
        constraints = constraint_file(
            ROOT, platform.system(), sys.version_info[:2], platform.machine()
        )
        print(
            f"Python {platform.python_version()}, {platform.system()} {platform.machine()}",
            flush=True,
        )
        print(
            "Dependencies: recorded Windows/Python 3.12 constraints"
            if constraints
            else "Dependencies: portable project ranges (not an exact platform lock)",
            flush=True,
        )
        if args.check:
            print("Preflight passed: supported interpreter and SQLite FTS5.")
            return 0
        target = (ROOT / args.venv).resolve()
        python = venv_python(target)
        if not python.is_file():
            if target.exists():
                raise RuntimeError("Target exists without a usable venv. Choose a new --venv path.")
            subprocess.run([sys.executable, "-m", "venv", str(target)], check=True)
        # Fail before installing when a leftover venv belongs to another interpreter.
        probe = json.loads(
            subprocess.check_output(
                [
                    str(python),
                    "-c",
                    "import sys, struct, platform, json; "
                    "print(json.dumps([list(sys.version_info[:2]), "
                    "platform.python_implementation(), struct.calcsize('P') * 8]))",
                ],
                text=True,
            )
        )
        if probe != [list(sys.version_info[:2]), "CPython", 64]:
            raise RuntimeError("Existing venv uses a different Python. Choose a new --venv path.")
        subprocess.run(install_command(python, constraints, args.dev), cwd=ROOT, check=True)
        subprocess.run([str(python), "-m", "pip", "check"], cwd=ROOT, check=True)
        destination = ROOT / "data/environments" / target.name
        destination.mkdir(parents=True, exist_ok=True)
        freeze = subprocess.check_output([str(python), "-m", "pip", "freeze"], cwd=ROOT, text=True)
        (destination / "requirements.freeze.txt").write_text(freeze, encoding="utf-8")
        (destination / "runtime.json").write_text(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "system": platform.system(),
                    "machine": platform.machine(),
                    "profile": "windows-py312" if constraints else "portable",
                    "dev": args.dev,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        created = create_env_file(ROOT)
        print("Created .env from template." if created else "Preserved existing .env.")
        print(f"Runtime ready: {python}")
        print("Set OPENAI_API_KEY in the root .env, then run scripts/start_chat.py.")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
