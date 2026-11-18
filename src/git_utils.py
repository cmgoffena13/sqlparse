import os
import subprocess
from functools import lru_cache
from pathlib import Path

from pathspec import PathSpec

_GIT_TIMEOUT_S = 5

INDEX_ALWAYS_IGNORE_NAMES = frozenset(
    {
        ".git",
        ".venv",
        ".env",
        ".DS_Store",
        ".gitignore",
        "__pycache__",
        "dist",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".vscode",
        ".sqlparse",
        ".cache",
        "logs",
    }
)


@lru_cache
def _path_spec_for_root(gitignore_path: Path, _gitignore_mtime: float) -> PathSpec:
    text = gitignore_path.read_text(encoding="utf-8", errors="replace")
    return PathSpec.from_lines("gitignore", text.splitlines())


def is_git_controlled(path: Path) -> bool:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    controlled = False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],  # noqa: S607
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
            timeout=_GIT_TIMEOUT_S,
            env=env,
        )
        controlled = bool(result.stdout.strip())
    except OSError, subprocess.SubprocessError:
        controlled = False
    return controlled


def path_spec_for_indexing(root: Path) -> PathSpec:
    resolved = root.resolve()
    gitignore_path = resolved / ".gitignore"
    if not is_git_controlled(resolved):
        raise FileNotFoundError(f"{resolved} is not a git repository; are you in a git repository?")
    return (
        _path_spec_for_root(gitignore_path, gitignore_path.stat().st_mtime)
        if gitignore_path.is_file()
        else PathSpec.from_lines("gitignore", [])
    )


def relative_path_is_ignored(relative: str, is_directory: bool, spec: PathSpec) -> bool:
    if os.path.isabs(relative):  # noqa: PTH117
        raise ValueError("relative path must not be absolute")
    ignored = False
    for part in relative.split("/"):
        if part in INDEX_ALWAYS_IGNORE_NAMES:
            ignored = True
    if not ignored and is_directory:
        ignored = spec.match_file(relative + "/") or spec.match_file(relative)
    if not ignored and not is_directory:
        ignored = spec.match_file(relative)
    return ignored
