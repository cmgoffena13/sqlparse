import asyncio

import mcp_types
import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from src.sqlparse_mcp.skill import SKILL_INSTRUCTIONS
from tests.conftest import FIXTURE_PROJECT

_TOOLS = {"search"}


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

    asyncio.run(run())
