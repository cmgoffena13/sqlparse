from collections import OrderedDict
from typing import Literal

from src.db import ProjectDB
from src.parse.column_lineage import FINAL_QUERY, final_query_name
from src.sqlparse_mcp.format_utils import bullet

_FIND_COLUMNS_SQL = """
SELECT id
FROM columns
WHERE qualified_name = ?
"""

_DEPENDENCIES_SQL = """
SELECT
    models.qualified_name AS model_name,
    lineage.source_query_name AS query_name,
    columns.from_table AS from_table,
    columns.name AS column_name,
    lineage.ref_kind AS ref_kind
FROM column_lineage AS lineage
INNER JOIN columns 
    ON columns.id = lineage.source_column_id
INNER JOIN models 
    ON models.id = lineage.source_models_id
WHERE lineage.ref_column_id IN ({placeholders})
ORDER BY model_name, query_name, column_name, from_table, ref_kind
"""

_DEPENDENTS_SQL = """
SELECT
    models.qualified_name AS model_name,
    lineage.ref_column_query_name AS query_name,
    columns.from_table AS from_table,
    columns.name AS column_name,
    lineage.ref_kind AS ref_kind
FROM column_lineage AS lineage
INNER JOIN columns 
    ON columns.id = lineage.ref_column_id
INNER JOIN models 
    ON models.id = lineage.ref_column_model_id
WHERE lineage.source_column_id IN ({placeholders})
ORDER BY model_name, query_name, column_name, from_table, ref_kind
"""

_TEST_DEPENDENTS_SQL = """
SELECT DISTINCT 
    files.path AS file_path, 
    tests.name AS test_name
FROM test_references
INNER JOIN tests 
    ON tests.id = test_references.test_id
INNER JOIN files 
    ON files.id = tests.file_id
WHERE test_references.column_id IN ({placeholders})
ORDER BY file_path, test_name
"""


def _resolve_query_name(model_name: str, query_name: str | None) -> str:
    relative = (query_name or "").strip() or FINAL_QUERY
    resolved = f"{model_name}.{relative}"
    if relative == FINAL_QUERY:
        resolved = final_query_name(model_name)
    elif relative.startswith(f"{model_name}."):
        resolved = relative
    return resolved


def _relative_query(model_name: str, query_name: str) -> str:
    relative = query_name
    if query_name.startswith(f"{model_name}."):
        relative = query_name[len(model_name) + 1 :]
    return relative


def _column_label(from_table: str | None, column_name: str) -> str:
    label = column_name
    if from_table is not None:
        label = f"{from_table}.{column_name}"
    return label


def _format_groups(
    rows: list[tuple[str, str, str | None, str, str]],
    test_rows: list[tuple[str, str]],
) -> str:
    grouped: OrderedDict[str, OrderedDict[str, OrderedDict[tuple[str, str], int]]] = OrderedDict()
    for model_name, query_name, from_table, column_name, ref_kind in rows:
        queries = grouped.setdefault(model_name, OrderedDict())
        columns = queries.setdefault(_relative_query(model_name, query_name), OrderedDict())
        key = (_column_label(from_table, column_name), ref_kind)
        columns[key] = columns.get(key, 0) + 1
    lines: list[str] = []
    for model_name, queries in grouped.items():
        if lines:
            lines.append("")
        lines.append(model_name)
        for relative_query, columns in queries.items():
            lines.append(f"  {relative_query}")
            for (label, ref_kind), count in columns.items():
                suffix = f" ({ref_kind})"
                if count > 1:
                    suffix = f"{suffix} ({count})"
                lines.append(bullet(f"{label}{suffix}", lead="  "))
    if test_rows:
        if lines:
            lines.append("")
        lines.append("## Tests")
        by_file: OrderedDict[str, list[str]] = OrderedDict()
        for file_path, test_name in test_rows:
            by_file.setdefault(file_path, []).append(test_name)
        for file_path, names in by_file.items():
            lines.append(file_path)
            for name in names:
                lines.append(bullet(name))
    result = "No relations."
    if lines:
        result = "\n".join(lines) + "\n"
    return result


def get_column_relations(
    db: ProjectDB,
    model_name: str,
    query_name: str | None,
    column_name: str,
    relation: Literal["dependents", "dependencies"],
    include_tests: bool = False,
) -> str:
    model_key = model_name.strip()
    column_key = column_name.strip()
    result = "No model name given; pass a non-empty model name."
    if model_key and not column_key:
        result = "No column name given; pass a non-empty column name."
    if model_key and column_key:
        qualified_name = f"{_resolve_query_name(model_key, query_name)}.{column_key}"
        column_ids = [
            int(row["id"]) for row in db.connection.execute(_FIND_COLUMNS_SQL, (qualified_name,))
        ]
        if not column_ids:
            result = "No column found."
        else:
            placeholders = ", ".join("?" for _ in column_ids)
            sql = _DEPENDENTS_SQL if relation == "dependents" else _DEPENDENCIES_SQL
            rows = [
                (
                    str(row["model_name"]),
                    str(row["query_name"]),
                    str(row["from_table"]) if row["from_table"] is not None else None,
                    str(row["column_name"]),
                    str(row["ref_kind"]),
                )
                for row in db.connection.execute(
                    sql.format(placeholders=placeholders),
                    column_ids,
                )
            ]
            test_rows: list[tuple[str, str]] = []
            if include_tests and relation == "dependents":
                test_rows = [
                    (str(row["file_path"]), str(row["test_name"]))
                    for row in db.connection.execute(
                        _TEST_DEPENDENTS_SQL.format(placeholders=placeholders),
                        column_ids,
                    )
                ]
            result = _format_groups(rows, test_rows)
    return result
