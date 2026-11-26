import re
import sqlite3
from typing import TypedDict

from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import traverse_scope
from sqlmesh.core.dialect import parse as parse_sql

from src.db import ProjectDB
from src.parse.column_lineage import FINAL_QUERY, _query_line_span, stored_query_name
from src.sqlparse_mcp.column_relations import _resolve_query_name
from src.sqlparse_mcp.format_utils import bullet, omit_default_catalog
from src.sqlparse_mcp.model import _normalize_file_path
from src.sqlparse_mcp.model_utils import (
    default_catalog,
    model_not_found_message,
    resolve_model_qualified_name,
)

_CONFIG_QUERY = "$CONFIG"
_EXTERNAL_QUERY = "$EXTERNAL"

_MODEL_SQL = """
SELECT
    models.qualified_name,
    models.dialect,
    models.kind,
    models.config_start_line,
    models.config_end_line,
    files.path AS file_path
FROM models
INNER JOIN files
    ON files.id = models.file_id
WHERE models.qualified_name = ?
"""

_MODEL_BY_FILE_SQL = """
SELECT
    models.qualified_name,
    models.dialect,
    models.kind,
    models.config_start_line,
    models.config_end_line,
    files.path AS file_path
FROM models
INNER JOIN files
    ON files.id = models.file_id
WHERE files.path = ?
ORDER BY models.qualified_name
"""

_RENDERED_SQL = """
SELECT queries.rendered_sql
FROM queries
INNER JOIN models
    ON models.id = queries.model_id
WHERE models.qualified_name = ?
  AND queries.name = ?
"""

_QUERY_SQL = """
SELECT queries.name
FROM queries
INNER JOIN models
    ON models.id = queries.model_id
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
INNER JOIN files
    ON files.id = models.file_id
WHERE files.path = ?
ORDER BY models.config_start_line, models.qualified_name
"""

_FILE_AUDITS_SQL = """
SELECT
    audits.name,
    audits.line_start,
    audits.line_end
FROM audits
INNER JOIN files
    ON files.id = audits.file_id
WHERE files.path = ?
ORDER BY audits.line_start, audits.name
"""

_FILE_MACROS_SQL = """
SELECT
    macros.name,
    macros.kind,
    macros.line_start,
    macros.line_end
FROM macros
INNER JOIN files
    ON files.id = macros.file_id
WHERE files.path = ?
ORDER BY macros.line_start, macros.name
"""

_FILE_TESTS_SQL = """
SELECT
    tests.name,
    tests.line_start,
    tests.line_end
FROM tests
INNER JOIN files
    ON files.id = tests.file_id
WHERE files.path = ?
ORDER BY tests.line_start, tests.name
"""

_MACRO_MODELS_SQL = """
SELECT
    models.qualified_name
FROM model_macros
INNER JOIN models
    ON models.id = model_macros.model_id
WHERE model_macros.macro_name = ?
ORDER BY models.qualified_name
"""

_AUDIT_MODELS_SQL = """
SELECT
    models.qualified_name
FROM model_audits
INNER JOIN models
    ON models.id = model_audits.model_id
WHERE model_audits.audit_name = ?
ORDER BY models.qualified_name
"""

_QUERY_MACROS_SQL = """
SELECT macros.name
FROM model_macros
INNER JOIN macros
    ON macros.name = model_macros.macro_name
INNER JOIN models
    ON models.id = model_macros.model_id
WHERE models.qualified_name = ?
ORDER BY macros.name
"""

