from collections.abc import Mapping
from typing import TypedDict, cast

from pydantic import BaseModel, ConfigDict
from sqlglot import exp
from sqlglot.lineage import Node, lineage
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlmesh.core.model import Model

from src.parse.model_utils import model_qualified_name
from src.parse.query_spans import model_query_line_spans
from src.parse.sqlmesh_utils import column_label, normalized_model_name

FINAL_QUERY = "$"

ColumnNameIndex = dict[str, dict[str, list[str]]]


class PreparedModelQuery(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: Model
    model_name: str
    dialect: str
    default_catalog: str | None
    kind: str
    mapping_schema: dict | None
    rendered: exp.Query | None
    qualified: exp.Query | None
    sql_by_name: dict[str, str]


def _qualify_query(query: exp.Query, dialect: str, schema: dict | None) -> exp.Query:
    return qualify(
        query,
        dialect=dialect,
        schema=schema,
        validate_qualify_columns=False,
        allow_partial_qualification=True,
    )


def _ast_missing_types(query: exp.Query) -> bool:
    return any(column.type is None for column in query.find_all(exp.Column)) or any(
        expression.type is None
        for scope in traverse_scope(query)
        if scope.is_cte or scope.is_root
        for expression in _select_projections(cast(exp.Expression, scope.expression))
    )


def prepare_model_query(model: Model) -> PreparedModelQuery:
    rendered: exp.Query | None
    try:
        rendered = model.render_query()
    except Exception:  # noqa: BLE001
        rendered = None
    dialect = str(model.dialect)
    mapping_schema = model.mapping_schema
    sql_by_name: dict[str, str] = {}
    qualified: exp.Query | None = None
    if rendered is not None:
        external = model.kind.name == "EXTERNAL"
        sql_by_name = {} if external else _rendered_query_sql(rendered, dialect)
        qualified = _qualify_query(rendered, dialect, mapping_schema)
        if _ast_missing_types(qualified):
            annotate_types(qualified, schema=mapping_schema, dialect=model.dialect)
    return PreparedModelQuery(
        model=model,
        model_name=model_qualified_name(model),
        dialect=dialect,
        default_catalog=model.default_catalog,
        kind=model.kind.name,
        mapping_schema=mapping_schema,
        rendered=rendered,
        qualified=qualified,
        sql_by_name=sql_by_name,
    )


def build_column_name_index(qualified_names: Mapping[str, object]) -> ColumnNameIndex:
    index: ColumnNameIndex = {}
    for qualified_name in qualified_names:
        model, sep, rest = qualified_name.partition("/")
        query, sep2, column = rest.partition("/") if sep else ("", "", "")
        if sep and sep2:
            query_name = f"{model}/{query}"
            bare = column.rsplit(".", 1)[-1]
            index.setdefault(query_name, {}).setdefault(bare, []).append(qualified_name)
    return index


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
    line_start: int | None
    line_end: int | None
    line_count: int | None
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


class ModelExtractBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    prepared: PreparedModelQuery
    queries: list[ExtractedQuery]
    columns: list[ExtractedColumn]
    references: list[ExtractedColumnReference]


def extract_model_bundle(model: Model) -> ModelExtractBundle:
    prepared = prepare_model_query(model)
    scopes = list(traverse_scope(prepared.qualified)) if prepared.qualified is not None else []
    return ModelExtractBundle(
        model_name=prepared.model_name,
        prepared=prepared,
        queries=extract_model_queries(model, prepared, scopes=scopes),
        columns=extract_model_columns(model, prepared, scopes=scopes),
        references=extract_model_column_references(model, prepared, scopes=scopes),
    )


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


def _projection_from_table(
    scope: Scope,
    expression: exp.Expression,
    *,
    default_catalog: str | None,
    dialect: str,
) -> str | None:
    alias = _column_table_alias(expression)
    if alias is None:
        tables = {column.table for column in expression.find_all(exp.Column) if column.table}
        alias = tables.pop() if len(tables) == 1 else None
    return _resolved_source(scope, alias, default_catalog=default_catalog, dialect=dialect)


def _table_source_name(table: exp.Table, *, default_catalog: str | None, dialect: str) -> str:
    return normalized_model_name(table, default_catalog, dialect)


def _resolved_source(
    scope: Scope,
    table_alias: str | None,
    *,
    default_catalog: str | None,
    dialect: str,
) -> str | None:
    source = None if table_alias is None else scope.sources.get(table_alias)
    source_name = None
    if isinstance(source, exp.Table):
        source_name = _table_source_name(source, default_catalog=default_catalog, dialect=dialect)
    if table_alias is not None and isinstance(source, Scope) and source.is_cte:
        source_name = stored_query_name(table_alias)
    return source_name


def _qualified_name(query_name: str, from_table: str | None, name: str, dialect: str) -> str:
    model, _, query = query_name.rpartition("/")
    return f"{model}/{query}/{column_label(from_table, name, dialect)}"


def _stored_qualified_name(
    query_name: str,
    proposed: str,
    qualified_names: Mapping[str, object],
    name_index: ColumnNameIndex,
) -> str:
    stored = proposed
    if proposed not in qualified_names:
        column_name = proposed.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
        names = _columns_named(query_name, column_name, qualified_names, name_index)
        if len(names) == 1:
            stored = names[0]
    return stored


def _columns_named(
    query_name: str,
    column_name: str,
    qualified_names: Mapping[str, object],
    name_index: ColumnNameIndex,
) -> list[str]:
    exact = f"{query_name}/{column_name}"
    matched = [exact] if exact in qualified_names else []
    if not matched:
        matched = list(name_index.get(query_name, {}).get(column_name, []))
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
    model_name = model_qualified_name(model)
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
                "qualified_name": _qualified_name(query_name, None, name, dialect),
                "data_type": type_sql,
                "line_start": 0,
                "line_end": 0,
                "context": type_sql,
                "is_select": True,
            }
        )
    return columns


