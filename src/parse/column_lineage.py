from typing import TypedDict, cast

from sqlglot import exp
from sqlglot.lineage import Node, lineage
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlmesh.core.model import Model


class ExtractedColumn(TypedDict):
    query_name: str
    from_table: str | None
    name: str
    qualified_name: str
    data_type: str
    line_start: int
    line_end: int
    context: str


class ExtractedColumnReference(TypedDict):
    ref_column_query_name: str
    ref_column_qualified_name: str
    source_query_name: str
    source_column_qualified_name: str
    source_line: int
    ref_line: int
    ref_kind: str
    ref_context: str


def _line_span(expression: exp.Expression) -> tuple[int, int]:
    line_start = 0
    line_end = 0
    for node in expression.walk():
        if "line" in node.meta:
            line = int(node.meta["line"])
            if line_start == 0 or line < line_start:
                line_start = line
            line_end = max(line_end, line)
    return line_start, line_end


def _source_line(expression: exp.Expression) -> int:
    source_line = 0
    for node in expression.walk():
        if "line" in node.meta:
            source_line = int(node.meta["line"])
            break
    return source_line


def _column_table_alias(expression: exp.Expression) -> str | None:
    column = expression.this if isinstance(expression, exp.Alias) else expression
    return column.table if isinstance(column, exp.Column) and column.table else None


def _table_source_name(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def _resolved_source(scope: Scope, table_alias: str | None) -> str | None:
    source_name = None
    if table_alias is not None:
        source = scope.sources[table_alias]
        source_name = _table_source_name(source) if isinstance(source, exp.Table) else table_alias
    return source_name


def _qualified_name(query_name: str, from_table: str | None, name: str) -> str:
    return f"{query_name}.{from_table}.{name}" if from_table is not None else f"{query_name}.{name}"


def _unwrap(expression: exp.Expression) -> exp.Expression:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _ref_kind(expression: exp.Expression) -> str:
    return "alias" if isinstance(_unwrap(expression), exp.Column) else "expression"


def _columns_from_types(model: Model) -> list[ExtractedColumn]:
    model_name = model.name
    dialect = model.dialect
    columns: list[ExtractedColumn] = []
    for name, dtype in (model.columns_to_types or {}).items():
        type_sql = dtype.sql(dialect=dialect)
        columns.append(
            {
                "query_name": model_name,
                "from_table": None,
                "name": name,
                "qualified_name": _qualified_name(model_name, None, name),
                "data_type": type_sql,
                "line_start": 0,
                "line_end": 0,
                "context": type_sql,
            }
        )
    return columns


def _columns_from_query(
    model_name: str, query: exp.Query, dialect: str, schema: dict | None
) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    qualified = qualify(query, dialect=dialect, schema=schema, validate_qualify_columns=False)
    annotate_types(qualified, schema=schema, dialect=dialect)
    for scope in traverse_scope(qualified):
        if not (scope.is_cte or scope.is_root):
            continue
        parent = scope.expression.parent
        query_name = (
            f"{model_name}.{parent.alias_or_name}"
            if scope.is_cte and parent is not None
            else model_name
        )
        for expression in scope.expression.expressions:
            name = expression.alias_or_name
            from_table = (
                _resolved_source(scope, _column_table_alias(expression)) if scope.is_cte else None
            )
            line_start, line_end = _line_span(expression)
            columns.append(
                {
                    "query_name": query_name,
                    "from_table": from_table,
                    "name": name,
                    "qualified_name": _qualified_name(query_name, from_table, name),
                    "data_type": cast(exp.DataType, expression.type).sql(dialect=dialect),
                    "line_start": line_start,
                    "line_end": line_end,
                    "context": expression.sql(dialect=dialect),
                }
            )
        columns.extend(_columns_from_clauses(query_name, scope, dialect, model_name=model_name))
    return columns


def extract_model_columns(model: Model) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn]
    query: exp.Query | None
    try:
        query = model.render_query()
    except Exception:  # noqa: BLE001
        query = None
    if query is None:
        columns = _columns_from_types(model)
    else:
        columns = _columns_from_query(model.name, query, model.dialect, model.mapping_schema)
    return columns


