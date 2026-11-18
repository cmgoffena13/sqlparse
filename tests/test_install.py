import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from src.app import main
from src.utils import binary_path


def test_install_registers_the_binary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    binary = tmp_path / "bin" / "sqlparse"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / ".cursor" / "skills").mkdir(parents=True)
    (tmp_path / "Library" / "Application Support" / "Claude").mkdir(parents=True)
    (tmp_path / ".config" / "goose").mkdir(parents=True)
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: "/usr/bin/claude")
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: "/usr/bin/gemini")
    cli_calls: list[list[str]] = []
    monkeypatch.setattr(
        "src.cli.install_mcp.run_cli_command",
        lambda command: cli_calls.append(command),
    )
    deeplinks: list[str] = []
    monkeypatch.setattr(
        "src.cli.install_mcp.open_deeplink",
        lambda url, **_kwargs: deeplinks.append(url) or True,
    )
    monkeypatch.setattr(sys, "argv", [str(binary), "install"])

    assert main() == 0
    command = str(binary.resolve())
    claude = json.loads(
        (
            tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        ).read_text(encoding="utf-8")
    )
    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    cursor_url = next(url for url in deeplinks if url.startswith("cursor://"))
    cursor_config = json.loads(
        base64.urlsafe_b64decode(parse_qs(urlparse(cursor_url).query)["config"][0])
    )
    assert cursor_config["command"] == command
    assert cursor_config["args"] == ["mcp", "--cwd", "${workspaceFolder}"]
    assert claude["mcpServers"]["sqlparse"]["command"] == command
    assert claude["mcpServers"]["sqlparse"]["args"] == ["mcp"]
    assert cli_calls == [
        ["/usr/bin/claude", "mcp", "add", "sqlparse", "--", command, "mcp"],
        ["/usr/bin/gemini", "mcp", "add", "sqlparse", command, "--", "mcp"],
    ]
    assert any(url.startswith("goose://") for url in deeplinks)
    out = capsys.readouterr().out
    skill = tmp_path / ".cursor" / "skills" / "sqlparse" / "SKILL.md"
    assert skill.is_file()
    assert "Installed MCP server → Cursor" in out
    assert "Installed MCP server → Claude Desktop" in out
    assert "Installed MCP server → Claude Code" in out
    assert "Installed MCP server → Gemini CLI" in out
    assert "Installed MCP server → Goose" in out
    assert f"Synced skill → {skill.parent}" in out
    assert out.index("Installed MCP server → Cursor") < out.index("Synced skill")
    assert "Restart the client" in out


def test_install_with_no_clients_prints_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: None)
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "install"])
    assert main() == 0
    assert "No MCP clients found." in capsys.readouterr().out


def test_install_exits_one_when_nothing_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "install"])
    monkeypatch.setattr("src.cli.install_mcp.install_mcp", list)
    assert main() == 1


def test_invalid_claude_config_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    binary = tmp_path / "sqlparse"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    claude_dir = tmp_path / "Library" / "Application Support" / "Claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "claude_desktop_config.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: None)
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: None)
    monkeypatch.setattr(sys, "argv", [str(binary), "install"])

    assert main() == 1
    assert "Failed to install sqlparse in Claude Desktop" in capsys.readouterr().err


