import hashlib
import os
import shutil
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

import xxhash

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv()


def snapshot_hash(values: Sequence[object]) -> str:
    payload = "|".join("" if value is None else str(value) for value in values)
    return xxhash.xxh128(payload.encode()).hexdigest()


def get_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if not isinstance(meipass, str):
            raise RuntimeError("frozen build missing sys._MEIPASS")
        pyproject_path = Path(meipass) / "pyproject.toml"
        if not pyproject_path.is_file():
            exe = Path(getattr(sys, "executable", None) or sys.argv[0])
            pyproject_path = exe.parent / "pyproject.toml"
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"Could not find pyproject.toml at {pyproject_path}")
    with pyproject_path.open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if not isinstance(version, str):
        raise TypeError("project.version must be a string")
    return version


def is_compiled() -> bool:
    return "__compiled__" in globals()


def binary_path() -> Path:
    invoked = Path(sys.argv[0])
    if not invoked.is_absolute():
        found = shutil.which(sys.argv[0])
        if found:
            invoked = Path(found)
    return invoked.resolve()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_sqlparse_config_dir(*parts: str) -> Path:
    override = os.environ.get("SQLPARSE_CONFIG_DIR")
    base = Path(override) if override else Path.home() / ".config" / "sqlparse"
    return ensure_dir(base.joinpath(*parts))


def db_path_for_index_root(index_root: Path) -> Path:
    key = str(index_root.resolve()).encode()
    digest = hashlib.sha256(key).hexdigest()
    return get_sqlparse_config_dir("indexes") / f"{digest}.db"


def line_count(file_bytes: bytes) -> int:
    text = file_bytes.decode("utf-8", errors="replace")
    count = text.count("\n")
    if text and not text.endswith("\n"):
        count += 1
    return count
