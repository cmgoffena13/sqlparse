from pathlib import Path

from sqlglot import exp
from sqlmesh.core.dialect import Audit as AuditExpr
from sqlmesh.core.dialect import parse as sqlmesh_parse
from sqlmesh.core.model import Model


def _names_from_columns_arg(value: object) -> set[str]:
    names: set[str] = set()
    if isinstance(value, exp.Column):
        names = {value.name}
    elif isinstance(value, exp.Tuple):
        names = {e.name for e in value.expressions if isinstance(e, exp.Column)}
    elif isinstance(value, exp.Expression):
        names = {column.name for column in value.find_all(exp.Column)}
    elif isinstance(value, (list, tuple)):
        for item in value:
            names |= _names_from_columns_arg(item)
    return names


def _names_from_is_null(query: object) -> set[str]:
    names: set[str] = set()
    if isinstance(query, exp.Expression):
        for node in query.find_all(exp.Is):
            if isinstance(node.this, exp.Column) and isinstance(node.expression, exp.Null):
                names.add(node.this.name)
    return names


def not_null_column_names(model: Model, audits_by_name: dict) -> set[str]:
    names: set[str] = set()
    for audit_name, args in model.audits:
        if audit_name in {"not_null", "not_null_non_blocking"}:
            names |= _names_from_columns_arg(args.get("columns"))
            continue
        audit = model.audit_definitions.get(audit_name) or audits_by_name.get(audit_name)
        if audit is not None:
            names |= _names_from_is_null(audit.query)
    return names


def unique_values_column_names(model: Model) -> set[str]:
    names: set[str] = set()
    for audit_name, args in model.audits:
        if audit_name in {"unique_values", "unique_values_non_blocking"}:
            names |= _names_from_columns_arg(args.get("columns"))
    return names


def audit_line_span(path: Path, dialect: str, name: str) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    expressions = sqlmesh_parse(text, default_dialect=dialect)
    blocks: list[list] = []
    current: list = []
    for expression in expressions:
        if isinstance(expression, AuditExpr) and current:
            blocks.append(current)
            current = []
        current.append(expression)
    blocks.append(current)
    line_start = 0
    line_end = 0
    for block in blocks:
        audit_expr = block[0]
        audit_name = next(
            prop.args["value"].this for prop in audit_expr.expressions if prop.this == "name"
        )
        if audit_name == name:
            first_sql = audit_expr.meta["sql"]
            last_sql = block[-1].meta["sql"]
            start_offset = text.find(first_sql)
            end_offset = text.find(last_sql) + len(last_sql)
            line_start = text.count("\n", 0, start_offset) + 1
            span = text[start_offset:end_offset]
            line_end = line_start + span.count("\n")
            if span.endswith("\n"):
                line_end -= 1
            break
    return line_start, line_end
