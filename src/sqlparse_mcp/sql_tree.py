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

_QUERY_COLUMNS_SQL = """
SELECT queries.name, queries.depth, queries.line_start, COUNT(*) AS column_count
FROM columns
INNER JOIN queries ON queries.id = columns.query_id
WHERE columns.model_id = ?
GROUP BY queries.id
"""

_QUERY_CLAUSE_COUNTS_SQL = """
SELECT
    ref_column_query_name AS query_name,
    ref_kind,
    COUNT(*) AS kind_count
FROM column_lineage
WHERE ref_column_model_id = ?
  AND ref_kind IN ('join', 'where')
GROUP BY ref_column_query_name, ref_kind
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


def _count_label(column_count: int, join_count: int, where_count: int) -> str:
    parts = [f"{column_count} columns"]
    if where_count:
        parts.append(f"{where_count} wheres" if where_count != 1 else "1 where")
    if join_count:
        parts.append(f"{join_count} joins" if join_count != 1 else "1 join")
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
                clause_counts: dict[str, dict[str, int]] = {}
                for row in db.connection.execute(_QUERY_CLAUSE_COUNTS_SQL, (model_id,)):
                    query_name = str(row["query_name"])
                    kinds = clause_counts.setdefault(query_name, {})
                    kinds[str(row["ref_kind"])] = int(row["kind_count"])
                fetched = list(db.connection.execute(_QUERY_COLUMNS_SQL, (model_id,)))
                fetched.sort(
                    key=lambda row: (int(row["depth"]), int(row["line_start"]), str(row["name"]))
                )
                labels: list[str] = []
                nodes: list[tuple[int, int]] = []
                for row in fetched:
                    relative = str(row["name"])
                    kinds = clause_counts.get(f"{model_name}/{relative}", {})
                    label = _count_label(
                        int(row["column_count"]),
                        kinds.get("join", 0),
                        kinds.get("where", 0),
                    )
                    labels.append(f"{relative} ({label})")
                    nodes.append((int(row["depth"]), int(row["line_start"])))
                children: dict[int | None, list[int]] = {}
                for index, parent in enumerate(_parent_indexes(nodes)):
                    children.setdefault(parent, []).append(index)
                lines.extend(_query_lines(children, labels, None, ""))
            result = "\n".join(lines) + "\n"
    return result
