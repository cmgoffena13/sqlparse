from collections.abc import Mapping
from typing import TypedDict, cast

from sqlglot import exp
from sqlglot.lineage import Node, lineage
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlmesh.core.model import Model

FINAL_QUERY = "$"


def _qualify_query(query: exp.Query, dialect: str, schema: dict | None) -> exp.Query:
    return qualify(
        query,
        dialect=dialect,
        schema=schema,
        validate_qualify_columns=False,
        allow_partial_qualification=True,
    )


def stored_query_name(name: str) -> str:
    stored = name
    if not name.startswith(FINAL_QUERY):
        stored = f"{FINAL_QUERY}{name}"
    return stored


def model_query_name(model_name: str, name: str) -> str:
    return f"{model_name}/{stored_query_name(name)}"


def final_query_name(model_name: str) -> str:
    return model_query_name(model_name, FINAL_QUERY)


class ExtractedColumn(TypedDict):
    query_name: str
    from_table: str | None
    name: str
    qualified_name: str
    data_type: str
    line_start: int
    line_end: int
    context: str
    is_select: bool


class ExtractedColumnReference(TypedDict):
    ref_column_query_name: str
    ref_column_qualified_name: str
    source_query_name: str
    source_column_qualified_name: str
    source_line: int
    ref_line: int
    ref_kind: str
    ref_context: str


class ExtractedQuery(TypedDict):
    name: str
    query_name: str
    line_start: int
    line_end: int
    depth: int
    select_col_count: int
    select_expr_count: int
    select_alias_count: int
    where_condition_count: int
    join_statement_count: int
    group_by_col_count: int
    having_condition_count: int
    order_by_col_count: int
    rendered_sql: str | None
    models_read_count: int


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


def _projection_from_table(scope: Scope, expression: exp.Expression) -> str | None:
    alias = _column_table_alias(expression)
    if alias is None:
        tables = {column.table for column in expression.find_all(exp.Column) if column.table}
        alias = tables.pop() if len(tables) == 1 else None
    return _resolved_source(scope, alias)


def _table_source_name(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def _resolved_source(scope: Scope, table_alias: str | None) -> str | None:
    source = None if table_alias is None else scope.sources.get(table_alias)
    source_name = None
    if isinstance(source, exp.Table):
        source_name = _table_source_name(source)
    if table_alias is not None and isinstance(source, Scope) and source.is_cte:
        source_name = stored_query_name(table_alias)
    return source_name


def _qualified_name(query_name: str, from_table: str | None, name: str) -> str:
    column = f"{from_table}.{name}" if from_table is not None else name
    model, _, query = query_name.rpartition("/")
    return f"{model}/{query}/{column}"


def _stored_qualified_name(
    query_name: str, proposed: str, qualified_names: Mapping[str, object]
) -> str:
    stored = proposed
    if proposed not in qualified_names:
        column_name = proposed.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        names = _columns_named(query_name, column_name, qualified_names)
        if len(names) == 1:
            stored = names[0]
    return stored


def _columns_named(
    query_name: str, column_name: str, qualified_names: Mapping[str, object]
) -> list[str]:
    model, _, query = query_name.rpartition("/")
    prefix = f"{model}/{query}/"
    exact = f"{prefix}{column_name}"
    matched = [exact] if exact in qualified_names else []
    if not matched:
        for qualified_name in qualified_names:
            bare = qualified_name[len(prefix) :].rsplit(".", 1)[-1]
            if qualified_name.startswith(prefix) and bare == column_name:
                matched.append(qualified_name)
    return matched


def _unwrap(expression: exp.Expression) -> exp.Expression:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _ref_kind(expression: exp.Expr) -> str:
    inner = _unwrap(cast(exp.Expression, expression))
    renamed = isinstance(expression, exp.Alias) and expression.alias != inner.name
    kind = "expression"
    if isinstance(inner, exp.Column):
        kind = "alias" if renamed else "select"
    return kind


def _columns_from_types(model: Model) -> list[ExtractedColumn]:
    model_name = model.name
    query_name = final_query_name(model_name)
    dialect = model.dialect
    columns: list[ExtractedColumn] = []
    for name, dtype in (model.columns_to_types or {}).items():
        type_sql = dtype.sql(dialect=dialect)
        columns.append(
            {
                "query_name": query_name,
                "from_table": None,
                "name": name,
                "qualified_name": _qualified_name(query_name, None, name),
                "data_type": type_sql,
                "line_start": 0,
                "line_end": 0,
                "context": type_sql,
                "is_select": True,
            }
        )
    return columns


def _columns_from_query(
    model_name: str, query: exp.Query, dialect: str, schema: dict | None
) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    qualified = _qualify_query(query, dialect, schema)
    annotate_types(qualified, schema=schema, dialect=dialect)
    for scope in traverse_scope(qualified):
        if not (scope.is_cte or scope.is_root):
            continue
        parent = scope.expression.parent
        query_name = (
            model_query_name(model_name, parent.alias_or_name)
            if scope.is_cte and parent is not None
            else final_query_name(model_name)
        )
        for expression in _select_projections(cast(exp.Expression, scope.expression)):
            name = expression.alias_or_name
            from_table = _projection_from_table(scope, expression)
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
                    "is_select": True,
                }
            )
        seen = {column["qualified_name"] for column in columns}
        for clause_column in _columns_from_clauses(
            query_name, scope, dialect, model_name=model_name
        ):
            if clause_column["qualified_name"] not in seen:
                columns.append(clause_column)
                seen.add(clause_column["qualified_name"])
    return columns


