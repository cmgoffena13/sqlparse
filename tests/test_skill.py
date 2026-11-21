from pathlib import Path

import pytest
import yaml

from src.sqlparse_mcp.skill import (
    DESCRIPTION,
    SKILL_INSTRUCTIONS,
    available_skill_dirs,
    materialize_skill,
    sync_skill,
)


def test_available_skill_dirs_returns_existing_vendor_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cursor = tmp_path / ".cursor" / "skills"
    cursor.mkdir(parents=True)
    assert cursor in available_skill_dirs()


def test_frontmatter_description_parses() -> None:
    frontmatter, _, body = SKILL_INSTRUCTIONS.partition("\n---\n")
    parsed = yaml.safe_load(frontmatter.removeprefix("---\n"))
    assert parsed == {"name": "sqlparse", "description": DESCRIPTION}
    assert body.lstrip("\n").startswith("# IMPORTANT RULES")
    assert "AmbiguousOrInvalidColumn" in body


def test_sync_skips_skill_when_hash_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    monkeypatch.setattr("src.sqlparse_mcp.skill.available_skill_dirs", lambda: [skill_root])

    assert sync_skill() == [skill_root / "sqlparse"]
    written = skill_root / "sqlparse" / "SKILL.md"
    stamp = written.stat().st_mtime_ns

    assert sync_skill() == []
    assert written.stat().st_mtime_ns == stamp
    assert written.read_text(encoding="utf-8") == SKILL_INSTRUCTIONS


def test_materialize_skill_writes_skill_md(tmp_path: Path) -> None:
    config = tmp_path / "sqlparse"
    written = materialize_skill(config)
    assert written == config / "SKILL.md"
    assert written.read_text(encoding="utf-8") == SKILL_INSTRUCTIONS
