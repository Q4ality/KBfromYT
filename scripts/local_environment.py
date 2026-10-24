"""Standard-library helpers shared by local setup and diagnostics."""

from __future__ import annotations

import platform
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def runtime_problem(version: tuple[int, int], implementation: str, bits: int) -> str | None:
    if implementation != "CPython" or version not in {(3, 12), (3, 13)} or bits != 64:
        return "Use 64-bit CPython 3.12 (recommended) or 3.13 for this installer."
    return None


def preflight() -> None:
    problem = runtime_problem(
        sys.version_info[:2], platform.python_implementation(), 8 * struct.calcsize("P")
    )
    if problem:
        raise RuntimeError(problem)
    with sqlite3.connect(":memory:") as connection:
        try:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        except sqlite3.OperationalError as exc:
            raise RuntimeError("This Python's SQLite needs FTS5 support.") from exc


def venv_python(path: Path, system: str | None = None) -> Path:
    return path / (
        "Scripts/python.exe" if (system or platform.system()) == "Windows" else "bin/python"
    )


def constraint_file(root: Path, system: str, version: tuple[int, int], machine: str) -> Path | None:
    if system == "Windows" and version == (3, 12) and machine.lower() in {"amd64", "x86_64"}:
        return root / "requirements/live-windows-py312.txt"
    return None


def create_env_file(root: Path) -> bool:
    """Exclusive creation deliberately preserves an existing configuration."""
    try:
        with (root / ".env").open("xb") as target:
            target.write((root / ".env.example").read_bytes())
    except FileExistsError:
        return False
    return True
