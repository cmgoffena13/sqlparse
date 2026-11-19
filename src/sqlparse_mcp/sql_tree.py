from collections import OrderedDict
from pathlib import Path

from src.db import ProjectDB
from src.parse.column_lineage import FINAL_QUERY
from src.sqlparse_mcp.format_utils import bullet

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
SELECT query_name, COUNT(*) AS column_count
FROM columns
WHERE model_id = ?
GROUP BY query_name
ORDER BY query_name
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


def _relative_query(model_name: str, query_name: str) -> str:
    relative = query_name
    if query_name.startswith(f"{model_name}."):
        relative = query_name[len(model_name) + 1 :]
    return relative


def _query_sort_key(relative: str) -> tuple[int, str]:
    return (0 if relative == FINAL_QUERY else 1, relative)


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
                column_counts: OrderedDict[str, int] = OrderedDict()
                for row in db.connection.execute(_QUERY_COLUMNS_SQL, (model_id,)):
                    column_counts[str(row["query_name"])] = int(row["column_count"])
                clause_counts: dict[str, dict[str, int]] = {}
                for row in db.connection.execute(_QUERY_CLAUSE_COUNTS_SQL, (model_id,)):
                    query_name = str(row["query_name"])
                    kinds = clause_counts.setdefault(query_name, {})
                    kinds[str(row["ref_kind"])] = int(row["kind_count"])
                relatives = sorted(
                    (
                        (_relative_query(model_name, query_name), query_name)
                        for query_name in column_counts
                    ),
                    key=lambda item: _query_sort_key(item[0]),
                )
                for relative, query_name in relatives:
                    kinds = clause_counts.get(query_name, {})
                    label = _count_label(
                        column_counts[query_name],
                        kinds.get("join", 0),
                        kinds.get("where", 0),
                    )
                    lines.append(bullet(f"{relative} ({label})"))
            result = "\n".join(lines) + "\n"
    return result
