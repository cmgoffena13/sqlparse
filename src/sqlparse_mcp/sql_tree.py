from pathlib import Path

from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import tree_glyphs

_MODELS_BY_NAME_SQL = """
SELECT id, qualified_name
FROM models
WHERE qualified_name = ?
ORDER BY qualified_name
"""

_MODELS_BY_FILE_SQL = """
SELECT models.id, models.qualified_name
FROM models
INNER JOIN files
    ON files.id = models.file_id
WHERE files.path = ?
ORDER BY models.qualified_name
"""

_QUERIES_SQL = """
SELECT
    name,
    depth,
    line_start,
    select_col_count,
    join_statement_count,
    where_condition_count,
    group_by_col_count
FROM queries
WHERE model_id = ?
"""


def _parent_indexes(nodes: list[tuple[int, int]]) -> list[int | None]:
    parents: list[int | None] = []
    for depth, line_start in nodes:
        parent: int | None = None
        if depth > 0:
            fallback: int | None = None
            fallback_line = -1
            best_line = -1
            for earlier, (earlier_depth, earlier_line) in enumerate(nodes):
                shallower = earlier_depth == depth - 1
                if shallower and (fallback is None or earlier_line < fallback_line):
                    fallback = earlier
                    fallback_line = earlier_line
                if shallower and earlier_line <= line_start and earlier_line >= best_line:
                    best_line = earlier_line
                    parent = earlier
            if parent is None:
                parent = fallback
        parents.append(parent)
    return parents


def _query_lines(
    children: dict[int | None, list[int]],
    labels: list[str],
    parent: int | None,
    prefix: str,
) -> list[str]:
    lines: list[str] = []
    kids = children.get(parent, [])
    last_index = len(kids) - 1
    for index, child in enumerate(kids):
        connector, continuation = tree_glyphs(index == last_index, wide=True)
        lines.append(f"{prefix}{connector}{labels[child]}")
        lines.extend(_query_lines(children, labels, child, prefix + continuation))
    return lines


def _count_label(column_count: int, join_count: int, where_count: int, group_count: int) -> str:
    column_label = "1 select column" if column_count == 1 else f"{column_count} select columns"
    parts = [column_label]
    if join_count:
        parts.append("1 join" if join_count == 1 else f"{join_count} joins")
    if where_count:
        where_label = "1 where condition" if where_count == 1 else f"{where_count} where conditions"
        parts.append(where_label)
    if group_count:
        grouped = "1 column" if group_count == 1 else f"{group_count} columns"
        parts.append(f"grouped by {grouped}")
    return ", ".join(parts)


def _normalize_file_path(target: str, root: Path) -> str:
    path = Path(target.strip())
    normalized = path.as_posix()
    if path.is_absolute():
        normalized = path.resolve().relative_to(root.resolve()).as_posix()
    elif normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def get_sql_tree(db: ProjectDB, target: str) -> str:
    key = target.strip()
    result = "No target given; pass a model name or file path."
    if key:
        models = [
            (int(row["id"]), str(row["qualified_name"]))
            for row in db.connection.execute(_MODELS_BY_NAME_SQL, (key,))
        ]
        if not models:
            file_path = _normalize_file_path(key, db.root)
            models = [
                (int(row["id"]), str(row["qualified_name"]))
                for row in db.connection.execute(_MODELS_BY_FILE_SQL, (file_path,))
            ]
        if not models:
            result = "No model found."
        else:
            lines: list[str] = []
            for model_id, model_name in models:
                if lines:
                    lines.append("")
                lines.append(model_name)
                fetched = list(db.connection.execute(_QUERIES_SQL, (model_id,)))
                fetched.sort(
                    key=lambda row: (int(row["depth"]), int(row["line_start"]), str(row["name"]))
                )
                labels: list[str] = []
                nodes: list[tuple[int, int]] = []
                for row in fetched:
                    relative = str(row["name"])
                    label = _count_label(
                        int(row["select_col_count"]),
                        int(row["join_statement_count"]),
                        int(row["where_condition_count"]),
                        int(row["group_by_col_count"]),
                    )
                    labels.append(f"{relative} ({label})")
                    nodes.append((int(row["depth"]), int(row["line_start"])))
                children: dict[int | None, list[int]] = {}
                for index, parent in enumerate(_parent_indexes(nodes)):
                    children.setdefault(parent, []).append(index)
                lines.extend(_query_lines(children, labels, None, ""))
            result = "\n".join(lines) + "\n"
    return result
