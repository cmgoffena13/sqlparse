"""Stand-ins for the FastMCP install helpers this CLI actually calls.

Importing ``fastmcp.cli`` loads the whole FastMCP command-line app, and Nuitka
then compiles Cyclopts, ``watchfiles``, and ``pyperclip`` into the binary.
These functions are the small slice ``install`` and ``uninstall`` need. Keep
this module free of ``fastmcp.cli`` imports.
"""

import base64
import logging
import ntpath
import os
import re
import shutil
import string
import subprocess
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote, urlparse

from fastmcp.mcp_config import StdioMCPServer

logger = logging.getLogger(__name__)

_BATCH_UNQUOTED_CHARS = frozenset(string.ascii_letters + string.digits + "#$*+-./:?@\\_")
_BATCH_PERCENT = "%%cd:~,%"


def _quote_batch_text(text: str) -> str:
    quoted: list[str] = ['"']
    backslashes = 0
    for char in text:
        if char == "\\":
            backslashes += 1
            quoted.append(char)
            continue
        if char == '"':
            quoted.append("\\" * backslashes + '""')
        elif char == "%":
            quoted.append(_BATCH_PERCENT)
        else:
            quoted.append(char)
        backslashes = 0
    quoted.append("\\" * backslashes + '"')
    return "".join(quoted)


def _quote_windows_batch_argument(argument: str) -> str:
    if "\r" in argument or "\n" in argument:
        raise ValueError(
            "Arguments passed to a Windows .cmd or .bat command cannot contain line breaks"
        )
    needs_quotes = argument == "" or argument.endswith("\\")
    for char in argument:
        if char.isascii():
            if char not in _BATCH_UNQUOTED_CHARS:
                needs_quotes = True
        elif unicodedata.category(char) == "Cc":
            needs_quotes = True
    if not needs_quotes:
        return argument
    return _quote_batch_text(argument)


def _windows_batch_command_line(command: Sequence[str]) -> str:
    script, *arguments = command
    if '"' in script or script.endswith("\\") or "\r" in script or "\n" in script:
        raise ValueError(f"Invalid Windows batch file path: {script!r}")
    parts = [_quote_batch_text(script)]
    parts.extend(_quote_windows_batch_argument(argument) for argument in arguments)
    return 'cmd.exe /e:on /v:off /d /s /c "' + " ".join(parts) + '"'


def _windows_command_processor() -> str:
    comspec = os.environ.get("COMSPEC", "")
    if ntpath.isabs(comspec):
        return comspec
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return ntpath.join(system_root, "System32", "cmd.exe")


def run_cli_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    if sys.platform == "win32" and command[0].lower().endswith((".cmd", ".bat")):
        return subprocess.run(  # noqa: S603
            _windows_batch_command_line(command),
            executable=_windows_command_processor(),
            check=True,
            capture_output=True,
            text=True,
        )
    return subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603


def open_deeplink(url: str, *, expected_scheme: str) -> bool:
    parsed = urlparse(url)
    opened = parsed.scheme == expected_scheme
    if not opened:
        logger.warning("Invalid deeplink scheme: %s, expected %s", parsed.scheme, expected_scheme)
    else:
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", url], check=True, capture_output=True)  # noqa: S603, S607
            elif sys.platform == "win32":
                os.startfile(url)  # noqa: S606
            else:
                subprocess.run(["xdg-open", url], check=True, capture_output=True)  # noqa: S603, S607
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            opened = False
    return opened


def generate_cursor_deeplink(server_name: str, server_config: StdioMCPServer) -> str:
    config_json = server_config.model_dump_json(exclude_none=True)
    config_b64 = base64.urlsafe_b64encode(config_json.encode()).decode()
    encoded_name = quote(server_name, safe="")
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={encoded_name}&config={config_b64}"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "sqlparse"


def generate_goose_deeplink(name: str, command: str, args: list[str]) -> str:
    params = [f"cmd={quote(command, safe='')}"]
    params.extend(f"arg={quote(arg, safe='')}" for arg in args)
    params.append(f"id={quote(_slugify(name), safe='')}")
    params.append(f"name={quote(name, safe='')}")
    params.append(f"description={quote('sqlparse MCP server', safe='')}")
    return f"goose://extension?{'&'.join(params)}"


def get_claude_config_path() -> Path | None:
    path: Path | None
    if sys.platform == "win32":
        path = Path(Path.home(), "AppData", "Roaming", "Claude")
    elif sys.platform == "darwin":
        path = Path(Path.home(), "Library", "Application Support", "Claude")
    elif sys.platform.startswith("linux"):
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"), "Claude")
    else:
        path = None
    if path is not None and not path.exists():
        path = None
    return path


def _command_reports_version(path: str, *, stdout_contains: str | None) -> bool:
    reports = False
    try:
        result = subprocess.run(  # noqa: S603
            [path, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        reports = True if stdout_contains is None else stdout_contains in result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        reports = False
    return reports


def find_claude_command() -> str | None:
    candidates = [shutil.which("claude")]
    candidates.extend(
        str(path)
        for path in (
            Path.home() / ".claude" / "local" / "claude",
            Path("/usr/local/bin/claude"),
            Path.home() / ".npm-global" / "bin" / "claude",
        )
    )
    found: str | None = None
    for candidate in candidates:
        if candidate and _command_reports_version(candidate, stdout_contains="Claude Code"):
            found = candidate
            break
    return found


def find_gemini_command() -> str | None:
    candidates = [shutil.which("gemini")]
    candidates.extend(
        str(path)
        for path in (
            Path.home() / ".gemini" / "local" / "gemini",
            Path("/usr/local/bin/gemini"),
            Path.home() / ".npm-global" / "bin" / "gemini",
            Path("/opt/homebrew/bin/gemini"),
        )
    )
    found: str | None = None
    for candidate in candidates:
        if candidate and _command_reports_version(candidate, stdout_contains=None):
            found = candidate
            break
    return found
