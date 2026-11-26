import shutil
from pathlib import Path

import xxhash
import yaml

DESCRIPTION = "Use when navigating SQLMesh projects: models, queries, columns, and lineage."

_SKILL_BODY = """\
# IMPORTANT RULES
 - ALWAYS use sqlparse tools to read queries, audits, macros, and tests.
 - NEVER use ``read`` or ``grep .`` on a SQL file or directory.
 - Only ``include_tests`` when making changes to the codebase. 
 - DO NOT ``include_tests`` when investigating unless explicitly asked.
 - If ``workspace://sqlparse/root`` does not match the project, STOP IMMEDIATELY.
    - Inform the user to restart the sqlparse MCP server.

# Query Input
 - Query names are prefixed with ``$``. 
 - A single ``$`` is the final output query of the model.
 - Model Config is treated as a query and called ``$CONFIG``.
 - EXTERNAL models have an $EXTERNAL placeholder value for query text.
 - Ex. ``$``, ``$cte_name``, or ``$CONFIG``.

# Catalog Input
 - Omitting the catalog name from tool calls, data model names, or column names
   implies the project's default catalog.
 - The default catalog name is omitted from data model names and column names.

# INSTRUCTIONS

The information that is provided to you will determine the tool you should use.

## You are given the file name or model name.
1. Use ``get_model`` to read the model's SQL tree, macro refs, and audit refs.
2. Use ``get_query`` to read a query's definition.
3. Use ``get_query_schema`` to read a query's output schema.

## You are given the file name or model name and a query name.
1. Use ``get_query`` to read the query's definition.
2. Use ``get_query_schema`` to read the query's output schema.

## You are given a file name and line numbers from ``grep`` or a ``code selection`` in Cursor.
1. Use ``get_span_at_lines`` to read the query, audit, macro, or test at a line range.

## You are NOT given a file name, model name, or query name.
1. Investigate the project using ``list_catalogs``, ``list_schemas``, ``list_models``, and keywords
2. Use ``get_model`` to read the model's SQL tree, macro refs, and audit refs.
3. Use ``get_query`` to read a query's definition.
4. Use ``get_query_schema`` to read a query's output schema.

### Investigate the project using keywords

#### ``glob``
 - Use when the clue is a path or a file name.

#### ``grep``
 - Use when the clue is specific text in file contents.
 - Use `-n` to get the line number and then use ``get_span_at_lines`` to get the span.
 - Use ``get_model_relations`` for model dependents or dependencies; DO NOT grep for this.
 - Use ``get_column_relations`` for column dependents or dependencies; DO NOT grep for this.

#### ``search``
 - Use when the clue is a reference to a model, query, or column.

# RESOURCES

## ``workspace://sqlparse/root``
 - Only use when results appear to be from the wrong project.

## ``stats://sqlparse/sessions``
 - Only use when the question is about sqlparse sessions, cost, or decision quality.

# RECOMMENDATIONS
 - Enable SQLMesh's ``AmbiguousOrInvalidColumn`` linter rule to to get proper column names / types.
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