def _query_line_span(expression: exp.Expr) -> tuple[int, int]:
    line_start = 0
    line_end = 0
    pending = [expression]
    while pending:
        node = pending.pop()
        if "line" in node.meta:
            line = int(node.meta["line"])
            if line_start == 0 or line < line_start:
                line_start = line
            line_end = max(line_end, line)
        pending.extend(
            child for child in node.iter_expressions() if not isinstance(child, exp.With)
        )
    return line_start, line_end


def _query_depth(scope: Scope) -> int:
    depth = 0
    parent = scope.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


def _query_models_read_count(scope: Scope) -> int:
    tables: set[str] = set()
    for source in scope.sources.values():
        if isinstance(source, exp.Table):
            tables.add(_table_source_name(source))
    return len(tables)


def _rendered_query_sql(expression: exp.Query, dialect: str) -> dict[str, str]:
    sql_by_name: dict[str, str] = {}
    for scope in traverse_scope(expression):
        parent = scope.expression.parent
        included = scope.is_cte or scope.is_root
        name = FINAL_QUERY
        if included and scope.is_cte and parent is not None:
            name = parent.alias_or_name
        name = stored_query_name(name)
        if included and name not in sql_by_name:
            rendered = scope.expression.copy()
            if scope.is_root:
                rendered.set("with_", None)
            sql_by_name[name] = rendered.sql(dialect=dialect, pretty=True)
    return sql_by_name


