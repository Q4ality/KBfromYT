from __future__ import annotations

import json
import subprocess
import sys

import pytest

from scripts import doctor, setup_live, start_chat
from scripts.local_environment import (
    constraint_file,
    create_env_file,
    preflight,
    runtime_problem,
    venv_python,
)


@pytest.mark.parametrize(
    ("version", "implementation", "bits", "valid"),
    [
        ((3, 12), "CPython", 64, True),
        ((3, 13), "CPython", 64, True),
        ((3, 11), "CPython", 64, False),
        ((3, 14), "CPython", 64, False),
        ((3, 12), "CPython", 32, False),
        ((3, 12), "PyPy", 64, False),
    ],
)
def test_bootstrap_interpreter_scope(version, implementation, bits, valid):
    assert (runtime_problem(version, implementation, bits) is None) == valid


def test_preflight_and_platform_profiles(tmp_path):
    preflight()
    assert constraint_file(tmp_path, "Windows", (3, 12), "AMD64") is not None
    for system, version, arch in [
        ("Linux", (3, 12), "x86_64"),
        ("Darwin", (3, 12), "arm64"),
        ("Windows", (3, 13), "AMD64"),
        ("Windows", (3, 12), "ARM64"),
    ]:
        assert constraint_file(tmp_path, system, version, arch) is None
    assert venv_python(tmp_path, "Windows") == tmp_path / "Scripts/python.exe"
    assert venv_python(tmp_path, "Linux") == tmp_path / "bin/python"


def test_env_creation_never_overwrites_credentials(tmp_path):
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    assert create_env_file(tmp_path)
    existing = b"OPENAI_API_KEY=fixture-secret\nCUSTOM_PATH=keep-me\n"
    (tmp_path / ".env").write_bytes(existing)
    assert not create_env_file(tmp_path)
    assert (tmp_path / ".env").read_bytes() == existing


def test_installer_check_changes_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_live, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["setup_live.py", "--check"])
    assert setup_live.main() == 0
    assert list(tmp_path.iterdir()) == []


def test_installer_records_runtime_without_overwriting_env(tmp_path, monkeypatch, capsys):
    root = tmp_path / "project with spaces and Катынь"
    root.mkdir()
    (root / ".env").write_text("fixture-secret", encoding="utf-8")
    python = venv_python(root / ".venv-test")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ["-m", "venv"]:
            python.parent.mkdir(parents=True)
            python.touch()

    def output(command, **kwargs):
        if "-c" in command:
            return json.dumps([list(sys.version_info[:2]), "CPython", 64])
        return "fixture-package==1.0\n"

    monkeypatch.setattr(setup_live, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["setup_live.py", "--venv", ".venv-test"])
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "check_output", output)
    assert setup_live.main() == 0
    assert calls[1][0][-2:] == ["-e", ".[semantic,chat]"]
    assert calls[1][1]["cwd"] == root
    assert (root / ".env").read_text(encoding="utf-8") == "fixture-secret"
    assert "fixture-secret" not in capsys.readouterr().out
    record = root / "data/environments/.venv-test"
    assert json.loads((record / "runtime.json").read_text())["dev"] is False
    assert (record / "requirements.freeze.txt").read_text() == "fixture-package==1.0\n"


def test_installer_refuses_incompatible_existing_environment(tmp_path, monkeypatch):
    python = venv_python(tmp_path / ".venv-live")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(setup_live, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["setup_live.py"])
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: '[[3, 11], "CPython", 64]')
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("must not install"))
    assert setup_live.main() == 1
    assert not (tmp_path / ".env").exists()


def test_portable_launcher_uses_root_without_shell_and_honors_port(tmp_path, monkeypatch):
    python = venv_python(tmp_path / ".venv-alternative")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(start_chat, "ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["start_chat.py", "--venv", ".venv-alternative", "--port", "8002", "--lexical-only"],
    )
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda *a, **kw: calls.append((a, kw)) or 0)
    assert start_chat.main() == 0
    assert calls == [
        (
            (
                [
                    str(python),
                    "-m",
                    "kbfromyt",
                    "chat",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8002",
                    "--lexical-only",
                ],
            ),
            {"cwd": tmp_path},
        )
    ]


def test_doctor_missing_packages_is_actionable_and_does_not_read_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("fixture-secret", encoding="utf-8")

    def missing(name):
        raise doctor.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(doctor.importlib.metadata, "version", missing)
    checks = doctor.inspect(tmp_path)
    assert any(level == "ERROR" and "fastembed" in message for level, message in checks)
    assert "fixture-secret" not in str(checks)
