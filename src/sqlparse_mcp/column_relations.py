from collections import OrderedDict
from typing import Literal

from src.db import ProjectDB
from src.parse.column_lineage import (
    FINAL_QUERY,
    _qualified_name,
    final_query_name,
    model_query_name,
)
from src.sqlparse_mcp.format_utils import bullet, tree_glyphs

_FIND_COLUMNS_SQL = """
SELECT columns.id
FROM columns
INNER JOIN queries 
    ON queries.id = columns.query_id
INNER JOIN models 
    ON models.id = columns.model_id
WHERE models.qualified_name = ?
  AND queries.name = ?
  AND (
    columns.name = ?
    OR columns.from_table || '.' || columns.name = ?
    OR columns.qualified_name = ?
  )
"""

_DEPENDENCIES_SQL = """
SELECT
    models.qualified_name AS model_name,
    models.kind AS model_kind,
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
    models.kind AS model_kind,
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
    resolved = model_query_name(model_name, relative)
    if relative == FINAL_QUERY:
        resolved = final_query_name(model_name)
    elif relative.startswith(f"{model_name}/"):
        resolved = relative
    return resolved


def _relative_query(model_name: str, query_name: str) -> str:
    relative = query_name
    if query_name.startswith(f"{model_name}/"):
        relative = query_name[len(model_name) + 1 :]
    return relative


def _model_label(model_name: str, kind: str, mark_external: bool) -> str:
    label = model_name
    if mark_external and kind == "EXTERNAL":
        label = f"{model_name} (EXTERNAL)"
    return label


def _column_label(from_table: str | None, column_name: str) -> str:
    label = column_name
    if from_table is not None:
        label = f"{from_table}.{column_name}"
    return label


def _external_model_names(db: ProjectDB) -> set[str]:
    return {
        str(row["qualified_name"])
        for row in db.connection.execute(
            "SELECT qualified_name FROM models WHERE kind = 'EXTERNAL'"
        )
    }


def _column_suffix(ref_kind: str, external: bool, count: int) -> str:
    suffix = f" ({ref_kind})"
    if external:
        suffix = f" (EXTERNAL){suffix}"
    if count > 1:
        suffix = f"{suffix} ({count})"
    return suffix


def _dependency_tree(
    grouped: OrderedDict[
        str, tuple[str, OrderedDict[str, OrderedDict[tuple[str, str, bool], int]]]
    ],
) -> list[str]:
    lines: list[str] = []
    for header, queries in grouped.values():
        if lines:
            lines.append("")
        lines.append(header)
        query_items = list(queries.items())
        last_query = len(query_items) - 1
        for query_index, (relative_query, columns) in enumerate(query_items):
            connector, continuation = tree_glyphs(query_index == last_query, wide=True)
            lines.append(f"{connector}{relative_query}")
            column_items = list(columns.items())
            last_column = len(column_items) - 1
            for column_index, ((label, ref_kind, external), count) in enumerate(column_items):
                column_connector, _column_continuation = tree_glyphs(
                    column_index == last_column, wide=True
                )
                lines.append(
                    f"{continuation}{column_connector}{label}"
                    f"{_column_suffix(ref_kind, external, count)}"
                )
    return lines


def _format_groups(
    rows: list[tuple[str, str, str, str | None, str, str]],
    test_rows: list[tuple[str, str]],
    mark_external: bool,
    external_names: set[str],
) -> str:
    grouped: OrderedDict[
        str, tuple[str, OrderedDict[str, OrderedDict[tuple[str, str, bool], int]]]
    ] = OrderedDict()
    for model_name, kind, query_name, from_table, column_name, ref_kind in rows:
        _header, queries = grouped.setdefault(
            model_name, (_model_label(model_name, kind, mark_external), OrderedDict())
        )
        columns = queries.setdefault(_relative_query(model_name, query_name), OrderedDict())
        external = mark_external and from_table in external_names
        key = (_column_label(from_table, column_name), ref_kind, external)
        columns[key] = columns.get(key, 0) + 1
    lines = _dependency_tree(grouped)
    if test_rows:
        if lines:
            lines.append("")
        lines.append("## Tests")
        lines.append("")
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
        resolved = _resolve_query_name(model_key, query_name)
        relative = _relative_query(model_key, resolved)
        from_table, _, name = column_key.rpartition(".")
        qualified_name = _qualified_name(resolved, from_table or None, name or column_key)
        column_ids = [
            int(row["id"])
            for row in db.connection.execute(
                _FIND_COLUMNS_SQL,
                (model_key, relative, column_key, column_key, qualified_name),
            )
        ]
        if not column_ids:
            result = "No column found."
        else:
            placeholders = ", ".join("?" for _ in column_ids)
            sql = _DEPENDENTS_SQL if relation == "dependents" else _DEPENDENCIES_SQL
            rows = [
                (
                    str(row["model_name"]),
                    str(row["model_kind"]),
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
            result = _format_groups(
                rows,
                test_rows,
                relation == "dependencies",
                _external_model_names(db),
            )
    return result
