import asyncio
import os
from pathlib import Path

import mcp_types
import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.exceptions import ToolError

from src.parse.sqlmesh_parser import is_sqlmesh_project
from src.sqlparse_mcp.skill import SKILL_INSTRUCTIONS
from tests.conftest import FIXTURE_PROJECT

_TOOLS = {
    "search",
    "get_directory_tree",
    "get_sql_tree",
    "get_model_relations",
    "get_column_relations",
}


def _text(result: CallToolResult) -> str:
    assert result.is_error is False
    assert isinstance(result.data, str)
    return result.data


def _resource_text(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> str:
    block = contents[0]
    assert isinstance(block, mcp_types.TextResourceContents)
    return block.text


def test_client_lists_tools_and_reads_the_project(
    mcp_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQLPARSE_WORKSPACE", str(FIXTURE_PROJECT))

    async def run() -> None:
        async with mcp_client:
            tools = await mcp_client.list_tools()
            assert {tool.name for tool in tools} == _TOOLS
            skill = _resource_text(await mcp_client.read_resource("skill://sqlparse/SKILL.md"))
            assert skill == SKILL_INSTRUCTIONS
            search_out = _text(
                await mcp_client.call_tool("search", {"query": "customers", "limit": 30})
            )
            assert "## Models" in search_out
            assert "sushi.customers" in search_out
            assert "## Columns" in search_out
            tree_out = _text(
                await mcp_client.call_tool("get_directory_tree", {"directory_path": "models"})
            )
            assert tree_out.startswith("models/")
            assert "sushi.customers" in tree_out
            relations_out = _text(
                await mcp_client.call_tool(
                    "get_model_relations",
                    {"model_name": "sushi.customers", "relation": "dependents"},
                )
            )
            assert relations_out.startswith("sushi.customers\n")
            assert "sushi.customer_orders" in relations_out
            column_out = _text(
                await mcp_client.call_tool(
                    "get_column_relations",
                    {
                        "model_name": "sushi.customers",
                        "column_name": "customer_id",
                        "relation": "dependencies",
                    },
                )
            )
            assert "sushi.customers" in column_out
            assert "cte" in column_out

    asyncio.run(run())


def test_plain_config_yaml_is_not_a_sqlmesh_project(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("service: api\n", encoding="utf-8")
    assert is_sqlmesh_project(FIXTURE_PROJECT) is True
    assert is_sqlmesh_project(tmp_path) is False


def test_mcp_skips_the_database_outside_a_sqlmesh_project(
    mcp_client: Client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text("service: api\n", encoding="utf-8")
    monkeypatch.setenv("SQLPARSE_WORKSPACE", str(tmp_path))

    async def run() -> None:
        async with mcp_client:
            await mcp_client.call_tool("search", {"query": "customers"})

    with pytest.raises(ToolError, match="is not a SQLMesh project"):
        asyncio.run(run())
    config_dir = Path(os.environ["SQLPARSE_CONFIG_DIR"])
    assert list(config_dir.glob("indexes/*.db")) == []
