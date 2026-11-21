import re
import sqlite3
from typing import TypedDict

from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import traverse_scope
from sqlmesh.core.dialect import parse as parse_sql

from src.db import ProjectDB
from src.parse.column_lineage import _query_line_span, stored_query_name
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

_FILE_MODELS_SQL = """
SELECT
    models.qualified_name,
    models.dialect,
    models.config_start_line,
    models.config_end_line
FROM models
INNER JOIN files ON files.id = models.file_id
WHERE files.path = ?
ORDER BY models.config_start_line, models.qualified_name
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


def _normalized_identifier(name: str, dialect: str) -> str:
    normalized = name
    if name != "$":
        normalized = normalize_identifiers(exp.to_identifier(name), dialect=dialect).name
    return normalized


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


def _indexed_query_name(name: str, dialect: str) -> str:
    bare = name[1:] if name.startswith("$") and name != "$" else name
    return stored_query_name(_normalized_identifier(bare, dialect))


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
                same_name = _indexed_query_name(name, dialect) == _indexed_query_name(
                    query_name, dialect
                )
                if included and same_name:
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


class _LineSpan(TypedDict):
    kind: str
    model_name: str
    query_name: str
    display_name: str
    start: int
    end: int


def _parsed_query_spans(
    text: str, dialect: str, model_name: str
) -> list[tuple[str, str, int, int]]:
    spans: list[tuple[str, str, int, int]] = []
    try:
        expressions = parse_sql(_neutralize_jinja(text), default_dialect=dialect)
    except ParseError:
        expressions = []
    lines = text.splitlines()
    seen: set[str] = set()
    for expression in expressions:
        if isinstance(expression, exp.Query):
            for scope in traverse_scope(expression):
                parent = scope.expression.parent
                name = "$"
                if scope.is_cte and parent is not None:
                    name = parent.alias_or_name
                stored = _indexed_query_name(name, dialect)
                included = (scope.is_cte or scope.is_root) and stored not in seen
                if included:
                    start, end = _query_line_span(scope.expression)
                    if start:
                        seen.add(stored)
                        expanded = _expand_query_span(lines, start, end)
                        display = model_name if name == "$" else name
                        spans.append((stored, display, expanded[0], expanded[1]))
    return spans


def _file_spans(text: str, models: list[sqlite3.Row]) -> list[_LineSpan]:
    spans: list[_LineSpan] = []
    for model in models:
        model_name = str(model["qualified_name"])
        spans.append(
            {
                "kind": "config",
                "model_name": model_name,
                "query_name": "",
                "display_name": model_name,
                "start": int(model["config_start_line"]),
                "end": int(model["config_end_line"]),
            }
        )
        for query_name, display_name, start, end in _parsed_query_spans(
            text, str(model["dialect"]), model_name
        ):
            spans.append(
                {
                    "kind": "query",
                    "model_name": model_name,
                    "query_name": query_name,
                    "display_name": display_name,
                    "start": start,
                    "end": end,
                }
            )
    return spans


def _span_label(span: _LineSpan) -> str:
    label = f"{span['model_name']} (model config)"
    if span["kind"] == "query":
        query_label = span["display_name"] if span["query_name"] != "$" else span["query_name"]
        label = f"{span['model_name']}/{query_label}"
    return label


def _gap(span: _LineSpan, start: int, end: int) -> int:
    gap = 0
    if end < span["start"]:
        gap = span["start"] - end
    elif start > span["end"]:
        gap = start - span["end"]
    return gap


def _matching_spans(spans: list[_LineSpan], start: int, end: int) -> list[_LineSpan]:
    containers = [span for span in spans if span["start"] <= start and end <= span["end"]]
    chosen = containers
    if containers:
        width = min(span["end"] - span["start"] for span in containers)
        chosen = [span for span in containers if span["end"] - span["start"] == width]
        latest = max(span["start"] for span in chosen)
        chosen = [span for span in chosen if span["start"] == latest]
    else:
        chosen = [span for span in spans if span["start"] <= end and start <= span["end"]]
        if not chosen:
            queries = [span for span in spans if span["kind"] == "query"]
            if queries:
                gap = min(_gap(span, start, end) for span in queries)
                chosen = [span for span in queries if _gap(span, start, end) == gap]
    chosen.sort(key=lambda span: (span["start"], span["model_name"], span["query_name"]))
    return chosen


def _render_span(db: ProjectDB, lines: list[str], span: _LineSpan) -> str:
    columns: list[tuple[str, str, int | None]] = []
    if span["kind"] == "query":
        columns = [
            (
                str(column["name"]),
                str(column["data_type"]),
                None if column["nullable"] is None else int(column["nullable"]),
            )
            for column in db.connection.execute(
                _COLUMNS_SQL, (span["model_name"], span["query_name"])
            )
        ]
    header = f"Model: {span['model_name']}"
    if span["kind"] == "query":
        query_label = span["display_name"] if span["query_name"] != "$" else span["query_name"]
        header = f"{header}\nQuery: {query_label}"
    return _format_query(
        header,
        lines,
        span["start"],
        span["end"],
        span["display_name"],
        columns,
    )


def _render_many(spans: list[_LineSpan]) -> str:
    lines = ["Multiple queries found:"]
    for span in spans:
        lines.append(bullet(f"{_span_label(span)} L{span['start']}-L{span['end']}"))
    return "\n".join(lines) + "\n"


def get_query_at_lines(
    db: ProjectDB, file_path: str, start_line: int, end_line: int | None = None
) -> str:
    end = start_line if end_line is None else end_line
    key = file_path.strip()
    result = "No file path given; pass a model file path."
    if key:
        path = _normalize_file_path(key, db.root)
        models = list(db.connection.execute(_FILE_MODELS_SQL, (path,)))
        result = "No model found."
        if models:
            text = (db.root / path).read_text(encoding="utf-8")
            chosen = _matching_spans(_file_spans(text, models), start_line, end)
            result = "No query found."
            if len(chosen) == 1:
                result = _render_span(db, text.splitlines(), chosen[0])
            elif chosen:
                result = _render_many(chosen)
    return result