def _append_reference(
    refs: list[ExtractedColumnReference],
    *,
    ref_query_name: str,
    ref_qn: str,
    source_query_name: str,
    source_qn: str,
    ref_expression: exp.Expression,
    source_expression: exp.Expression,
    dialect: str,
    ref_kind: str,
) -> None:
    refs.append(
        {
            "ref_column_query_name": ref_query_name,
            "ref_column_qualified_name": ref_qn,
            "source_query_name": source_query_name,
            "source_column_qualified_name": source_qn,
            "source_line": _source_line(source_expression),
            "ref_line": _source_line(ref_expression),
            "ref_kind": ref_kind,
            "ref_context": ref_expression.sql(dialect=dialect),
        }
    )


def _cte_projection_qn(
    model_name: str, cte_name: str, scope: Scope, expression: exp.Expression
) -> str:
    name = expression.alias_or_name
    from_table = _resolved_source(scope, _column_table_alias(expression))
    return _qualified_name(f"{model_name}.{cte_name}", from_table, name)


def _table_column_qn(
    scope: Scope, column: exp.Column, *, model_name: str
) -> tuple[str, str] | None:
    resolved: tuple[str, str] | None = None
    source = scope.sources.get(column.table) if column.table else None
    if isinstance(source, exp.Table):
        query_name = _table_source_name(source)
        resolved = (query_name, f"{query_name}.{column.name}")
    if isinstance(source, Scope):
        cte_name = column.table
        query_name = f"{model_name}.{cte_name}"
        expression = next(
            e for e in source.expression.expressions if e.alias_or_name == column.name
        )
        resolved = (query_name, _cte_projection_qn(model_name, cte_name, source, expression))
    return resolved


def _clause_nodes(select: exp.Select) -> list[tuple[str, exp.Expression]]:
    nodes: list[tuple[str, exp.Expression]] = []
    for join in select.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            nodes.append(("join", on))
    for kind in ("where", "group", "having", "order"):
        node = select.args.get(kind)
        if node is not None:
            nodes.append((kind, node))
    return nodes


def _columns_from_clauses(
    query_base: str, scope: Scope, dialect: str, *, model_name: str
) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    for kind, node in _clause_nodes(cast(exp.Select, scope.expression)):
        query_name = f"{query_base}.{kind}"
        for column in node.find_all(exp.Column):
            source = _table_column_qn(scope, column, model_name=model_name)
            if source is not None:
                from_table, _source_qn = source
                line_start, line_end = _line_span(column)
                columns.append(
                    {
                        "query_name": query_name,
                        "from_table": from_table,
                        "name": column.name,
                        "qualified_name": _qualified_name(query_name, from_table, column.name),
                        "data_type": cast(exp.DataType, column.type).sql(dialect=dialect),
                        "line_start": line_start,
                        "line_end": line_end,
                        "context": column.sql(dialect=dialect),
                    }
                )
    return columns


def _emit_clause_refs(
    refs: list[ExtractedColumnReference],
    *,
    query_base: str,
    scope: Scope,
    dialect: str,
    model_name: str,
) -> None:
    for kind, node in _clause_nodes(cast(exp.Select, scope.expression)):
        ref_query_name = f"{query_base}.{kind}"
        for column in node.find_all(exp.Column):
            source = _table_column_qn(scope, column, model_name=model_name)
            if source is not None:
                source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=ref_query_name,
                    ref_qn=_qualified_name(ref_query_name, source_query_name, column.name),
                    source_query_name=source_query_name,
                    source_qn=source_qn,
                    ref_expression=node,
                    source_expression=column,
                    dialect=dialect,
                    ref_kind=kind,
                )