_COLUMNS_SQL = """
SELECT
    columns.name,
    columns.data_type,
    columns.nullable,
    columns.unique_constraint
FROM columns
INNER JOIN queries
    ON queries.id = columns.query_id
INNER JOIN models
    ON models.id = columns.model_id
WHERE models.qualified_name = ?
  AND queries.name = ?
  AND columns.is_select = 1
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
                        shown = model_name if name == "$" else stored_query_name(name)
                        span = (expanded[0], expanded[1], shown)
    return span


def _called_macros(text: str, names: list[str]) -> list[str]:
    return [
        name for name in names if re.search(r"(?:@|\{\{|\{%)\s*" + re.escape(name) + r"\b", text)
    ]


def _query_macros(db: ProjectDB, model_name: str, text: str) -> list[str]:
    names = [str(row["name"]) for row in db.connection.execute(_QUERY_MACROS_SQL, (model_name,))]
    return _called_macros(text, names)


def _output_label(
    name: str,
    data_type: str,
    nullable: int | None,
    unique_constraint: int | None,
    width: int,
) -> str:
    constraint = ""
    if nullable == 0:
        constraint = f"{constraint} NOT NULL"
    if unique_constraint == 1:
        constraint = f"{constraint} UNIQUE"
    return f"{name:<{width}} {data_type}{constraint}"


def _rendered_sql(db: ProjectDB, model_name: str, query_name: str) -> str | None:
    row = db.connection.execute(_RENDERED_SQL, (model_name, query_name)).fetchone()
    stored = None if row is None else row["rendered_sql"]
    return None if stored is None else str(stored)


def _select_columns(
    db: ProjectDB, model_name: str, relative: str
) -> list[tuple[str, str, int | None, int | None]]:
    return [
        (
            str(column["name"]),
            str(column["data_type"]),
            None if column["nullable"] is None else int(column["nullable"]),
            None if column["unique_constraint"] is None else int(column["unique_constraint"]),
        )
        for column in db.connection.execute(_COLUMNS_SQL, (model_name, relative))
    ]


def _format_output_schema(
    qualifier: str,
    columns: list[tuple[str, str, int | None, int | None]],
) -> str:
    result = "No columns found.\n"
    if columns:
        labels = [f"{qualifier}.{name}" for name, _data_type, _nullable, _unique in columns]
        width = max(len(label) for label in labels)
        result = (
            "\n".join(
                bullet(_output_label(label, data_type, nullable, unique_constraint, width))
                for label, (_name, data_type, nullable, unique_constraint) in zip(
                    labels, columns, strict=True
                )
            )
            + "\n"
        )
    return result


def _format_query(
    header: str,
    lines: list[str],
    start: int,
    end: int,
    macros: list[str],
    sql: str | None,
) -> str:
    chunk = lines[start - 1 : end]
    gutter = len(str(end))
    body = [f"L{lineno:<{gutter}} | {line}" for lineno, line in enumerate(chunk, start)]
    if sql is not None:
        body = sql.splitlines()
    rendered = [header, "", *body]
    if macros:
        heading = "## Macros Rendered" if sql is not None else "## Macro Refs"
        rendered.extend(["", heading, ""])
        rendered.extend(bullet(name) for name in macros)
    return "\n".join(rendered) + "\n"


def get_query(db: ProjectDB, target: str, query_name: str | None, render: bool = False) -> str:
    key = target.strip()
    result = "No target given; pass a model name or file path."
    if key:
        resolved = resolve_model_qualified_name(db, key)
        rows = list(db.connection.execute(_MODEL_SQL, (resolved,))) if resolved is not None else []
        from_file = not rows
        if from_file:
            file_path = _normalize_file_path(key, db.root)
            rows = list(db.connection.execute(_MODEL_BY_FILE_SQL, (file_path,)))
        if not rows:
            result = model_not_found_message()
        elif len(rows) > 1:
            result = "File contains more than one model; pass a model name."
        else:
            model_row = rows[0]
            model_name = str(model_row["qualified_name"])
            path = str(model_row["file_path"])
            shown = omit_default_catalog(model_name, default_catalog(db))
            header = f"Model: {shown}" if from_file else f"File: {path}"
            asked = "" if query_name is None else query_name.strip()
            result = _EXTERNAL_QUERY
            if asked == _CONFIG_QUERY and str(model_row["kind"]) == "EXTERNAL":
                result = _EXTERNAL_QUERY
            elif asked == _CONFIG_QUERY:
                text = (db.root / path).read_text(encoding="utf-8")
                result = _format_query(
                    header,
                    text.splitlines(),
                    int(model_row["config_start_line"]),
                    int(model_row["config_end_line"]),
                    [],
                    None,
                )
            elif str(model_row["kind"]) == "EXTERNAL":
                result = _format_query(header, [], 1, 1, [], _EXTERNAL_QUERY)
            else:
                relative = _relative_query(model_name, query_name)
                query_row = db.connection.execute(_QUERY_SQL, (model_name, relative)).fetchone()
                if query_row is None:
                    result = "No query found."
                else:
                    text = (db.root / path).read_text(encoding="utf-8")
                    span = _source_span(text, str(model_row["dialect"]), relative, model_name)
                    result = "No SQL source for this query."
                    if span is not None:
                        query_lines = text.splitlines()
                        source = "\n".join(query_lines[span[0] - 1 : span[1]])
                        sql = _rendered_sql(db, model_name, relative) if render else None
                        if not render or sql is not None:
                            result = _format_query(
                                header,
                                query_lines,
                                span[0],
                                span[1],
                                _query_macros(db, model_name, source),
                                sql,
                            )
    return result


def get_query_schema(db: ProjectDB, target: str, query_name: str | None) -> str:
    key = target.strip()
    result = "No target given; pass a model name or file path."
    if key:
        resolved = resolve_model_qualified_name(db, key)
        rows = list(db.connection.execute(_MODEL_SQL, (resolved,))) if resolved is not None else []
        if not rows:
            file_path = _normalize_file_path(key, db.root)
            rows = list(db.connection.execute(_MODEL_BY_FILE_SQL, (file_path,)))
        if not rows:
            result = model_not_found_message()
        elif len(rows) > 1:
            result = "File contains more than one model; pass a model name."
        else:
            model_row = rows[0]
            model_name = str(model_row["qualified_name"])
            asked = "" if query_name is None else query_name.strip()
            result = "No columns found.\n"
            if asked != _CONFIG_QUERY:
                relative = _relative_query(model_name, query_name)
                columns: list[tuple[str, str, int | None, int | None]] = []
                if str(model_row["kind"]) == "EXTERNAL":
                    if relative == FINAL_QUERY:
                        columns = _select_columns(db, model_name, relative)
                else:
                    query_row = db.connection.execute(_QUERY_SQL, (model_name, relative)).fetchone()
                    if query_row is None:
                        result = "No query found."
                    else:
                        columns = _select_columns(db, model_name, relative)
                if result != "No query found.":
                    catalog = default_catalog(db)
                    qualifier = omit_default_catalog(model_name, catalog)
                    if relative != FINAL_QUERY:
                        qualifier = omit_default_catalog(stored_query_name(relative), catalog)
                    result = _format_output_schema(qualifier, columns)
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


def _shown_query_name(query_name: str, display_name: str) -> str:
    shown = query_name
    if query_name != "$":
        shown = f"${display_name}"
    return shown


def _path_kind(path: str) -> str:
    kind = "model"
    for part in path.split("/")[:-1]:
        if part == "audits":
            kind = "audit"
        elif part == "macros":
            kind = "macro"
        elif part == "tests":
            kind = "test"
    return kind


def _stored_spans(db: ProjectDB, path: str, kind: str) -> list[_LineSpan]:
    sql = {
        "audit": _FILE_AUDITS_SQL,
        "macro": _FILE_MACROS_SQL,
        "test": _FILE_TESTS_SQL,
    }[kind]
    spans: list[_LineSpan] = []
    for row in db.connection.execute(sql, (path,)):
        name = str(row["name"])
        query_name = ""
        if kind == "macro":
            query_name = str(row["kind"])
        spans.append(
            {
                "kind": kind,
                "model_name": name,
                "query_name": query_name,
                "display_name": name,
                "start": int(row["line_start"]),
                "end": int(row["line_end"]),
            }
        )
    return spans


def _span_label(span: _LineSpan, catalog: str | None = None) -> str:
    model_shown = omit_default_catalog(span["model_name"], catalog)
    label = f"{model_shown}/{_CONFIG_QUERY}"
    if span["kind"] == "query":
        label = f"{model_shown}/{_shown_query_name(span['query_name'], span['display_name'])}"
    elif span["kind"] == "audit":
        label = f"Audit: {span['model_name']}"
    elif span["kind"] == "macro":
        label = f"Macro: {span['model_name']}"
    elif span["kind"] == "test":
        label = f"Test: {span['model_name']}"
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
            queries = [span for span in spans if span["kind"] != "config"]
            if queries:
                gap = min(_gap(span, start, end) for span in queries)
                chosen = [span for span in queries if _gap(span, start, end) == gap]
    chosen.sort(key=lambda span: (span["start"], span["model_name"], span["query_name"]))
    return chosen


def _referenced_models(db: ProjectDB, kind: str, name: str) -> list[str]:
    sql = _AUDIT_MODELS_SQL if kind == "audit" else _MACRO_MODELS_SQL
    catalog = default_catalog(db)
    return [
        omit_default_catalog(str(row["qualified_name"]), catalog)
        for row in db.connection.execute(sql, (name,))
    ]


def _render_span(db: ProjectDB, lines: list[str], span: _LineSpan) -> str:
    macros: list[str] = []
    catalog = default_catalog(db)
    model_shown = omit_default_catalog(span["model_name"], catalog)
    detail = f"Model: {model_shown}"
    if span["kind"] == "query":
        shown = _shown_query_name(span["query_name"], span["display_name"])
        detail = f"{detail}\nQuery: {shown}"
        source = "\n".join(lines[span["start"] - 1 : span["end"]])
        macros = _query_macros(db, span["model_name"], source)
    elif span["kind"] == "config":
        detail = f"{detail}\nQuery: {_CONFIG_QUERY}"
    elif span["kind"] == "audit":
        detail = f"Audit: {span['model_name']}"
    elif span["kind"] == "macro":
        detail = f"Macro: {span['model_name']}\nType: {span['query_name']}"
    elif span["kind"] == "test":
        detail = f"Test: {span['model_name']}"
    text = _format_query(
        detail,
        lines,
        span["start"],
        span["end"],
        macros,
        None,
    )
    referenced: list[str] = []
    if span["kind"] in {"audit", "macro"}:
        referenced = _referenced_models(db, span["kind"], span["model_name"])
    if referenced:
        footer = "\n".join(["## Models", "", *[bullet(name) for name in referenced]])
        text = f"{text}\n{footer}\n"
    return text


def _render_many(spans: list[_LineSpan], catalog: str | None) -> str:
    lines = ["Multiple spans found:"]
    for span in spans:
        lines.append(bullet(f"{_span_label(span, catalog)} L{span['start']}-L{span['end']}"))
    return "\n".join(lines) + "\n"


def get_span_at_lines(
    db: ProjectDB,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
) -> str:
    end = start_line if end_line is None else end_line
    key = file_path.strip()
    result = "No file path given; pass a file path."
    if key:
        path = _normalize_file_path(key, db.root)
        kind = _path_kind(path)
        spans: list[_LineSpan] = []
        text = ""
        missing = {
            "model": "No model found.",
            "audit": "No audit found.",
            "macro": "No macro found.",
            "test": "No test found.",
        }
        result = missing[kind]
        if kind == "model":
            models = list(db.connection.execute(_FILE_MODELS_SQL, (path,)))
            if models:
                text = (db.root / path).read_text(encoding="utf-8")
                spans = _file_spans(text, models)
        else:
            spans = _stored_spans(db, path, kind)
            if spans:
                text = (db.root / path).read_text(encoding="utf-8")
        if spans:
            chosen = _matching_spans(spans, start_line, end)
            if kind == "model" and not chosen:
                result = "No query found."
            elif len(chosen) == 1:
                result = _render_span(db, text.splitlines(), chosen[0])
            elif chosen:
                result = _render_many(chosen, default_catalog(db))
    return result
