import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastmcp import Context, FastMCP

from src.db import ProjectDB
from src.parse.sqlmesh_parser import is_sqlmesh_project
from src.processor import ProjectProcessor
from src.sqlparse_mcp.column_relations import get_column_relations as run_column_relations
from src.sqlparse_mcp.directory_tree import get_directory_tree as run_directory_tree
from src.sqlparse_mcp.model_relations import get_model_relations as run_model_relations
from src.sqlparse_mcp.query import get_query as run_query
from src.sqlparse_mcp.search import search as run_search
from src.sqlparse_mcp.skill import DESCRIPTION, SKILL_INSTRUCTIONS
from src.sqlparse_mcp.sql_tree import get_sql_tree as run_sql_tree
from src.utils import get_sqlparse_config_dir

_INSTRUCTIONS = """\
sqlparse tools read an up-to-date view of a SQLMesh project.
Utilize the ``sqlparse`` skill for guided exploration workflows.
Use the ``skill://sqlparse/SKILL.md`` resource if the skill is not found.
"""


def index_root() -> Path:
    workspace = os.environ.get("SQLPARSE_WORKSPACE", "").strip()
    if not workspace:
        workspace = os.environ.get("CLAUDE_WORKSPACE", "").strip()
    return Path(workspace).resolve() if workspace else Path.cwd().resolve()


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncGenerator[dict[str, ProjectDB | None]]:
    get_sqlparse_config_dir()
    root = index_root()
    db = ProjectDB(root) if is_sqlmesh_project(root) else None
    if db is not None:
        ProjectProcessor(db, root).process()
    try:
        yield {"db": db}
    finally:
        if db is not None:
            db.close()


mcp = FastMCP("sqlparse", instructions=_INSTRUCTIONS, lifespan=_lifespan)


def _db(ctx: Context) -> ProjectDB:
    db = ctx.lifespan_context["db"]
    if db is None:
        raise RuntimeError(f"{index_root()} is not a SQLMesh project")
    return db


@mcp.resource(
    "skill://sqlparse/SKILL.md",
    name="sqlparse/SKILL.md",
    description=DESCRIPTION,
    mime_type="text/markdown",
)
def sqlparse_skill() -> str:
    return SKILL_INSTRUCTIONS


@mcp.tool()
def search(ctx: Context, query: str, limit: int = 20) -> str:
    """
    FTS model, query, and column names. Results are ordered #1, #2, #3... by relevance.

    Narrow with one distinctive word; Widen with extra space-separated words (OR).

    "$" is the default query name for the final output query.
    """
    return run_search(_db(ctx), query, limit)


@mcp.tool()
def get_directory_tree(ctx: Context, directory_path: str | None = None) -> str:
    """
    Return the project's directory/file tree with line counts and model names.

    Optional ``directory_path`` scopes to one directory tree (exact path).
    """
    return run_directory_tree(_db(ctx), directory_path)


@mcp.tool()
def get_sql_tree(ctx: Context, target: str) -> str:
    """
    Return the SQL query tree for a model name or model file path.

    Lists each query (``$`` for the final output, otherwise the CTE name) with
    select column, where, and join counts.
    """
    return run_sql_tree(_db(ctx), target)


@mcp.tool()
def get_query(ctx: Context, target: str, query_name: str | None = None) -> str:
    """
    Return one query's source for a model name or model file path.

    Lines use ``L{n} | {source}``. ``query_name`` defaults to ``$`` (final output query).
    ``## Output`` lists each column's data type, and ``NOT NULL`` when required.
    """
    return run_query(_db(ctx), target, query_name)


@mcp.tool()
def get_model_relations(
    ctx: Context,
    model_name: str,
    relation: Literal["dependents", "dependencies"] = "dependents",
) -> str:
    """
    Return model relations for ``model_name``.

    ``dependencies`` lists upstream models this model reads.
    ``dependents`` lists downstream models that read it.
    """
    return run_model_relations(_db(ctx), model_name, relation)


@mcp.tool()
def get_column_relations(
    ctx: Context,
    model_name: str,
    column_name: str,
    query_name: str | None = None,
    relation: Literal["dependents", "dependencies"] = "dependents",
    include_tests: bool = False,
) -> str:
    """
    Return column relations for ``model_name`` / ``query_name`` / ``column_name``.

    ``dependencies`` lists upstream columns this column reads.
    ``dependents`` lists downstream columns that read it.

    ``query_name`` defaults to ``$`` (final output query). Use a CTE name for CTE columns.
    Excludes test files from dependents by default; set ``include_tests`` to include them.
    """
    return run_column_relations(
        _db(ctx),
        model_name,
        query_name,
        column_name,
        relation,
        include_tests=include_tests,
    )
