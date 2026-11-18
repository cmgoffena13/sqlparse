"""Smoke-print MCP tool outputs against the sushi fixture."""

import asyncio
import json
import os
from pathlib import Path

import mcp_types
from fastmcp import Client
from fastmcp.client.client import CallToolResult

REPO_ROOT = Path(__file__).resolve().parent
SUSHI_ROOT = REPO_ROOT / "tests" / "fixtures" / "sushi"

_BANNER_WIDTH = 40


def _banner(title: str) -> str:
    label = f" {title} "
    pad = max(_BANNER_WIDTH - len(label), 0)
    left = pad // 2
    right = pad - left
    return f"{'-' * left}{label}{'-' * right}"


def _print_section(title: str, body: str) -> None:
    print(_banner(title))
    print(body)
    print(f"[{len(body):,} chars / {body.count(chr(10)) + 1} lines]\n")


def _body(result: CallToolResult) -> str:
    if not isinstance(result.data, str):
        raise SystemExit(f"Tool returned no text: {result.content}")
    return result.data


def _resource_text(
    contents: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents],
) -> str:
    block = contents[0]
    if not isinstance(block, mcp_types.TextResourceContents):
        raise SystemExit(f"Resource returned a blob: {block}")
    return block.text


def _server_preamble(client: Client) -> str:
    info = client.server_info
    header = "unknown" if info is None else f"{info.name} {info.version}".strip()
    return f"{header}\n\n{client.instructions or ''}".rstrip() + "\n"


def _format_tools(tools: list[mcp_types.Tool]) -> str:
    parts: list[str] = []
    for tool in tools:
        block = (
            f"{tool.name}\n{(tool.description or '').strip()}\n"
            f"input:\n{json.dumps(tool.input_schema, indent=2)}"
        )
        if tool.output_schema is not None:
            block += f"\noutput:\n{json.dumps(tool.output_schema, indent=2)}"
        parts.append(block)
    return "\n\n".join(parts) + "\n"


def _format_resources(resources: list[mcp_types.Resource]) -> str:
    parts: list[str] = []
    for resource in resources:
        parts.append(
            "\n".join(
                [
                    str(resource.uri),
                    f"name: {resource.name}",
                    f"mime: {resource.mime_type}",
                    f"description: {resource.description or ''}",
                ]
            )
        )
    formatted = "No resources.\n"
    if parts:
        formatted = "\n\n".join(parts) + "\n"
    return formatted


def _format_prompts(prompts: list[mcp_types.Prompt]) -> str:
    parts = [f"{prompt.name}\n{(prompt.description or '').strip()}" for prompt in prompts]
    formatted = "No prompts.\n"
    if parts:
        formatted = "\n\n".join(parts) + "\n"
    return formatted


async def _print_catalog(client: Client) -> None:
    _print_section("SERVER", _server_preamble(client))
    _print_section("TOOLS", _format_tools(await client.list_tools()))
    resources = await client.list_resources()
    _print_section("RESOURCES", _format_resources(resources))
    for resource in resources:
        _print_section(
            str(resource.uri),
            _resource_text(await client.read_resource(resource.uri)),
        )
    _print_section("PROMPTS", _format_prompts(await client.list_prompts()))


async def _print_tools() -> None:
    os.environ["SQLPARSE_WORKSPACE"] = str(SUSHI_ROOT)
    from src.sqlparse_mcp.server import mcp

    async with Client(mcp) as client:
        await _print_catalog(client)
        _print_section(
            "EXAMPLE",
            _body(await client.call_tool("example", {"name": "sushi"})),
        )


def main() -> None:
    if not SUSHI_ROOT.is_dir():
        raise SystemExit(f"Missing {SUSHI_ROOT}")
    asyncio.run(_print_tools())


if __name__ == "__main__":
    main()
