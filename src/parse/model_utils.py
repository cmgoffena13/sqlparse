import ast
from functools import lru_cache
from pathlib import Path
from typing import cast

from sqlmesh.core import constants as sqlmesh_constants
from sqlmesh.core.dialect import Model as ModelExpr
from sqlmesh.core.dialect import parse as sqlmesh_parse
from sqlmesh.core.model import Model, PythonModel
from sqlmesh.utils.yaml import YAML

from src.parse.sqlmesh_utils import normalized_model_name


def model_qualified_name(model: Model) -> str:
    return normalized_model_name(model.fqn, model.default_catalog, model.dialect)


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


@lru_cache(maxsize=4096)
def read_model_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@lru_cache(maxsize=4096)
def _sql_model_config_span(path: str, dialect: str) -> tuple[int, int]:
    text = read_model_file(path)
    model_sql = next(
        expression.meta["sql"]
        for expression in sqlmesh_parse(text, default_dialect=dialect)
        if isinstance(expression, ModelExpr)
    )
    offset = text.find(model_sql)
    start_line = text.count("\n", 0, offset) + 1
    return start_line, start_line + model_sql.count("\n")


@lru_cache(maxsize=4096)
def _python_model_config_span(path: str, entrypoint: str) -> tuple[int, int]:
    tree = ast.parse(read_model_file(path))
    decorator = next(
        deco
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entrypoint
        for deco in node.decorator_list
        if isinstance(deco, ast.Call)
    )
    return decorator.lineno, cast(int, decorator.end_lineno)


@lru_cache(maxsize=4096)
def _external_model_config_span(path: str, model_name: str) -> tuple[int, int]:
    text = read_model_file(path)
    lines = text.splitlines()
    row = next(entry for entry in YAML(typ="rt").load(text) if entry["name"] == model_name)
    start_line = row.lc.line + 1
    end_line = start_line
    for i, line in enumerate(lines[start_line:], start=start_line + 1):
        if line.startswith("- "):
            break
        if line.strip():
            end_line = i
    return start_line, end_line


def clear_model_file_caches() -> None:
    read_model_file.cache_clear()
    _sql_model_config_span.cache_clear()
    _python_model_config_span.cache_clear()
    _external_model_config_span.cache_clear()


def model_config_lines(model: Model) -> tuple[int, int]:
    path = str(model._path)
    source_type = model.source_type
    start_line = 0
    end_line = 0
    if source_type in ("sql", "seed"):
        start_line, end_line = _sql_model_config_span(path, str(model.dialect))
    if source_type == "python" and isinstance(model, PythonModel):
        start_line, end_line = _python_model_config_span(path, model.entrypoint)
    if source_type == "external":
        start_line, end_line = _external_model_config_span(path, model.name)
    return start_line, end_line