def extract_model_queries(model: Model) -> list[ExtractedQuery]:
    queries: list[ExtractedQuery] = []
    try:
        rendered = model.render_query()
    except Exception:  # noqa: BLE001
        rendered = None
    if rendered is None:
        queries.append(
            {
                "name": FINAL_QUERY,
                "query_name": final_query_name(model.name),
                "line_start": 0,
                "line_end": 0,
                "depth": 0,
                "select_col_count": len(model.columns_to_types or {}),
                "select_expr_count": 0,
                "select_alias_count": 0,
                "where_condition_count": 0,
                "join_statement_count": 0,
                "group_by_col_count": 0,
                "having_condition_count": 0,
                "order_by_col_count": 0,
                "rendered_sql": None if model.kind.name == "EXTERNAL" else "",
                "models_read_count": 0,
            }
        )
    else:
        external = model.kind.name == "EXTERNAL"
        sql_by_name = {} if external else _rendered_query_sql(rendered.copy(), str(model.dialect))
        qualified = _qualify_query(rendered, str(model.dialect), model.mapping_schema)
        annotate_types(qualified, schema=model.mapping_schema, dialect=model.dialect)
        seen: set[str] = set()
        for scope in traverse_scope(qualified):
            parent = scope.expression.parent
            included = scope.is_cte or scope.is_root
            name = FINAL_QUERY
            if included and scope.is_cte and parent is not None:
                name = parent.alias_or_name
            name = stored_query_name(name)
            query_name = model_query_name(model.name, name)
            if included and query_name not in seen:
                seen.add(query_name)
                line_start, line_end = _query_line_span(scope.expression)
                (
                    select_col_count,
                    select_expr_count,
                    select_alias_count,
                    where_condition_count,
                    join_statement_count,
                    group_by_col_count,
                    having_condition_count,
                    order_by_col_count,
                ) = _query_counts(scope.expression)
                queries.append(
                    {
                        "name": name,
                        "query_name": query_name,
                        "line_start": line_start,
                        "line_end": line_end,
                        "depth": _query_depth(scope),
                        "select_col_count": select_col_count,
                        "select_expr_count": select_expr_count,
                        "select_alias_count": select_alias_count,
                        "where_condition_count": where_condition_count,
                        "join_statement_count": join_statement_count,
                        "group_by_col_count": group_by_col_count,
                        "having_condition_count": having_condition_count,
                        "order_by_col_count": order_by_col_count,
                        "rendered_sql": None if external else sql_by_name[name],
                        "models_read_count": _query_models_read_count(scope),
                    }
                )
    return queries


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
    from_table = _projection_from_table(scope, expression)
    return _qualified_name(model_query_name(model_name, cte_name), from_table, name)


def _select_projections(expression: exp.Expression) -> list[exp.Expression]:
    current = expression
    while isinstance(current, exp.Union):
        current = current.this
    projections: list[exp.Expression] = []
    if isinstance(current, exp.Select):
        projections = list(current.expressions)
    return projections


def _table_column_qn(
    scope: Scope, column: exp.Column, *, model_name: str
) -> tuple[str, str, str] | None:
    resolved: tuple[str, str, str] | None = None
    source = scope.sources.get(column.table) if column.table else None
    if isinstance(source, exp.Table):
        from_table = _table_source_name(source)
        source_query_name = final_query_name(from_table)
        resolved = (
            from_table,
            source_query_name,
            _qualified_name(source_query_name, None, column.name),
        )
    if isinstance(source, Scope) and source.is_cte:
        cte_name = column.table
        query_name = model_query_name(model_name, cte_name)
        expression = next(
            (
                e
                for e in _select_projections(cast(exp.Expression, source.expression))
                if e.alias_or_name == column.name
            ),
            None,
        )
        if expression is not None:
            resolved = (
                stored_query_name(cte_name),
                query_name,
                _cte_projection_qn(model_name, cte_name, source, expression),
            )
    return resolved


def _query_counts(expression: exp.Expr) -> tuple[int, int, int, int, int, int, int, int]:
    select_col_count = 0
    select_expr_count = 0
    select_alias_count = 0
    where_condition_count = 0
    join_statement_count = 0
    group_by_col_count = 0
    having_condition_count = 0
    order_by_col_count = 0
    if isinstance(expression, exp.Select):
        select_col_count = len(expression.expressions)
        for projection in expression.expressions:
            kind = _ref_kind(cast(exp.Expression, projection))
            if kind == "expression":
                select_expr_count += 1
            if kind == "alias":
                select_alias_count += 1
        join_statement_count = len(expression.args.get("joins") or [])
        where = expression.args.get("where")
        if where is not None:
            where_condition_count = len(_and_predicates(where.this))
        group = expression.args.get("group")
        if group is not None:
            group_by_col_count = len(group.expressions)
        having = expression.args.get("having")
        if having is not None:
            having_condition_count = len(_and_predicates(having.this))
        order = expression.args.get("order")
        if order is not None:
            order_by_col_count = len(order.expressions)
    return (
        select_col_count,
        select_expr_count,
        select_alias_count,
        where_condition_count,
        join_statement_count,
        group_by_col_count,
        having_condition_count,
        order_by_col_count,
    )