def _emit_cte_projection_refs(
    refs: list[ExtractedColumnReference],
    *,
    model_name: str,
    scope: Scope,
    cte_name: str,
    dialect: str,
) -> None:
    ref_query_name = f"{model_name}.{cte_name}"
    for expression in scope.expression.expressions:
        ref_qn = _cte_projection_qn(model_name, cte_name, scope, expression)
        inner = _unwrap(expression)
        if isinstance(inner, exp.Column):
            source = _table_column_qn(scope, inner, model_name=model_name)
            if source is not None:
                source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=ref_query_name,
                    ref_qn=ref_qn,
                    source_query_name=source_query_name,
                    source_qn=source_qn,
                    ref_expression=expression,
                    source_expression=expression,
                    dialect=dialect,
                    ref_kind="alias",
                )
            continue
        for column in inner.find_all(exp.Column):
            source = _table_column_qn(scope, column, model_name=model_name)
            if source is not None:
                source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=ref_query_name,
                    ref_qn=ref_qn,
                    source_query_name=source_query_name,
                    source_qn=source_qn,
                    ref_expression=expression,
                    source_expression=column,
                    dialect=dialect,
                    ref_kind="expression",
                )


def _lineage_node_qn(model_name: str, root_scope: Scope, node: Node) -> tuple[str, str] | None:
    expression = cast(exp.Expression, node.expression)
    resolved: tuple[str, str] | None = None
    if isinstance(expression, exp.Placeholder):
        resolved = None
    elif isinstance(expression, exp.Table):
        column_name = node.name.split(".")[-1].strip('"')
        query_name = _table_source_name(expression)
        resolved = (query_name, f"{query_name}.{column_name}")
    elif node.reference_node_name:
        cte_scope = root_scope.sources.get(node.reference_node_name)
        if isinstance(cte_scope, Scope):
            resolved = (
                f"{model_name}.{node.reference_node_name}",
                _cte_projection_qn(model_name, node.reference_node_name, cte_scope, expression),
            )
    elif isinstance(_unwrap(expression), exp.Column):
        resolved = (model_name, f"{model_name}.{expression.alias_or_name}")
    return resolved


def _emit_root_lineage_refs(
    refs: list[ExtractedColumnReference],
    *,
    model_name: str,
    query: exp.Query,
    dialect: str,
    schema: dict | None,
) -> None:
    root_scope = next(scope for scope in traverse_scope(query) if scope.is_root)
    for expression in root_scope.expression.expressions:
        name = expression.alias_or_name
        ref_qn = f"{model_name}.{name}"
        node = lineage(name, query, dialect=dialect, schema=schema, copy=False)
        kind = _ref_kind(cast(exp.Expression, node.expression))
        for child in node.downstream:
            source = _lineage_node_qn(model_name, root_scope, child)
            if source is not None:
                source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=model_name,
                    ref_qn=ref_qn,
                    source_query_name=source_query_name,
                    source_qn=source_qn,
                    ref_expression=cast(exp.Expression, node.expression),
                    source_expression=cast(exp.Expression, child.expression),
                    dialect=dialect,
                    ref_kind=kind,
                )


def extract_model_column_references(model: Model) -> list[ExtractedColumnReference]:
    refs: list[ExtractedColumnReference] = []
    query: exp.Query | None
    try:
        query = model.render_query()
    except Exception:  # noqa: BLE001
        query = None
    if query is not None:
        dialect = model.dialect
        model_name = model.name
        schema = model.mapping_schema
        qualified = qualify(query, dialect=dialect, schema=schema, validate_qualify_columns=False)
        for scope in traverse_scope(qualified):
            if not (scope.is_cte or scope.is_root):
                continue
            parent = scope.expression.parent
            query_base = (
                f"{model_name}.{parent.alias_or_name}"
                if scope.is_cte and parent is not None
                else model_name
            )
            if scope.is_cte and parent is not None:
                _emit_cte_projection_refs(
                    refs,
                    model_name=model_name,
                    scope=scope,
                    cte_name=parent.alias_or_name,
                    dialect=dialect,
                )
            _emit_clause_refs(
                refs,
                query_base=query_base,
                scope=scope,
                dialect=dialect,
                model_name=model_name,
            )
        _emit_root_lineage_refs(
            refs,
            model_name=model_name,
            query=qualified,
            dialect=dialect,
            schema=schema,
        )
    return refs
