import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

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
from src.sqlparse_mcp.session_stats import SessionStatsMiddleware, format_session_stats_report
from src.sqlparse_mcp.skill import DESCRIPTION, SKILL_INSTRUCTIONS
from src.utils import get_sqlparse_config_dir

_INSTRUCTIONS = """\
sqlparse tools read an up-to-date view of a SQLMesh project.

Utilize the ``sqlparse`` skill for guided exploration workflows.
Use the ``skill://sqlparse/SKILL.md`` resource if the skill is not found.
Read ``workspace://sqlparse/root`` when the indexed tree may not match the project.
"""


def index_root() -> Path:
    workspace = os.environ.get("SQLPARSE_WORKSPACE", "").strip()
    if not workspace:
        workspace = os.environ.get("CLAUDE_WORKSPACE", "").strip()
    return Path(workspace).resolve() if workspace else Path.cwd().resolve()


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncGenerator[dict[str, Any]]:
    get_sqlparse_config_dir()
    root = index_root()
    db = ProjectDB(root) if is_sqlmesh_project(root) else None
    processor = ProjectProcessor(db, root) if db is not None else None
    if processor is not None:
        processor.process()
    try:
        yield {"db": db, "processor": processor}
    finally:
        if processor is not None:
            processor.close()
        if db is not None:
            db.close()


mcp = FastMCP("sqlparse", instructions=_INSTRUCTIONS, lifespan=_lifespan)
mcp.add_middleware(SessionStatsMiddleware())


def _processor(ctx: Context) -> ProjectProcessor:
    processor = ctx.lifespan_context["processor"]
    if processor is None:
        raise RuntimeError(f"{index_root()} is not a SQLMesh project")
    return processor


@mcp.resource(
    "skill://sqlparse/SKILL.md",
    name="sqlparse/SKILL.md",
    description=DESCRIPTION,
    mime_type="text/markdown",
)
def sqlparse_skill() -> str:
    return SKILL_INSTRUCTIONS


@mcp.resource(
    "stats://sqlparse/sessions",
    name="sqlparse/sessions",
    description="Per MCP session (id + start time), a markdown table of file stats.",
    mime_type="text/markdown",
)
def session_stats_resource() -> str:
    return format_session_stats_report(index_root())


@mcp.resource(
    "workspace://sqlparse/root",
    name="sqlparse/root",
    description="Absolute path of the workspace this MCP server is indexing.",
    mime_type="text/plain",
)
def workspace_root_resource() -> str:
    return f"{index_root()}\n"


@mcp.tool()
def search(
    ctx: Context,
    query: str,
    limit: int = 20,
    search_models: bool = True,
    search_queries: bool = True,
    search_columns: bool = True,
) -> str:
    """
    FTS model, query, and column names. Results are ordered #1, #2, #3... by relevance.
    Full result format is: data_model/query_name/column_name.

    Narrow with one distinctive word; Widen with extra space-separated words (OR).

    Filter the search targets with the ``search_`` flags. All three are included by default.
    """
    return _processor(ctx).run_query(
        lambda db: run_search(db, query, limit, search_models, search_queries, search_columns)
    )


@mcp.tool()
def list_schemas(ctx: Context) -> str:
    """Return every schema name."""
    return _processor(ctx).run_query(run_list_schemas)


@mcp.tool()
def list_models(ctx: Context, schema: str) -> str:
    """Return the model names in one schema."""
    return _processor(ctx).run_query(lambda db: run_list_models(db, schema))


@mcp.tool()
def get_directory_tree(ctx: Context, directory_path: str | None = None) -> str:
    """
    Return the project's directory/file tree with line counts (L).

    Optional ``directory_path`` scopes to one directory tree (exact path).
    Ex. `audits/`
    """
    return _processor(ctx).run_query(lambda db: run_get_directory_tree(db, directory_path))


@mcp.tool()
def get_model(ctx: Context, target: str) -> str:
    """
    Return a model's SQL tree, macro refs, and audit refs.

    Target can be a model name or model file path.
    Ex. ``sushi.customer_orders`` or `sushi/models/customer_orders.sql`

    SQL Tree Legend:
     - Join Statements = J
     - Where Conditions = W
     - Grouped By Columns = G
     - Having Conditions = H
     - Select Expressions = E
     - Select Aliases = A
     - Total Select Columns = S
     - Order By Columns = O
    """
    return _processor(ctx).run_query(lambda db: run_get_model(db, target))


@mcp.tool()
def get_query(
    ctx: Context, target: str, query_name: str | None = None, render: bool = False
) -> str:
    """
    Return a query's definition and output schema.

    Target can be a model name or model file path.
    Ex. ``sushi.customer_orders`` or `sushi/models/customer_orders.sql`

    Enable ``render`` to render the SQL and the query's macros.
    """
    return _processor(ctx).run_query(lambda db: run_get_query(db, target, query_name, render))


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
    return _processor(ctx).run_query(
        lambda db: run_get_span_at_lines(db, file_path, start_line, end_line)
    )


@mcp.tool()
def get_test(ctx: Context, file_path: str, test_name: str) -> str:
    """
    Return a test definition.
    """
    return _processor(ctx).run_query(lambda db: run_get_test(db, file_path, test_name))


@mcp.tool()
def get_macro(ctx: Context, file_path: str, macro_name: str) -> str:
    """
    Return a macro's definition and the models that use it.
    """
    return _processor(ctx).run_query(lambda db: run_get_macro(db, file_path, macro_name))


@mcp.tool()
def get_audit(ctx: Context, file_path: str, audit_name: str) -> str:
    """
    Return an audit's definition and the models that use it.
    """
    return _processor(ctx).run_query(lambda db: run_get_audit(db, file_path, audit_name))


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

    Excludes test files from dependents by default; set ``include_tests`` to include them.
    """
    return _processor(ctx).run_query(
        lambda db: run_get_model_relations(db, model_name, relation, include_tests, page)
    )


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
    Return column relations for ``model_name/query_name/column_name``.

    ``query_name`` defaults to ``$`` if not provided.
    ``column_name`` should include the source query name or table name.
    Ex. ``$cte_name.customer_id`` or ``schema.table.column``

    Excludes test files from dependents by default; set ``include_tests`` to include them.

    Reference Kind Legend:
     - Join = J
     - Where = W
     - Group By = G
     - Having = H
     - Expression = E
     - Alias = A
     - Select = S
     - Order By = O
    """
    return _processor(ctx).run_query(
        lambda db: run_get_column_relations(
            db,
            model_name,
            query_name,
            column_name,
            relation,
            include_tests=include_tests,
            page=page,
        )
    )
