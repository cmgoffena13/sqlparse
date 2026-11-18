import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import Context, FastMCP

from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.skill import DESCRIPTION, SKILL_INSTRUCTIONS
from src.utils import get_sqlparse_config_dir

_INSTRUCTIONS = """\
sqlparse tools read an indexed SQLMesh project.
Use the ``skill://sqlparse/SKILL.md`` resource if the skill is not found.
"""


def index_root() -> Path:
    workspace = os.environ.get("SQLPARSE_WORKSPACE", "").strip()
    if not workspace:
        workspace = os.environ.get("CLAUDE_WORKSPACE", "").strip()
    return Path(workspace).resolve() if workspace else Path.cwd().resolve()


@asynccontextmanager
async def _lifespan(_app: FastMCP) -> AsyncGenerator[dict[str, ProjectDB]]:
    get_sqlparse_config_dir()
    root = index_root()
    db = ProjectDB(root)
    ProjectProcessor(db, root).process()
    try:
        yield {"db": db}
    finally:
        db.close()


mcp = FastMCP("sqlparse", instructions=_INSTRUCTIONS, lifespan=_lifespan)


def _db(ctx: Context) -> ProjectDB:
    db = ctx.lifespan_context["db"]
    if not isinstance(db, ProjectDB):
        raise TypeError("index database missing from MCP lifespan")
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
def example(ctx: Context, name: str) -> str:
    """Example tool."""
    root = _db(ctx).root
    return f"example: {name}\n{root}\n"
