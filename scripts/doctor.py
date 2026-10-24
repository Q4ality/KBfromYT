"""Offline local readiness checks. Does not open Qdrant or call providers."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sqlite3
from pathlib import Path

if __package__:
    from .local_environment import ROOT, preflight
else:
    from local_environment import ROOT, preflight


def inspect(root: Path) -> list[tuple[str, str]]:
    checks: list[tuple[str, str]] = []
    try:
        preflight()
        checks.append(("OK", "Python, architecture and SQLite FTS5"))
    except RuntimeError as exc:
        checks.append(("ERROR", str(exc)))
    missing = []
    for name in (
        "kbfromyt",
        "fastapi",
        "uvicorn",
        "openai",
        "python-dotenv",
        "tiktoken",
        "qdrant-client",
        "fastembed",
    ):
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        return checks + [("ERROR", "Missing packages: " + ", ".join(missing))]
    checks.append(("OK", "Chat and semantic packages installed (metadata check)"))
    from kbfromyt.chat.config import ChatConfig
    from kbfromyt.semantic import INDEX_VERSION

    try:
        config = ChatConfig.from_env(root / ".env")
    except Exception:
        return checks + [("ERROR", "Invalid .env configuration; check .env.example field formats.")]
    checks.append(
        (
            "OK" if config.has_key else "WARN",
            "OpenAI key configured"
            if config.has_key
            else "Set OPENAI_API_KEY in .env and restart chat",
        )
    )
    if not config.db.is_file():
        checks.append(("WARN", "No source database yet; start chat and import a playlist"))
    else:
        try:
            with sqlite3.connect(config.db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                videos = connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            checks.append(("OK" if videos else "WARN", f"Source database: {videos} videos"))
        except sqlite3.Error:
            checks.append(("ERROR", "Source database could not be read; check path/schema"))
    marker = config.index_dir / "complete.json"
    if not marker.is_file():
        checks.append(
            ("WARN", "No completed semantic index; import/rebuild through Manage library")
        )
    else:
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            compatible = (
                metadata.get("index_version") == INDEX_VERSION
                and metadata.get("model") == config.embedding_model
            )
            checks.append(
                (
                    "OK" if compatible else "WARN",
                    "Semantic index metadata compatible"
                    if compatible
                    else "Semantic index metadata needs rebuild",
                )
            )
        except (OSError, ValueError, AttributeError):
            checks.append(
                ("WARN", "Semantic index metadata unreadable; rebuild through Manage library")
            )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="also fail on missing key/library/index"
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    checks = inspect(ROOT)
    for level, message in checks:
        print(f"{level}: {message}")
    print("Offline check only: provider access, model caches, native imports and index freshness")
    print("are verified by actual startup/import/chat, not by this diagnostic.")
    return int(any(level == "ERROR" or (args.strict and level == "WARN") for level, _ in checks))


if __name__ == "__main__":
    raise SystemExit(main())