def _and_predicates(expression: exp.Expression) -> list[exp.Expression]:
    predicates = [expression]
    if isinstance(expression, exp.And):
        predicates = _and_predicates(expression.this) + _and_predicates(expression.expression)
    return predicates


def _clause_nodes(select: exp.Select) -> list[tuple[str, exp.Expression]]:
    nodes: list[tuple[str, exp.Expression]] = []
    for join in select.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            nodes.append(("join", on))
    where = select.args.get("where")
    if where is not None:
        for predicate in _and_predicates(where.this):
            nodes.append(("where", predicate))
    for kind in ("group", "having", "order"):
        node = select.args.get(kind)
        if node is not None:
            nodes.append((kind, node))
    return nodes


def _columns_from_clauses(
    query_base: str, scope: Scope, dialect: str, *, model_name: str
) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    for _kind, node in _clause_nodes(cast(exp.Select, scope.expression)):
        for column in node.find_all(exp.Column):
            source = _table_column_qn(scope, column, model_name=model_name)
            if source is not None:
                from_table, _source_query_name, _source_qn = source
                line_start, line_end = _line_span(column)
                columns.append(
                    {
                        "query_name": query_base,
                        "from_table": from_table,
                        "name": column.name,
                        "qualified_name": _qualified_name(query_base, from_table, column.name),
                        "data_type": cast(exp.DataType, column.type).sql(dialect=dialect),
                        "line_start": line_start,
                        "line_end": line_end,
                        "context": column.sql(dialect=dialect),
                        "is_select": False,
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
        for column in node.find_all(exp.Column):
            source = _table_column_qn(scope, column, model_name=model_name)
            if source is not None:
                from_table, source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=query_base,
                    ref_qn=_qualified_name(query_base, from_table, column.name),
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
    ref_query_name = model_query_name(model_name, cte_name)
    for expression in _select_projections(cast(exp.Expression, scope.expression)):
        ref_qn = _cte_projection_qn(model_name, cte_name, scope, expression)
        inner = _unwrap(expression)
        if isinstance(inner, exp.Column):
            source = _table_column_qn(scope, inner, model_name=model_name)
            if source is not None:
                _from_table, source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=ref_query_name,
                    ref_qn=ref_qn,
                    source_query_name=source_query_name,
                    source_qn=source_qn,
                    ref_expression=expression,
                    source_expression=expression,
                    dialect=dialect,
                    ref_kind=_ref_kind(expression),
                )
            continue
        for column in inner.find_all(exp.Column):
            source = _table_column_qn(scope, column, model_name=model_name)
            if source is not None:
                _from_table, source_query_name, source_qn = source
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
        query_name = final_query_name(_table_source_name(expression))
        resolved = (query_name, _qualified_name(query_name, None, column_name))
    elif node.reference_node_name:
        cte_scope = root_scope.sources.get(node.reference_node_name)
        if isinstance(cte_scope, Scope):
            resolved = (
                model_query_name(model_name, node.reference_node_name),
                _cte_projection_qn(model_name, node.reference_node_name, cte_scope, expression),
            )
    elif isinstance(_unwrap(expression), exp.Column):
        query_name = final_query_name(model_name)
        resolved = (
            query_name,
            _qualified_name(query_name, None, expression.alias_or_name),
        )
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
    query_name = final_query_name(model_name)
    for expression in root_scope.expression.expressions:
        name = expression.alias_or_name
        ref_qn = _qualified_name(query_name, _projection_from_table(root_scope, expression), name)
        node = lineage(
            name,
            query,
            dialect=dialect,
            schema=schema,
            copy=False,
            allow_partial_qualification=True,
        )
        kind = _ref_kind(cast(exp.Expression, node.expression))
        for child in node.downstream:
            source = _lineage_node_qn(model_name, root_scope, child)
            if source is not None:
                source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=query_name,
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
        qualified = _qualify_query(query, str(dialect), schema)
        for scope in traverse_scope(qualified):
            if not (scope.is_cte or scope.is_root):
                continue
            parent = scope.expression.parent
            query_base = (
                model_query_name(model_name, parent.alias_or_name)
                if scope.is_cte and parent is not None
                else final_query_name(model_name)
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
