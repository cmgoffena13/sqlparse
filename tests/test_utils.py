import os
import subprocess
import sys
from pathlib import Path

import pytest
import xxhash

from src.utils import get_version, is_compiled, snapshot_hash


def test_snapshot_hash_joins_values_and_blank_nones() -> None:
    payload = "1||full|note"
    assert snapshot_hash([1, None, "full", "note"]) == xxhash.xxh128(payload.encode()).hexdigest()
    assert snapshot_hash([1, None, "full", "note"]) == snapshot_hash([1, "", "full", "note"])
    assert snapshot_hash([1, None, "full", "note"]) != snapshot_hash([2, None, "full", "note"])


def test_env_file_sets_the_config_dir(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SQLPARSE_CONFIG_DIR=from-dotenv\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("SQLPARSE_CONFIG_DIR", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.utils import get_sqlparse_config_dir; print(get_sqlparse_config_dir())",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "from-dotenv"
    assert (tmp_path / "from-dotenv").is_dir()


def test_is_compiled_is_false_under_pytest() -> None:
    assert is_compiled() is False


def test_get_version_frozen_with_meipass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    meipass = tmp_path / "meipass"
    meipass.mkdir()
    (meipass / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert get_version() == "9.9.9"


def test_get_version_frozen_falls_back_to_exe_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    (exe_dir / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    exe = exe_dir / "sqlparse"
    exe.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "empty-meipass"), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert get_version() == "1.2.3"


def test_get_version_frozen_missing_meipass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", None, raising=False)
    with pytest.raises(RuntimeError, match="_MEIPASS"):
        get_version()
