from collections import OrderedDict
from typing import Literal

from src.db import ProjectDB
from src.parse.column_lineage import FINAL_QUERY, final_query_name, model_query_name
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
  AND columns.column_name = ?
"""

_DEPENDENCIES_SQL = """
SELECT
    ref_models.qualified_name AS ref_model_name,
    ref_models.kind AS ref_model_kind,
    lineage.ref_column_query_name AS ref_query_name,
    ref_columns.from_table AS ref_from_table,
    ref_columns.name AS ref_output_name,
    lineage.ref_kind,
    lineage.source_column_id,
    source_models.qualified_name AS source_model_name,
    source_models.kind AS source_model_kind,
    source_columns.name AS source_output_name
FROM column_lineage AS lineage
INNER JOIN columns AS ref_columns
    ON ref_columns.id = lineage.ref_column_id
INNER JOIN models AS ref_models
    ON ref_models.id = lineage.ref_column_model_id
INNER JOIN columns AS source_columns
    ON source_columns.id = lineage.source_column_id
INNER JOIN models AS source_models
    ON source_models.id = lineage.source_models_id
WHERE lineage.ref_column_id IN ({placeholders})
ORDER BY ref_model_name, ref_query_name, ref_output_name, ref_from_table, lineage.ref_kind
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


_KIND_ORDER = ("select", "join", "where", "group", "alias", "expression")


def _use_label(kinds: list[str]) -> str:
    ordered = [kind for kind in _KIND_ORDER if kind in kinds]
    ordered.extend(kind for kind in kinds if kind not in ordered)
    return f" ({', '.join(ordered)})"


def _column_suffix(ref_kind: str, count: int) -> str:
    suffix = f" ({ref_kind})"
    if count > 1:
        suffix = f"{suffix} ({count})"
    return suffix


def _dependency_tree(
    grouped: OrderedDict[str, tuple[str, bool, OrderedDict[str, OrderedDict[str, list[str]]]]],
) -> list[str]:
    lines: list[str] = []
    for header, hide_query, queries in grouped.values():
        if lines:
            lines.append("")
        lines.append(header)
        query_items = list(queries.items())
        if hide_query:
            column_items = [item for _query, columns in query_items for item in columns.items()]
            last_column = len(column_items) - 1
            for column_index, (label, kinds) in enumerate(column_items):
                connector, _continuation = tree_glyphs(column_index == last_column, wide=True)
                lines.append(f"{connector}{label}{_use_label(kinds)}")
        else:
            last_query = len(query_items) - 1
            for query_index, (relative_query, columns) in enumerate(query_items):
                connector, continuation = tree_glyphs(query_index == last_query, wide=True)
                lines.append(f"{connector}{relative_query}")
                column_items = list(columns.items())
                last_column = len(column_items) - 1
                for column_index, (label, kinds) in enumerate(column_items):
                    column_connector, _column_continuation = tree_glyphs(
                        column_index == last_column, wide=True
                    )
                    lines.append(f"{continuation}{column_connector}{label}{_use_label(kinds)}")
    return lines


def _format_groups(
    rows: list[tuple[str, str, str, str | None, str, str]],
    test_rows: list[tuple[str, str]],
    mark_external: bool,
) -> str:
    grouped: OrderedDict[str, tuple[str, bool, OrderedDict[str, OrderedDict[str, list[str]]]]] = (
        OrderedDict()
    )
    for model_name, kind, query_name, from_table, column_name, ref_kind in rows:
        _header, _hide_query, queries = grouped.setdefault(
            model_name,
            (
                _model_label(model_name, kind, mark_external),
                mark_external and kind == "EXTERNAL",
                OrderedDict(),
            ),
        )
        columns = queries.setdefault(_relative_query(model_name, query_name), OrderedDict())
        label = _column_label(from_table, column_name)
        kinds = columns.setdefault(label, [])
        if ref_kind not in kinds:
            kinds.append(ref_kind)
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


def _fetch_dependencies(
    db: ProjectDB, column_ids: list[int]
) -> list[tuple[str, str, str, str | None, str, str, int, str, str, str]]:
    placeholders = ", ".join("?" for _ in column_ids)
    return [
        (
            str(row["ref_model_name"]),
            str(row["ref_model_kind"]),
            str(row["ref_query_name"]),
            str(row["ref_from_table"]) if row["ref_from_table"] is not None else None,
            str(row["ref_output_name"]),
            str(row["ref_kind"]),
            int(row["source_column_id"]),
            str(row["source_model_name"]),
            str(row["source_model_kind"]),
            str(row["source_output_name"]),
        )
        for row in db.connection.execute(
            _DEPENDENCIES_SQL.format(placeholders=placeholders),
            column_ids,
        )
    ]