def _columns_from_query(
    model_name: str,
    qualified: exp.Query,
    dialect: str,
    *,
    default_catalog: str | None,
    scopes: list[Scope] | None = None,
) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    for scope in scopes if scopes is not None else traverse_scope(qualified):
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
            from_table = _projection_from_table(
                scope, expression, default_catalog=default_catalog, dialect=dialect
            )
            line_start, line_end = _line_span(expression)
            columns.append(
                {
                    "query_name": query_name,
                    "from_table": from_table,
                    "name": name,
                    "qualified_name": _qualified_name(query_name, from_table, name, dialect),
                    "data_type": cast(exp.DataType, expression.type).sql(dialect=dialect),
                    "line_start": line_start,
                    "line_end": line_end,
                    "context": expression.sql(dialect=dialect),
                    "is_select": True,
                }
            )
        seen = {column["qualified_name"] for column in columns}
        for clause_column in _columns_from_clauses(
            query_name,
            scope,
            dialect,
            model_name=model_name,
            default_catalog=default_catalog,
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


def _query_models_read_count(scope: Scope, *, default_catalog: str | None, dialect: str) -> int:
    tables: set[str] = set()
    for source in scope.sources.values():
        if isinstance(source, exp.Table):
            tables.add(_table_source_name(source, default_catalog=default_catalog, dialect=dialect))
    return len(tables)


def _set_operation_models_read_count(
    expression: exp.Expression,
    scope_by_expression: dict[int, Scope],
    *,
    default_catalog: str | None,
    dialect: str,
) -> int:
    tables: set[str] = set()
    for leaf in _set_operation_leaf_selects(expression):
        leaf_scope = scope_by_expression.get(id(leaf))
        if leaf_scope is not None:
            for source in leaf_scope.sources.values():
                if isinstance(source, exp.Table):
                    tables.add(
                        _table_source_name(source, default_catalog=default_catalog, dialect=dialect)
                    )
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
            rendered = scope.expression
            if scope.is_root:
                rendered = scope.expression.copy()
                rendered.set("with_", None)
            sql_by_name[name] = rendered.sql(dialect=dialect, pretty=False)
    return sql_by_name


def extract_model_queries(
    model: Model,
    prepared: PreparedModelQuery | None = None,
    *,
    scopes: list[Scope] | None = None,
) -> list[ExtractedQuery]:
    prepared_query = prepared if prepared is not None else prepare_model_query(model)
    queries: list[ExtractedQuery] = []
    if prepared_query.qualified is not None:
        external = prepared_query.kind == "EXTERNAL"
        seen: set[str] = set()
        source_spans = model_query_line_spans(prepared_query.model, prepared_query.dialect)
        scopes = scopes if scopes is not None else list(traverse_scope(prepared_query.qualified))
        scope_by_expression = {id(scope.expression): scope for scope in scopes}
        for scope in scopes:
            parent = scope.expression.parent
            included = scope.is_cte or scope.is_root
            name = FINAL_QUERY
            if included and scope.is_cte and parent is not None:
                name = parent.alias_or_name
            name = stored_query_name(name)
            query_name = model_query_name(prepared_query.model_name, name)
            if included and query_name not in seen:
                seen.add(query_name)
                line_start, line_end = source_spans.get(name, (None, None))
                if name not in source_spans:
                    start, end = _query_line_span(scope.expression)
                    line_start, line_end = (start, end) if start else (None, None)
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
                models_read_count = _query_models_read_count(
                    scope,
                    default_catalog=prepared_query.default_catalog,
                    dialect=prepared_query.dialect,
                )
                if isinstance(scope.expression, _SET_OPERATIONS):
                    models_read_count = _set_operation_models_read_count(
                        scope.expression,
                        scope_by_expression,
                        default_catalog=prepared_query.default_catalog,
                        dialect=prepared_query.dialect,
                    )
                line_count = (
                    None if line_start is None or line_end is None else line_end - line_start + 1
                )
                queries.append(
                    {
                        "name": name,
                        "query_name": query_name,
                        "line_start": line_start,
                        "line_end": line_end,
                        "line_count": line_count,
                        "depth": _query_depth(scope),
                        "select_col_count": select_col_count,
                        "select_expr_count": select_expr_count,
                        "select_alias_count": select_alias_count,
                        "where_condition_count": where_condition_count,
                        "join_statement_count": join_statement_count,
                        "group_by_col_count": group_by_col_count,
                        "having_condition_count": having_condition_count,
                        "order_by_col_count": order_by_col_count,
                        "rendered_sql": None if external else prepared_query.sql_by_name[name],
                        "models_read_count": models_read_count,
                    }
                )
    return queries


def extract_model_columns(
    model: Model,
    prepared: PreparedModelQuery | None = None,
    *,
    scopes: list[Scope] | None = None,
) -> list[ExtractedColumn]:
    prepared_query = prepared if prepared is not None else prepare_model_query(model)
    return (
        _columns_from_types(prepared_query.model)
        if prepared_query.qualified is None
        else _columns_from_query(
            prepared_query.model_name,
            prepared_query.qualified,
            prepared_query.dialect,
            default_catalog=prepared_query.default_catalog,
            scopes=scopes,
        )
    )


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
    model_name: str,
    cte_name: str,
    scope: Scope,
    expression: exp.Expression,
    *,
    default_catalog: str | None,
    dialect: str,
) -> str:
    name = expression.alias_or_name
    from_table = _projection_from_table(
        scope, expression, default_catalog=default_catalog, dialect=dialect
    )
    return _qualified_name(model_query_name(model_name, cte_name), from_table, name, dialect)


