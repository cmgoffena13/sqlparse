import ast
from pathlib import Path
from typing import cast

from sqlmesh.core import constants as sqlmesh_constants
from sqlmesh.core.dialect import Model as ModelExpr
from sqlmesh.core.dialect import parse as sqlmesh_parse
from sqlmesh.core.model import Model, PythonModel


def model_is_blueprint(model: Model) -> bool:
    env = model.python_env or {}
    return (
        sqlmesh_constants.SQLMESH_BLUEPRINT_VARS in env
        or sqlmesh_constants.SQLMESH_BLUEPRINT_VARS_METADATA in env
    )


def model_time_column(model: Model) -> str | None:
    column = getattr(model.kind, "time_column", None)
    name = None
    if column is not None:
        name = column.column.name
    return name


def model_grain(model: Model) -> str | None:
    names = [grain.name or grain.sql(dialect=model.dialect) for grain in model.grains]
    return ", ".join(names) if names else None


def model_config_lines(model: Model) -> tuple[int, int]:
    text = Path(str(model._path)).read_text(encoding="utf-8")
    source_type = model.source_type
    start_line = 0
    end_line = 0
    if source_type in ("sql", "seed"):
        model_sql = next(
            expression.meta["sql"]
            for expression in sqlmesh_parse(text, default_dialect=model.dialect)
            if isinstance(expression, ModelExpr)
        )
        offset = text.find(model_sql)
        start_line = text.count("\n", 0, offset) + 1
        end_line = start_line + model_sql.count("\n")
    if source_type == "python" and isinstance(model, PythonModel):
        tree = ast.parse(text)
        decorator = next(
            deco
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == model.entrypoint
            for deco in node.decorator_list
            if isinstance(deco, ast.Call)
        )
        start_line = decorator.lineno
        end_line = cast(int, decorator.end_lineno)
    if source_type == "external":
        lines = text.splitlines()
        marker = f"- name: {model.name}"
        start_line = next(i for i, line in enumerate(lines, start=1) if line.strip() == marker)
        end_line = start_line
        for i, line in enumerate(lines[start_line:], start=start_line + 1):
            if line.startswith("- "):
                break
            if line.strip():
                end_line = i
    return start_line, end_line
