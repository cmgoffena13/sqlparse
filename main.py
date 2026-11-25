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
            "CATALOGS",
            _body(await client.call_tool("list_catalogs", {})),
        )
        _print_section(
            "SCHEMAS",
            _body(await client.call_tool("list_schemas", {})),
        )
        _print_section(
            "MODELS",
            _body(await client.call_tool("list_models", {"schema": "sushi"})),
        )
        _print_section(
            "SEARCH",
            _body(await client.call_tool("search", {"query": "customers", "limit": 20})),
        )
        _print_section(
            "DIRECTORY TREE",
            _body(await client.call_tool("get_directory_tree", {})),
        )
        _print_section(
            "MODEL",
            _body(await client.call_tool("get_model", {"target": "sushi.customers"})),
        )
        _print_section(
            "SQL QUERY",
            _body(
                await client.call_tool(
                    "get_query",
                    {"target": "sushi.customers", "render": True},
                )
            ),
        )
        _print_section(
            "MODEL CONFIG",
            _body(
                await client.call_tool(
                    "get_query",
                    {"target": "sushi.customers", "query_name": "$CONFIG"},
                )
            ),
        )
        _print_section(
            "EXTERNAL QUERY",
            _body(
                await client.call_tool(
                    "get_query",
                    {"target": "raw.customers", "query_name": "$"},
                )
            ),
        )
        _print_section(
            "EXTERNAL CONFIG",
            _body(
                await client.call_tool(
                    "get_query",
                    {"target": "raw.customers", "query_name": "$CONFIG"},
                )
            ),
        )
        _print_section(
            "SPAN",
            _body(
                await client.call_tool(
                    "get_span_at_lines",
                    {"file_path": "models/customers.sql", "start_line": 12},
                )
            ),
        )
        _print_section(
            "TEST",
            _body(
                await client.call_tool(
                    "get_test",
                    {"file_path": "tests/test_orders.yaml", "test_name": "test_orders_exist"},
                )
            ),
        )
        _print_section(
            "MACRO",
            _body(
                await client.call_tool(
                    "get_macro",
                    {"file_path": "macros/cents_to_dollars.sql", "macro_name": "cents_to_dollars"},
                )
            ),
        )
        _print_section(
            "AUDIT",
            _body(
                await client.call_tool(
                    "get_audit",
                    {
                        "file_path": "audits/not_null_customer_id.sql",
                        "audit_name": "not_null_customer_id",
                    },
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
                    {
                        "model_name": "sushi.customers",
                        "relation": "dependents",
                        "include_tests": True,
                    },
                )
            ),
        )
        _print_section(
            "STATUS COLUMN DEPENDENCIES",
            _body(
                await client.call_tool(
                    "get_column_relations",
                    {
                        "model_name": "sushi.customer_status",
                        "query_name": "$",
                        "column_name": "$filtered.customer_id",
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
                        "column_name": "$cte.customer_id",
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
