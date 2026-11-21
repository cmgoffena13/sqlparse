import re

from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import traverse_scope
from sqlmesh.core.dialect import parse as parse_sql

from src.db import ProjectDB
from src.parse.column_lineage import _query_line_span
from src.sqlparse_mcp.column_relations import _resolve_query_name
from src.sqlparse_mcp.format_utils import bullet
from src.sqlparse_mcp.sql_tree import _normalize_file_path

_MODEL_SQL = """
SELECT
    models.qualified_name,
    models.dialect,
    files.path AS file_path
FROM models
INNER JOIN files ON files.id = models.file_id
WHERE models.qualified_name = ?
"""

_MODEL_BY_FILE_SQL = """
SELECT
    models.qualified_name,
    models.dialect,
    files.path AS file_path
FROM models
INNER JOIN files ON files.id = models.file_id
WHERE files.path = ?
ORDER BY models.qualified_name
"""

_QUERY_SQL = """
SELECT queries.name
FROM queries
INNER JOIN models ON models.id = queries.model_id
WHERE models.qualified_name = ?
  AND queries.name = ?
"""

_COLUMNS_SQL = """
SELECT
    columns.name,
    columns.data_type,
    columns.nullable
FROM columns
INNER JOIN queries ON queries.id = columns.query_id
INNER JOIN models ON models.id = columns.model_id
WHERE models.qualified_name = ?
  AND queries.name = ?
ORDER BY columns.line_start, columns.line_end, columns.name
"""


def _relative_query(model_name: str, query_name: str | None) -> str:
    resolved = _resolve_query_name(model_name, query_name)
    prefix = f"{model_name}/"
    relative = resolved
    if resolved.startswith(prefix):
        relative = resolved[len(prefix) :]
    return relative


def _neutralize_jinja(text: str) -> str:
    def replace_expression(match: re.Match[str]) -> str:
        token = match.group(0)
        return "NULL" + (" " * (len(token) - 4))

    neutralized = re.sub(r"\{\{.*?\}\}", replace_expression, text, flags=re.DOTALL)
    neutralized = re.sub(
        r"\{%.*?%\}",
        lambda match: " " * len(match.group(0)),
        neutralized,
        flags=re.DOTALL,
    )
    for token in ("JINJA_QUERY_BEGIN;", "JINJA_END;"):
        neutralized = neutralized.replace(token, " " * len(token))
    return neutralized


def _expand_query_span(lines: list[str], start: int, end: int) -> tuple[int, int]:
    while start > 1:
        previous = lines[start - 2].strip().upper()
        header = previous.startswith(("SELECT", "WITH ")) or previous.endswith(" AS (")
        if not header:
            break
        start -= 1
    if end < len(lines) and lines[end].strip() in {")", "),"}:
        end += 1
    return start, end


def _source_span(
    text: str, dialect: str, query_name: str, model_name: str
) -> tuple[int, int, str] | None:
    span = None
    try:
        expressions = parse_sql(_neutralize_jinja(text), default_dialect=dialect)
    except ParseError:
        expressions = []
    lines = text.splitlines()
    for expression in expressions:
        if isinstance(expression, exp.Query):
            for scope in traverse_scope(expression):
                parent = scope.expression.parent
                name = "$"
                if scope.is_cte and parent is not None:
                    name = parent.alias_or_name
                included = scope.is_cte or scope.is_root
                if included and name.casefold() == query_name.casefold():
                    start, end = _query_line_span(scope.expression)
                    if start:
                        expanded = _expand_query_span(lines, start, end)
                        shown = model_name if name == "$" else name
                        span = (expanded[0], expanded[1], shown)
    return span


def _output_label(qualifier: str, name: str, data_type: str, nullable: int | None) -> str:
    constraint = " NOT NULL" if nullable == 0 else ""
    return f"{qualifier}.{name} {data_type}{constraint}"


def _format_query(
    header: str,
    lines: list[str],
    start: int,
    end: int,
    qualifier: str,
    columns: list[tuple[str, str, int | None]],
) -> str:
    chunk = lines[start - 1 : end]
    gutter = len(str(end))
    body = [f"L{lineno:<{gutter}} | {line}" for lineno, line in enumerate(chunk, start)]
    rendered = [header, "", *body]
    if columns:
        rendered.extend(["", "## Output", ""])
        rendered.extend(
            bullet(_output_label(qualifier, name, data_type, nullable))
            for name, data_type, nullable in columns
        )
    return "\n".join(rendered) + "\n"


def get_query(db: ProjectDB, target: str, query_name: str | None) -> str:
    key = target.strip()
    result = "No target given; pass a model name or file path."
    if key:
        rows = list(db.connection.execute(_MODEL_SQL, (key,)))
        from_file = not rows
        if from_file:
            file_path = _normalize_file_path(key, db.root)
            rows = list(db.connection.execute(_MODEL_BY_FILE_SQL, (file_path,)))
        if not rows:
            result = "No model found."
        elif len(rows) > 1:
            result = "File contains more than one model; pass a model name."
        else:
            model_row = rows[0]
            model_name = str(model_row["qualified_name"])
            relative = _relative_query(model_name, query_name)
            query_row = db.connection.execute(_QUERY_SQL, (model_name, relative)).fetchone()
            if query_row is None:
                result = "No query found."
            else:
                path = str(model_row["file_path"])
                text = (db.root / path).read_text(encoding="utf-8")
                span = _source_span(text, str(model_row["dialect"]), relative, model_name)
                result = "No SQL source for this query."
                if span is not None:
                    header = f"Model: {model_name}" if from_file else f"File: {path}"
                    columns = [
                        (
                            str(column["name"]),
                            str(column["data_type"]),
                            None if column["nullable"] is None else int(column["nullable"]),
                        )
                        for column in db.connection.execute(_COLUMNS_SQL, (model_name, relative))
                    ]
                    result = _format_query(
                        header, text.splitlines(), span[0], span[1], span[2], columns
                    )
    return result
