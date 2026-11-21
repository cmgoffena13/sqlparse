import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastmcp import Context, FastMCP

from src.db import ProjectDB
from src.parse.sqlmesh_parser import is_sqlmesh_project
from src.processor import ProjectProcessor
from src.sqlparse_mcp.audit import get_audit as run_get_audit
from src.sqlparse_mcp.column_relations import get_column_relations as run_get_column_relations
from src.sqlparse_mcp.directory_tree import get_directory_tree as run_get_directory_tree
from src.sqlparse_mcp.listing import list_models as run_list_models
from src.sqlparse_mcp.listing import list_schemas as run_list_schemas
from src.sqlparse_mcp.macro import get_macro as run_get_macro
from src.sqlparse_mcp.model import get_model as run_get_model
from src.sqlparse_mcp.model_relations import get_model_relations as run_get_model_relations
from src.sqlparse_mcp.model_test import get_test as run_get_test
from src.sqlparse_mcp.query import get_query as run_get_query
from src.sqlparse_mcp.query import get_span_at_lines as run_get_span_at_lines
from src.sqlparse_mcp.search import search as run_search
from src.sqlparse_mcp.skill import DESCRIPTION, SKILL_INSTRUCTIONS
from src.utils import get_sqlparse_config_dir

_INSTRUCTIONS = """\
sqlparse tools read an up-to-date view of a SQLMesh project.

Queries/CTEs are prefixed with ``$``. 
A single ``$`` is the final output query.
Model Config is treated as a query and called ``MODEL``.
EXTERNAL models have no query and return ``EXTERNAL``.

Ex. ``$``, ``$cte_name``, ``MODEL``, or ``EXTERNAL``.

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
def search(
    ctx: Context,
    query: str,
    limit: int = 20,
    models: bool = True,
    queries: bool = True,
    columns: bool = True,
) -> str:
    """
    FTS model, query, and column names. Results are ordered #1, #2, #3... by relevance.

    Narrow with one distinctive word; Widen with extra space-separated words (OR).

    ``models``, ``queries``, and ``columns`` choose which types to search.
    All three are included by default.
    """
    return run_search(_db(ctx), query, limit, models, queries, columns)


@mcp.tool()
def list_schemas(ctx: Context) -> str:
    """Return every schema name."""
    return run_list_schemas(_db(ctx))


@mcp.tool()
def list_models(ctx: Context, schema: str) -> str:
    """Return the model names in one schema."""
    return run_list_models(_db(ctx), schema)


@mcp.tool()
def get_directory_tree(ctx: Context, directory_path: str | None = None) -> str:
    """
    Return the project's directory/file tree with line counts.

    Optional ``directory_path`` scopes to one directory tree (exact path).
    """
    return run_get_directory_tree(_db(ctx), directory_path)


@mcp.tool()
def get_model(ctx: Context, target: str) -> str:
    """
    Return a model's SQL tree, macro refs, and audit refs.

    Target can be a model name or model file path.
    Ex. ``sushi.customer_orders`` or `sushi/models/customer_orders.sql`
    """
    return run_get_model(_db(ctx), target)


@mcp.tool()
def get_query(
    ctx: Context, target: str, query_name: str | None = None, render: bool = False
) -> str:
    """
    Return a query's output schema and definition for a model name or model file path.

    Target can be a model name or model file path.
    Ex. ``sushi.customer_orders`` or `sushi/models/customer_orders.sql`

    Enable ``render`` to render the query's macros.
    """
    return run_get_query(_db(ctx), target, query_name, render)


@mcp.tool()
def get_span_at_lines(
    ctx: Context,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
) -> str:
    """
    Return the query, audit, macro, or test that contains ``start_line`` through ``end_line``.

    ``end_line`` defaults to ``start_line`` if not provided.

    The tightest match that contains the whole range is returned.
    A range that crosses spans lists each span name.
    """
    return run_get_span_at_lines(_db(ctx), file_path, start_line, end_line)


@mcp.tool()
def get_test(ctx: Context, file_path: str, test_name: str) -> str:
    """
    Return a test definition.
    """
    return run_get_test(_db(ctx), file_path, test_name)


@mcp.tool()
def get_macro(ctx: Context, file_path: str, macro_name: str) -> str:
    """
    Return a macro's definition and the models that use it.
    """
    return run_get_macro(_db(ctx), file_path, macro_name)


@mcp.tool()
def get_audit(ctx: Context, file_path: str, audit_name: str) -> str:
    """
    Return an audit's definition and the models that use it.
    """
    return run_get_audit(_db(ctx), file_path, audit_name)


@mcp.tool()
def get_model_relations(
    ctx: Context,
    model_name: str,
    relation: Literal["dependents", "dependencies"] = "dependents",
    include_tests: bool = False,
    page: int = 1,
) -> str:
    """
    Return model relations for ``model_name``.

    ``dependencies`` lists upstream models this model reads.
    ``dependents`` lists downstream models that read it.

    Excludes test files from dependents by default; set ``include_tests`` to include them.
    """
    return run_get_model_relations(_db(ctx), model_name, relation, include_tests, page)


@mcp.tool()
def get_column_relations(
    ctx: Context,
    model_name: str,
    column_name: str,
    query_name: str | None = None,
    relation: Literal["dependents", "dependencies"] = "dependents",
    include_tests: bool = False,
    page: int = 1,
) -> str:
    """
    Return column relations for ``model_name`` / ``query_name`` / ``column_name``.
    ``query_name`` defaults to ``$`` (final output query).

    ``dependencies`` lists upstream columns this column reads.
    ``dependents`` lists downstream columns that read it.

    Excludes test files from dependents by default; set ``include_tests`` to include them.
    """
    return run_get_column_relations(
        _db(ctx),
        model_name,
        query_name,
        column_name,
        relation,
        include_tests=include_tests,
        page=page,
    )