def _relation_text(
    model_name: str,
    kind: str,
    query_name: str,
    column: str,
    ref_kind: str,
    count: int,
) -> str:
    text = f"{model_name} / EXTERNAL / {column}"
    if kind != "EXTERNAL":
        text = (
            f"{model_name} / {_relative_query(model_name, query_name)} / {column}"
            f"{_column_suffix(ref_kind, count)}"
        )
    return text


def _dependency_nodes(
    db: ProjectDB,
    column_ids: list[int],
    seen: set[int],
) -> list[tuple[str, list]]:
    grouped: OrderedDict[tuple[str, str, str, str, str, int], int] = OrderedDict()
    sources: dict[int, tuple[str, str, str]] = {}
    for (
        model_name,
        kind,
        query_name,
        from_table,
        name,
        ref_kind,
        source_id,
        source_model_name,
        source_model_kind,
        source_name,
    ) in _fetch_dependencies(db, column_ids):
        if kind == "EXTERNAL":
            column = name
            ref_kind = ""
        else:
            column = _column_label(from_table, name)
        key = (model_name, kind, query_name, column, ref_kind, source_id)
        grouped[key] = grouped.get(key, 0) + 1
        sources[source_id] = (source_model_name, source_model_kind, source_name)
    nodes: list[tuple[str, list]] = []
    child_nodes: dict[int, list] = {}
    for (model_name, kind, query_name, column, ref_kind, source_id), count in grouped.items():
        if source_id not in child_nodes and source_id not in seen and len(seen) < 100:
            seen.add(source_id)
            source_model_name, source_model_kind, source_name = sources[source_id]
            if source_model_kind == "EXTERNAL":
                child_nodes[source_id] = [
                    (
                        _relation_text(
                            source_model_name, source_model_kind, "", source_name, "", 1
                        ),
                        [],
                    )
                ]
            else:
                child_nodes[source_id] = _dependency_nodes(db, [source_id], seen)
        nodes.append(
            (
                _relation_text(model_name, kind, query_name, column, ref_kind, count),
                child_nodes.get(source_id, []),
            )
        )
    return nodes


def _render_dependency_nodes(nodes: list[tuple[str, list]], nested: bool) -> list[str]:
    lines: list[str] = []
    last = len(nodes) - 1
    for index, (text, children) in enumerate(nodes):
        connector, continuation = tree_glyphs(index == last, wide=True)
        if nested:
            lines.append(f"{connector}{text}")
            for line in _render_dependency_nodes(children, True):
                lines.append(f"{continuation}{line}" if line else "")
        else:
            if lines:
                lines.append("")
            lines.append(text)
            lines.extend(_render_dependency_nodes(children, True))
    return lines


def _format_dependency_tree(db: ProjectDB, column_ids: list[int]) -> str:
    nodes = _dependency_nodes(db, column_ids, set(column_ids))
    roots: list[tuple[str, list]] = []
    seen_children: set[int] = set()
    for _text, children in nodes:
        if id(children) not in seen_children:
            seen_children.add(id(children))
            roots.extend(children)
    lines = _render_dependency_nodes(roots, False)
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
        column_ids = [
            int(row["id"])
            for row in db.connection.execute(
                _FIND_COLUMNS_SQL,
                (model_key, relative, column_key),
            )
        ]
        if not column_ids:
            result = "No column found."
        elif relation == "dependencies":
            result = _format_dependency_tree(db, column_ids)
        else:
            placeholders = ", ".join("?" for _ in column_ids)
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
                    _DEPENDENTS_SQL.format(placeholders=placeholders),
                    column_ids,
                )
            ]
            test_rows: list[tuple[str, str]] = []
            if include_tests:
                test_rows = [
                    (str(row["file_path"]), str(row["test_name"]))
                    for row in db.connection.execute(
                        _TEST_DEPENDENTS_SQL.format(placeholders=placeholders),
                        column_ids,
                    )
                ]
            result = _format_groups(rows, test_rows, False)
    return result
