from pathlib import Path

from sqlmesh.core.dialect import Audit as AuditExpr
from sqlmesh.core.dialect import parse as sqlmesh_parse


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
