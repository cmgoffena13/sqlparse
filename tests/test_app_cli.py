import os
import shutil
import sys
from pathlib import Path

import pytest

from src.app import main
from src.cli.commands import help_banner
from src.utils import get_version
from tests.conftest import FIXTURE_PROJECT


def test_bare_sqlparse_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["sqlparse"])
    assert main() == 0
    out = capsys.readouterr().out
    assert help_banner() in out
    assert "usage:" in out
    assert "mcp" in out
    assert "reload" in out
    assert "install" in out
    assert "uninstall" in out
    assert "sync" not in out


def test_version_flag_prints_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["sqlparse", "--version"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "sqlparse version:" in out
    assert get_version() in out


def test_info_flag_prints_paths_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "sqlparse-config"
    monkeypatch.setattr(sys, "argv", ["sqlparse", "--info"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Binary path:" in out
    assert "Config directory:" in out
    assert str(config_dir) in out


def test_hidden_sync_writes_the_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skills = tmp_path / ".cursor" / "skills"
    skills.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "sync"])
    assert main() == 0
    skill = skills / "sqlparse" / "SKILL.md"
    assert skill.is_file()
    assert "example" in skill.read_text(encoding="utf-8")
    assert f"Synced skill → {skill.parent}" in capsys.readouterr().out


def test_reload_indexes_the_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db import ProjectDB

    monkeypatch.setattr(sys, "argv", ["sqlparse", "reload", "--cwd", str(FIXTURE_PROJECT)])
    assert main() == 0
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        count = db.fetch("SELECT COUNT(*) AS file_count FROM files")[0]["file_count"]
    finally:
        db.close()
    assert count == 12


def test_reload_missing_directory_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing = tmp_path / "no-such-dir"
    monkeypatch.setattr(sys, "argv", ["sqlparse", "reload", "--cwd", str(missing)])
    assert main() == 1
    assert "Not a directory" in capsys.readouterr().err


def test_reload_outside_git_repo_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    shutil.rmtree(tmp_path / ".git")
    monkeypatch.setattr(sys, "argv", ["sqlparse", "reload", "--cwd", str(tmp_path)])
    assert main() == 1
    assert "not a git repository" in capsys.readouterr().err


def test_mcp_starts_against_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    def fake_run(**kwargs: object) -> None:
        del kwargs
        seen["workspace"] = os.environ["SQLPARSE_WORKSPACE"]
        seen["cwd"] = str(Path.cwd())

    monkeypatch.setattr("src.sqlparse_mcp.server.mcp.run", fake_run)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "mcp", "--cwd", str(FIXTURE_PROJECT)])
    origin = Path.cwd()
    try:
        assert main() == 0
        assert seen["workspace"] == str(FIXTURE_PROJECT.resolve())
        assert seen["cwd"] == str(FIXTURE_PROJECT.resolve())
    finally:
        os.chdir(origin)


def test_cleanup_removes_an_orphan_index(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    shutil.copytree(FIXTURE_PROJECT, project)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "reload", "--cwd", str(project)])
    assert main() == 0
    shutil.rmtree(project)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "cleanup"])
    assert main() == 0
    assert "Removing index" in capsys.readouterr().out
    assert main() == 0
    assert "No orphan indexes found." in capsys.readouterr().out
