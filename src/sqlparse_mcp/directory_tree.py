import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import file_label, tree_glyphs

_CONFIG_FILES_SQL = """
SELECT name
FROM files
WHERE is_config
ORDER BY path
"""

_TREE_SQL = """
SELECT
    'directory' AS row_type,
    id,
    parent_id,
    name,
    NULL AS line_count
FROM directories
UNION ALL
SELECT
    'file' AS row_type,
    id,
    directory_id AS parent_id,
    name,
    line_count
FROM files
"""

_SUBTREE_SQL = """
SELECT
    'directory' AS row_type,
    id,
    parent_id,
    name,
    NULL AS line_count
FROM directories
WHERE path >= ? AND path < ?
UNION ALL
SELECT
    'file' AS row_type,
    id,
    directory_id AS parent_id,
    name,
    line_count
FROM files
WHERE path >= ? AND path < ?
"""


def _normalize_directory_path(directory_path: str, root: Path) -> str:
    raw = directory_path.strip().replace("\\", "/")
    if not raw:
        raise ValueError("directory_path is empty")
    resolved_root = root.resolve()
    return (resolved_root / raw).resolve().relative_to(resolved_root).as_posix()


def _children_by_parent(
    rows: Iterable[sqlite3.Row],
) -> dict[int | None, list[tuple[bool, sqlite3.Row]]]:
    children_by_parent_id: dict[int | None, list[tuple[bool, sqlite3.Row]]] = defaultdict(list)
    for row in rows:
        is_directory = row["row_type"] == "directory"
        parent_id = None if row["parent_id"] is None else int(row["parent_id"])
        children_by_parent_id[parent_id].append((is_directory, row))
    for sibling_list in children_by_parent_id.values():
        sibling_list.sort(
            key=lambda item: (not item[0], str(item[1]["name"]).lower()),
        )
    return children_by_parent_id


def _lines_under_parent(
    children_by_parent_id: dict[int | None, list[tuple[bool, sqlite3.Row]]],
    parent_key: int | None,
    branch_prefix: str,
) -> list[str]:
    lines: list[str] = []
    siblings = children_by_parent_id.get(parent_key, ())
    last_index = len(siblings) - 1
    for index, (is_directory, row) in enumerate(siblings):
        connector, continuation = tree_glyphs(index == last_index, wide=True)
        if is_directory:
            display_name = f"{row['name']}/"
        else:
            display_name = file_label(str(row["name"]), int(row["line_count"] or 0))
        lines.append(f"{branch_prefix}{connector}{display_name}")
        if is_directory:
            lines.extend(
                _lines_under_parent(
                    children_by_parent_id,
                    int(row["id"]),
                    branch_prefix + continuation,
                )
            )
    return lines


def _render(
    children_by_parent_id: dict[int | None, list[tuple[bool, sqlite3.Row]]],
    root_key: int | None,
    root_label: str,
) -> str:
    body_lines = _lines_under_parent(children_by_parent_id, root_key, "")
    result = root_label.rstrip("/") or "."
    if body_lines:
        result = root_label + "\n" + "\n".join(body_lines)
    return result


def get_directory_tree(db: ProjectDB, directory_path: str | None) -> str:
    scoped = None
    result = ""
    if directory_path and directory_path.strip():
        try:
            normalized = _normalize_directory_path(directory_path, db.root).rstrip("/")
        except ValueError as exc:
            result = str(exc)
            normalized = ""
        if not result and normalized not in ("", "."):
            scoped = normalized
    if not result and scoped is None:
        rows = db.connection.execute(_TREE_SQL)
        result = _render(_children_by_parent(rows), None, ".")
        config_lines = [
            f"PROJECT CONFIG FILE: {row['name']}"
            for row in db.connection.execute(_CONFIG_FILES_SQL)
        ]
        if config_lines:
            result = "\n".join(config_lines) + "\n" + result
    elif not result:
        dir_row = db.connection.execute(
            "SELECT id, path FROM directories WHERE path = ?",
            (scoped,),
        ).fetchone()
        if dir_row is None:
            result = "No directory found."
        else:
            prefix = f"{dir_row['path']}/"
            upper = f"{dir_row['path']}0"
            rows = db.connection.execute(_SUBTREE_SQL, (prefix, upper, prefix, upper))
            result = _render(
                _children_by_parent(rows),
                int(dir_row["id"]),
                f"{dir_row['path']}/",
            )
    return result