def _select_projections(expression: exp.Expression) -> list[exp.Expression]:
    current = expression
    while isinstance(current, exp.Union):
        current = current.this
    projections: list[exp.Expression] = []
    if isinstance(current, exp.Select):
        projections = list(current.expressions)
    return projections


def _table_column_qn(
    scope: Scope,
    column: exp.Column,
    *,
    model_name: str,
    default_catalog: str | None,
    dialect: str,
) -> tuple[str, str, str] | None:
    resolved: tuple[str, str, str] | None = None
    source = scope.sources.get(column.table) if column.table else None
    if isinstance(source, exp.Table):
        from_table = _table_source_name(source, default_catalog=default_catalog, dialect=dialect)
        source_query_name = final_query_name(from_table)
        resolved = (
            from_table,
            source_query_name,
            _qualified_name(source_query_name, None, column.name, dialect),
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
                _cte_projection_qn(
                    model_name,
                    cte_name,
                    source,
                    expression,
                    default_catalog=default_catalog,
                    dialect=dialect,
                ),
            )
    return resolved


_SET_OPERATIONS = (exp.Union, exp.Intersect, exp.Except)


def _set_operation_leaf_selects(expression: exp.Expression) -> list[exp.Select]:
    leaves: list[exp.Select] = []
    if isinstance(expression, exp.Select):
        leaves = [expression]
    elif isinstance(expression, _SET_OPERATIONS):
        leaves = _set_operation_leaf_selects(expression.this) + _set_operation_leaf_selects(
            expression.expression
        )
    return leaves


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
    elif isinstance(expression, _SET_OPERATIONS):
        leaves = _set_operation_leaf_selects(expression)
        if leaves:
            (
                select_col_count,
                select_expr_count,
                select_alias_count,
                _where,
                _join,
                _group,
                _having,
                _order,
            ) = _query_counts(leaves[0])
            for leaf in leaves:
                (
                    _select,
                    _expr,
                    _alias,
                    where_count,
                    join_count,
                    group_count,
                    having_count,
                    order_count,
                ) = _query_counts(leaf)
                where_condition_count += where_count
                join_statement_count += join_count
                group_by_col_count += group_count
                having_condition_count += having_count
                order_by_col_count += order_count
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
    query_base: str,
    scope: Scope,
    dialect: str,
    *,
    model_name: str,
    default_catalog: str | None,
) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    for _kind, node in _clause_nodes(cast(exp.Select, scope.expression)):
        for column in node.find_all(exp.Column):
            source = _table_column_qn(
                scope,
                column,
                model_name=model_name,
                default_catalog=default_catalog,
                dialect=dialect,
            )
            if source is not None:
                from_table, _source_query_name, _source_qn = source
                line_start, line_end = _line_span(column)
                columns.append(
                    {
                        "query_name": query_base,
                        "from_table": from_table,
                        "name": column.name,
                        "qualified_name": _qualified_name(
                            query_base, from_table, column.name, dialect
                        ),
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
    default_catalog: str | None,
) -> None:
    for kind, node in _clause_nodes(cast(exp.Select, scope.expression)):
        for column in node.find_all(exp.Column):
            source = _table_column_qn(
                scope,
                column,
                model_name=model_name,
                default_catalog=default_catalog,
                dialect=dialect,
            )
            if source is not None:
                from_table, source_query_name, source_qn = source
                _append_reference(
                    refs,
                    ref_query_name=query_base,
                    ref_qn=_qualified_name(query_base, from_table, column.name, dialect),
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
    default_catalog: str | None,
) -> None:
    ref_query_name = model_query_name(model_name, cte_name)
    for expression in _select_projections(cast(exp.Expression, scope.expression)):
        ref_qn = _cte_projection_qn(
            model_name,
            cte_name,
            scope,
            expression,
            default_catalog=default_catalog,
            dialect=dialect,
        )
        inner = _unwrap(expression)
        if isinstance(inner, exp.Column):
            source = _table_column_qn(
                scope,
                inner,
                model_name=model_name,
                default_catalog=default_catalog,
                dialect=dialect,
            )
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
            source = _table_column_qn(
                scope,
                column,
                model_name=model_name,
                default_catalog=default_catalog,
                dialect=dialect,
            )
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


def _lineage_node_qn(
    model_name: str,
    root_scope: Scope,
    node: Node,
    *,
    default_catalog: str | None,
    dialect: str,
) -> tuple[str, str] | None:
    expression = cast(exp.Expression, node.expression)
    resolved: tuple[str, str] | None = None
    if isinstance(expression, exp.Placeholder):
        resolved = None
    elif isinstance(expression, exp.Table):
        column_name = node.name.split(".")[-1].strip('"')
        query_name = final_query_name(
            _table_source_name(expression, default_catalog=default_catalog, dialect=dialect)
        )
        resolved = (query_name, _qualified_name(query_name, None, column_name, dialect))
    elif node.reference_node_name:
        cte_scope = root_scope.sources.get(node.reference_node_name)
        if isinstance(cte_scope, Scope):
            resolved = (
                model_query_name(model_name, node.reference_node_name),
                _cte_projection_qn(
                    model_name,
                    node.reference_node_name,
                    cte_scope,
                    expression,
                    default_catalog=default_catalog,
                    dialect=dialect,
                ),
            )
    elif isinstance(_unwrap(expression), exp.Column):
        query_name = final_query_name(model_name)
        resolved = (
            query_name,
            _qualified_name(query_name, None, expression.alias_or_name, dialect),
        )
    return resolved


def _emit_root_lineage_refs(
    refs: list[ExtractedColumnReference],
    *,
    model_name: str,
    query: exp.Query,
    dialect: str,
    default_catalog: str | None,
    schema: dict | None,
    scopes: list[Scope] | None = None,
) -> None:
    walked = scopes if scopes is not None else list(traverse_scope(query))
    root_scope = next(scope for scope in walked if scope.is_root)
    query_name = final_query_name(model_name)
    nodes = lineage(
        None,
        query,
        dialect=dialect,
        schema=schema,
        scope=root_scope,
        copy=False,
        allow_partial_qualification=True,
    )
    for expression in _select_projections(cast(exp.Expression, root_scope.expression)):
        name = expression.alias_or_name
        node = nodes[name]
        ref_qn = _qualified_name(
            query_name,
            _projection_from_table(
                root_scope, expression, default_catalog=default_catalog, dialect=dialect
            ),
            name,
            dialect,
        )
        kind = _ref_kind(cast(exp.Expression, node.expression))
        for child in node.downstream:
            source = _lineage_node_qn(
                model_name,
                root_scope,
                child,
                default_catalog=default_catalog,
                dialect=dialect,
            )
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


def extract_model_column_references(
    model: Model,
    prepared: PreparedModelQuery | None = None,
    *,
    scopes: list[Scope] | None = None,
) -> list[ExtractedColumnReference]:
    prepared_query = prepared if prepared is not None else prepare_model_query(model)
    refs: list[ExtractedColumnReference] = []
    if prepared_query.qualified is not None:
        model_name = prepared_query.model_name
        dialect = prepared_query.dialect
        default_catalog = prepared_query.default_catalog
        walked = scopes if scopes is not None else list(traverse_scope(prepared_query.qualified))
        for scope in walked:
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
                    default_catalog=default_catalog,
                )
            _emit_clause_refs(
                refs,
                query_base=query_base,
                scope=scope,
                dialect=dialect,
                model_name=model_name,
                default_catalog=default_catalog,
            )
        _emit_root_lineage_refs(
            refs,
            model_name=model_name,
            query=prepared_query.qualified,
            dialect=dialect,
            default_catalog=default_catalog,
            schema=prepared_query.mapping_schema,
            scopes=walked,
        )
    return refs
