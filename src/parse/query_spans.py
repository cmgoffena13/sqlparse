import re
from pathlib import Path

from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import traverse_scope
from sqlmesh.core.dialect import parse as parse_sql
from sqlmesh.core.model import Model

_FINAL = "$"


def neutralize_jinja(text: str) -> str:
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


def _stored_name(name: str) -> str:
    stored = name
    if not name.startswith(_FINAL):
        stored = f"{_FINAL}{name}"
    return stored


def _line_span(expression: exp.Expr) -> tuple[int, int]:
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


def _spans_from_expression(
    expression: exp.Expression, lines: list[str]
) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    if isinstance(expression, exp.Query):
        for scope in traverse_scope(expression):
            parent = scope.expression.parent
            name = _FINAL
            if scope.is_cte and parent is not None:
                name = parent.alias_or_name
            stored = _stored_name(name)
            included = (scope.is_cte or scope.is_root) and stored not in spans
            if included:
                start, end = _line_span(scope.expression)
                if start:
                    spans[stored] = _expand_query_span(lines, start, end)
    return spans


def source_query_spans(text: str, dialect: str) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    lines = text.splitlines()
    try:
        expressions = parse_sql(neutralize_jinja(text), default_dialect=dialect)
    except ParseError:
        expressions = []
    for expression in expressions:
        if isinstance(expression, exp.Expression):
            spans.update(_spans_from_expression(expression, lines))
    return spans


def model_query_line_spans(model: Model, dialect: str) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    path = model._path
    text = "" if path is None else Path(str(path)).read_text(encoding="utf-8")
    lines = text.splitlines()
    query = getattr(model, "query", None)
    if isinstance(query, exp.Expression) and lines:
        spans = _spans_from_expression(query, lines)
    if not spans and text:
        spans = source_query_spans(text, dialect)
    return spans