def test_uninstall_removes_server_and_skill(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sqlparse": {"command": "sqlparse", "args": ["mcp"]},
                    "other": {"command": "noop"},
                }
            }
        ),
        encoding="utf-8",
    )
    claude_dir = tmp_path / "Library" / "Application Support" / "Claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"sqlparse": {"command": "sqlparse", "args": ["mcp"]}}}),
        encoding="utf-8",
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "userID": "abc",
                "mcpServers": {"sqlparse": {"command": "sqlparse"}},
                "projects": {"/repo": {"mcpServers": {"sqlparse": {"command": "sqlparse"}}}},
            }
        ),
        encoding="utf-8",
    )
    gemini = tmp_path / ".gemini"
    gemini.mkdir()
    (gemini / "settings.json").write_text(
        json.dumps({"theme": "dark", "mcpServers": {"sqlparse": {"command": "sqlparse"}}}),
        encoding="utf-8",
    )
    goose = tmp_path / ".config" / "goose"
    goose.mkdir(parents=True)
    (goose / "config.yaml").write_text(
        "extensions:\n  sqlparse:\n    type: stdio\n    cmd: sqlparse\n"
        "  other:\n    type: stdio\n    cmd: noop\n",
        encoding="utf-8",
    )
    skills = tmp_path / ".cursor" / "skills"
    skills.mkdir()
    skill = skills / "sqlparse"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill", encoding="utf-8")
    (skills / "other").mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: "/usr/bin/claude")
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: "/usr/bin/gemini")
    monkeypatch.setattr(
        "src.cli.install_mcp.run_cli_command",
        lambda command: calls.append(command),
    )
    monkeypatch.setattr(sys, "argv", ["sqlparse", "uninstall"])

    assert main() == 0
    cursor = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "sqlparse" not in cursor["mcpServers"]
    assert cursor["mcpServers"]["other"]["command"] == "noop"
    claude_desktop = json.loads(
        (claude_dir / "claude_desktop_config.json").read_text(encoding="utf-8")
    )
    assert "sqlparse" not in claude_desktop["mcpServers"]
    claude_code = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert claude_code["userID"] == "abc"
    assert "sqlparse" not in claude_code["mcpServers"]
    assert "sqlparse" not in claude_code["projects"]["/repo"]["mcpServers"]
    gemini_data = json.loads((gemini / "settings.json").read_text(encoding="utf-8"))
    assert gemini_data["theme"] == "dark"
    assert "sqlparse" not in gemini_data["mcpServers"]
    goose_text = (goose / "config.yaml").read_text(encoding="utf-8")
    assert "sqlparse" not in goose_text
    assert "noop" in goose_text
    assert not skill.exists()
    assert (skills / "other").is_dir()
    assert calls == [
        ["/usr/bin/claude", "mcp", "remove", "sqlparse", "--scope", "user"],
        ["/usr/bin/claude", "mcp", "remove", "sqlparse", "--scope", "local"],
        ["/usr/bin/gemini", "mcp", "remove", "sqlparse"],
    ]
    out = capsys.readouterr().out
    assert f"Removed mcp server config from {tmp_path / '.cursor' / 'mcp.json'}" in out
    assert f"Removed skill → {skill}" in out
    assert "Removed all index files." in out


def test_uninstall_with_nothing_installed_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: None)
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "uninstall"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "No MCP server entries found." in out
    assert "No sqlparse skill found." in out


def test_uninstall_invalid_config_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("src.cli.install_mcp.find_claude_command", lambda: None)
    monkeypatch.setattr("src.cli.install_mcp.find_gemini_command", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "uninstall"])
    assert main() == 1
    assert "Failed to uninstall sqlparse" in capsys.readouterr().err


def test_binary_path_resolves_argv_and_path_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "sqlparse"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(binary), "install"])
    assert binary_path() == binary.resolve()

    real = tmp_path / "real" / "sqlparse"
    real.parent.mkdir()
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "bin" / "sqlparse"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.setattr(sys, "argv", ["sqlparse", "install"])
    monkeypatch.setattr("src.utils.shutil.which", lambda _name: str(link))
    assert binary_path() == real.resolve()


def test_windows_deeplink_and_cmd_install(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.cli.fastmcp_cli_standin import find_claude_command, open_deeplink, run_cli_command

    monkeypatch.setattr(sys, "platform", "win32")
    opened: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda url: opened.append(url), raising=False)
    assert open_deeplink("cursor://install", expected_scheme="cursor") is True
    assert opened == ["cursor://install"]
    assert open_deeplink("https://example", expected_scheme="cursor") is False

    recorded: dict[str, object] = {}

    def fake_run(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded["command"] = command
        recorded["executable"] = kwargs.get("executable")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.cli.fastmcp_cli_standin.subprocess.run", fake_run)
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    run_cli_command(
        [
            r"C:\Users\me\AppData\Roaming\npm\claude.cmd",
            "mcp",
            "add",
            "sqlparse",
            "--",
            r"C:\sqlparse.exe",
            "mcp",
        ]
    )
    assert str(recorded["executable"]).lower().endswith("cmd.exe")
    assert "sqlparse.exe" in str(recorded["command"])

    def fake_version(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[0].endswith("claude.cmd")
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout="Claude Code 1.0\n", stderr=""
        )

    monkeypatch.setattr("src.cli.fastmcp_cli_standin.subprocess.run", fake_version)
    monkeypatch.setattr(
        "src.cli.fastmcp_cli_standin.shutil.which",
        lambda name: r"C:\npm\claude.cmd" if name == "claude" else None,
    )
    assert find_claude_command() == r"C:\npm\claude.cmd"
