from typing import TypedDict

from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlmesh.core.model import Model


class ExtractedColumn(TypedDict):
    query_name: str
    from_table: str | None
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    context: str


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


def _columns_from_types(model: Model) -> list[ExtractedColumn]:
    model_name = model.name
    dialect = model.dialect
    columns: list[ExtractedColumn] = []
    for name, dtype in (model.columns_to_types or {}).items():
        columns.append(
            {
                "query_name": model_name,
                "from_table": None,
                "name": name,
                "qualified_name": _qualified_name(model_name, None, name),
                "line_start": 0,
                "line_end": 0,
                "context": dtype.sql(dialect=dialect),
            }
        )
    return columns


def _columns_from_query(model_name: str, query: exp.Query, dialect: str) -> list[ExtractedColumn]:
    columns: list[ExtractedColumn] = []
    qualified = qualify(query, dialect=dialect, validate_qualify_columns=False)
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
                    "line_start": line_start,
                    "line_end": line_end,
                    "context": expression.sql(dialect=dialect),
                }
            )
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
        columns = _columns_from_query(model.name, query, model.dialect)
    return columns
