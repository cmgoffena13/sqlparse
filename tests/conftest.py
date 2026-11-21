import os
import subprocess
import tempfile
from pathlib import Path

import pytest

os.environ["MAX_FORK_WORKERS"] = "1"
os.environ["SQLMESH_HOME"] = tempfile.mkdtemp(prefix="sqlmesh-test-")

FIXTURE_PROJECT = Path(__file__).resolve().parent / "fixtures" / "sushi"


@pytest.fixture(autouse=True)
def _isolate_sqlparse_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLPARSE_CONFIG_DIR", str(tmp_path / "sqlparse-config"))


@pytest.fixture(autouse=True)
def _isolate_vendor_skill_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    def roots() -> list[Path]:
        home = Path.home()
        return [
            home / ".claude" / "skills",
            home / ".codex" / "skills",
            home / ".copilot" / "skills",
            home / ".cursor" / "skills",
            home / ".gemini" / "skills",
            home / ".config" / "agents" / "skills",
            home / ".config" / "opencode" / "skills",
        ]

    monkeypatch.setattr("src.sqlparse_mcp.skill._vendor_skill_roots", roots)


@pytest.fixture(autouse=True)
def _git_controlled_tmp_path(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "-q"],  # noqa: S607
        cwd=tmp_path,
        capture_output=True,
        check=True,
        timeout=5,
    )


@pytest.fixture
def mcp_client(_isolate_sqlparse_config: None):
    from fastmcp import Client

    from src.sqlparse_mcp import server

    return Client(server.mcp)
