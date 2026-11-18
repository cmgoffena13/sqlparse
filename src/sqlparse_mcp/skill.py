import shutil
from pathlib import Path

import xxhash
import yaml

DESCRIPTION = "Use when navigating a SQLMesh project: models, kinds, audits, macros, and lineage."

_SKILL_BODY = """\
# IMPORTANT RULES
 - ALWAYS use sqlparse tools to read models, lineage, and indexed project files.
 - NEVER use ``read`` or ``grep`` on a model file when a sqlparse tool can answer.

# INSTRUCTIONS

1. Use ``example`` to confirm the sqlparse server is connected.

# CAVEATS
 - A macro is expanded away, so column lineage does not show which macro produced a column.
 - A macro change affects columns only after rendering before and after the change.
"""


def skill_frontmatter() -> str:
    dumped = yaml.safe_dump(
        {"name": "sqlparse", "description": DESCRIPTION},
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")
    return f"---\n{dumped}\n---\n\n"


SKILL_INSTRUCTIONS = skill_frontmatter() + _SKILL_BODY


def materialize_skill(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    path = base / "SKILL.md"
    path.write_text(SKILL_INSTRUCTIONS, encoding="utf-8")
    return path


def _vendor_skill_roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".claude" / "skills",
        Path("/etc/codex/skills"),
        home / ".codex" / "skills",
        home / ".copilot" / "skills",
        home / ".cursor" / "skills",
        home / ".gemini" / "skills",
        home / ".config" / "agents" / "skills",
        home / ".config" / "opencode" / "skills",
    ]


def available_skill_dirs() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for path in _vendor_skill_roots():
        if path.is_dir() and path not in seen:
            seen.add(path)
            found.append(path)
    return found


def sync_skill() -> list[Path]:
    written: list[Path] = []
    targets = available_skill_dirs()
    if not targets:
        print("No skill directories found.")
    else:
        skill_bytes = SKILL_INSTRUCTIONS.encode("utf-8")
        current_hash = xxhash.xxh128(skill_bytes).hexdigest()
        for target in targets:
            skill_dir = target / "sqlparse"
            skill_path = skill_dir / "SKILL.md"
            existing = skill_path.read_bytes() if skill_path.is_file() else b""
            if xxhash.xxh128(existing).hexdigest() != current_hash:
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_path.write_bytes(skill_bytes)
                written.append(skill_dir)
        for path in written:
            print(f"Synced skill → {path}")
    return written


def remove_skill() -> list[Path]:
    removed: list[Path] = []
    for target in available_skill_dirs():
        skill_dir = target / "sqlparse"
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            removed.append(skill_dir)
    if not removed:
        print("No sqlparse skill found.")
    for path in removed:
        print(f"Removed skill → {path}")
    return removed
