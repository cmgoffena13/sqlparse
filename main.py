"""Smoke-print MCP tool outputs against the sushi fixture."""

import asyncio
import os
from pathlib import Path

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


async def _print_tools() -> None:
    os.environ["SQLPARSE_WORKSPACE"] = str(SUSHI_ROOT)
    from src.sqlparse_mcp.server import mcp

    async with Client(mcp) as client:
        _print_section(
            "SEARCH",
            _body(await client.call_tool("search", {"query": "customers", "limit": 20})),
        )
        _print_section(
            "DIRECTORY TREE",
            _body(await client.call_tool("get_directory_tree", {})),
        )
        _print_section(
            "SQL TREE",
            _body(await client.call_tool("get_sql_tree", {"target": "sushi.customers"})),
        )
        _print_section(
            "SQL QUERY",
            _body(await client.call_tool("get_query", {"target": "sushi.customers"})),
        )
        _print_section(
            "QUERY AT LINES",
            _body(
                await client.call_tool(
                    "get_query_at_lines",
                    {"file_path": "models/customers.sql", "start_line": 12},
                )
            ),
        )
        _print_section(
            "SQL QUERY CTE",
            _body(
                await client.call_tool(
                    "get_query",
                    {"target": "models/customers.sql", "query_name": "cte"},
                )
            ),
        )
        _print_section(
            "MODEL DEPENDENCIES",
            _body(
                await client.call_tool(
                    "get_model_relations",
                    {"model_name": "sushi.customer_orders", "relation": "dependencies"},
                )
            ),
        )
        _print_section(
            "MODEL DEPENDENTS",
            _body(
                await client.call_tool(
                    "get_model_relations",
                    {"model_name": "sushi.customers", "relation": "dependents"},
                )
            ),
        )
        _print_section(
            "COLUMN DEPENDENCIES",
            _body(
                await client.call_tool(
                    "get_column_relations",
                    {
                        "model_name": "sushi.customers",
                        "column_name": "cte.customer_id",
                        "relation": "dependencies",
                    },
                )
            ),
        )
        _print_section(
            "COLUMN DEPENDENTS",
            _body(
                await client.call_tool(
                    "get_column_relations",
                    {
                        "model_name": "sushi.customers",
                        "column_name": "cte.customer_id",
                        "relation": "dependents",
                        "include_tests": True,
                    },
                )
            ),
        )


def main() -> None:
    if not SUSHI_ROOT.is_dir():
        raise SystemExit(f"Missing {SUSHI_ROOT}")
    asyncio.run(_print_tools())


if __name__ == "__main__":
    main()
