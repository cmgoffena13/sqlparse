import asyncio
import time
from pathlib import Path

from tests.conftest import memory_fqn

CUSTOMERS_FQN = memory_fqn("sushi.customers")

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from src.db import ProjectDB
from src.sqlparse_mcp.session_stats import (
    FileToolStats,
    _record,
    _spawn,
    format_session_stats_report,
    load_session_files,
    record_tool_call,
)
from tests.conftest import FIXTURE_PROJECT


def _text(result: CallToolResult) -> str:
    assert result.is_error is False
    assert isinstance(result.data, str)
    return result.data


def _seed(root: Path, paths: dict[str, str]) -> None:
    (root / "models").mkdir(parents=True)
    db = ProjectDB(root)
    db.connection.execute("INSERT INTO projects (id, name) VALUES (1, 'sushi')")
    db.connection.execute(
        """
        INSERT INTO project_gateways (
            id, project_id, name, catalog_name, dialect, is_default, snapshot_hash
        )
        VALUES (1, 1, 'local', 'memory', NULL, TRUE, 'hash')
        """
    )
    for file_id, path in enumerate(paths, start=1):
        (root / path).write_text(paths[path], encoding="utf-8")
        db.connection.execute(
            """
            INSERT INTO files (
                id, name, path, normalized_path, language, content_hash,
                mtime_ns, size_bytes, line_count, is_test, is_config
            )
            VALUES (?, ?, ?, ?, 'sql', 'hash', 0, 1, 1, 0, 0)
            """,
            (file_id, Path(path).name, path, path),
        )
    db.connection.execute(
        """
        INSERT INTO models (
            id, file_id, gateway_id, dialect, schema_name, qualified_name, kind,
            is_blueprint, config_start_line, config_end_line, snapshot_hash,
            data_hash, metadata_hash, direct_dependencies_count, direct_dependents_count
        )
        VALUES (
            1, 1, 1, 'duckdb', 'sushi', ?, 'FULL', FALSE, 1, 1, 'hash',
            'data', 'meta', 0, 0
        )
        """,
        (CUSTOMERS_FQN,),
    )
    db.connection.commit()
    db.close()


def _record_call(
    root: Path,
    session_id: str,
    file_path: str,
    tool: str,
    qualified_name: str,
    output: str,
    file_chars: int,
) -> None:
    record_tool_call(root, session_id, file_path, tool, qualified_name, output, file_chars)


def _wait_path(root: Path, file_path: str, calls: int) -> list[FileToolStats]:
    found: list[FileToolStats] = []
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        found = [item for item in load_session_files(root) if item.file_path == file_path]
        if sum(item.tool_call_count for item in found) >= calls:
            break
        time.sleep(0.01)
    return found


def test_record_groups_calls_by_file(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        {"models/customers.sql": "SELECT 1\n", "models/orders.sql": "SELECT 2\n"},
    )
    _record_call(tmp_path, "window-a", "models/customers.sql", "get_model", "", "overview", 40)
    _record_call(
        tmp_path,
        "window-a",
        "models/customers.sql",
        "get_query",
        "memory.sushi.customers/$",
        "symbol-body",
        40,
    )
    _record_call(
        tmp_path,
        "window-a",
        "models/orders.sql",
        "get_span_at_lines",
        "",
        "other",
        8,
    )

    files = {item.file_path: item for item in load_session_files(tmp_path)}
    target = files["models/customers.sql"]
    assert target.session_id == "window-a"
    assert target.current_file_tokens == 10
    assert target.tool_call_count == 2
    assert target.output_tokens == len("overview") // 4 + len("symbol-body") // 4
    assert [
        (item.tool, item.tool_symbol_qualified_name, item.output_tokens, item.file_tokens)
        for item in target.outputs
    ] == [
        ("get_model", None, len("overview") // 4, 10),
        ("get_query", "memory.sushi.customers/$", len("symbol-body") // 4, 10),
    ]
    assert files["models/orders.sql"].tool_call_count == 1


def test_format_session_stats_report_lists_sessions(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        {"models/customers.sql": "SELECT 1\n", "models/orders.sql": "SELECT 2\n"},
    )
    start_a = int(time.time()) - 120
    start_b = int(time.time()) - 60
    db = ProjectDB(tmp_path)
    db.connection.execute(
        "INSERT INTO session_stats (session_id, session_start_time) VALUES (?, ?), (?, ?)",
        ("window-b", start_b, "window-a", start_a),
    )
    db.connection.commit()
    db.close()
    _record_call(
        tmp_path, "window-a", "models/customers.sql", "get_model", CUSTOMERS_FQN, "overview", 40
    )
    _record_call(
        tmp_path,
        "window-a",
        "models/customers.sql",
        "get_query",
        "memory.sushi.customers/$",
        "symbol-body",
        80,
    )
    _record_call(tmp_path, "window-a", "models/orders.sql", "get_audit", "not_null", "xyzw", 8)
    _record_call(tmp_path, "window-b", "models/orders.sql", "get_audit", "not_null", "other", 8)

    report = format_session_stats_report(tmp_path)
    started_a = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_a))
    started_b = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_b))
    header = (
        "| file | tool_calls | latest_file_tokens | if_file_read_every_time | "
        "tool_output_tokens | tokens_saved |"
    )
    rule = "| --- | --- | --- | --- | --- | --- |"
    assert (
        "Tokens saved: low = vs reading each file once; "
        "high = vs re-reading it on every tool call.\n"
    ) in report
    assert (
        f"window-a - {started_a}\n"
        f"{header}\n"
        f"{rule}\n"
        "| models/customers.sql | 2 | 20 | 30 | 4 | 16..26 |\n"
        "| models/orders.sql | 1 | 2 | 2 | 1 | 1 |\n"
        "| 2 files | 3 | 22 | 32 | 5 | 17..27 |\n"
    ) in report
    assert (
        f"window-b - {started_b}\n"
        f"{header}\n"
        f"{rule}\n"
        "| models/orders.sql | 1 | 2 | 2 | 1 | 1 |\n"
        "| 1 file | 1 | 2 | 2 | 1 | 1 |\n"
    ) in report
    assert report.index("window-b") < report.index("window-a")


def test_format_session_stats_report_empty(tmp_path: Path) -> None:
    assert format_session_stats_report(tmp_path) == "No session stats recorded.\n"
    _seed(tmp_path, {"models/customers.sql": "SELECT 1\n"})
    assert format_session_stats_report(tmp_path) == "No session stats recorded.\n"
    assert load_session_files(tmp_path) == []


def test_record_keeps_each_call_file_size(tmp_path: Path) -> None:
    _seed(tmp_path, {"models/customers.sql": "SELECT 1\n"})
    _record_call(
        tmp_path, "window-a", "models/customers.sql", "get_model", CUSTOMERS_FQN, "first", 10
    )
    _record_call(
        tmp_path, "window-a", "models/customers.sql", "get_model", CUSTOMERS_FQN, "second", 25
    )
    target = load_session_files(tmp_path)[0]
    assert target.current_file_tokens == 25 // 4
    assert [item.file_tokens for item in target.outputs] == [10 // 4, 25 // 4]


def test_record_separates_sessions_and_workspaces(tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    _seed(one, {"models/customers.sql": "SELECT 1\n"})
    _seed(two, {"models/customers.sql": "SELECT 1\n"})
    _record_call(one, "window-a", "models/customers.sql", "get_model", CUSTOMERS_FQN, "a", 40)
    _record_call(one, "window-b", "models/customers.sql", "get_model", CUSTOMERS_FQN, "b", 80)
    rows = {
        (item.session_id, item.file_path, item.current_file_tokens)
        for item in load_session_files(one)
    }
    assert rows == {
        ("window-a", "models/customers.sql", 10),
        ("window-b", "models/customers.sql", 20),
    }
    assert load_session_files(two) == []


def test_record_deletes_sessions_older_than_a_week(tmp_path: Path) -> None:
    _seed(tmp_path, {"models/customers.sql": "SELECT 1\n"})
    started = int(time.time())
    week = 7 * 24 * 60 * 60
    db = ProjectDB(tmp_path)
    file_id = int(
        db.connection.execute(
            "SELECT id FROM files WHERE path = ?",
            ("models/customers.sql",),
        ).fetchone()["id"]
    )
    for session_id, start in (("old", started - week - 1), ("recent", started - week + 60)):
        db.connection.execute(
            "INSERT INTO session_stats (session_id, session_start_time) VALUES (?, ?)",
            (session_id, start),
        )
        session_row_id = int(
            db.connection.execute(
                "SELECT id FROM session_stats WHERE session_id = ?",
                (session_id,),
            ).fetchone()["id"]
        )
        cursor = db.connection.execute(
            """
            INSERT INTO session_stats_files (
                session_id, file_id, current_file_tokens, tool_call_count, output_tokens
            )
            VALUES (?, ?, 4, 1, 2)
            """,
            (session_row_id, file_id),
        )
        db.connection.execute(
            """
            INSERT INTO session_stats_tool_outputs (
                session_file_id, tool, tool_symbol_qualified_name, output_tokens, file_tokens
            )
            VALUES (?, 'get_model', ?, 2, 4)
            """,
            (cursor.lastrowid, CUSTOMERS_FQN),
        )
    db.connection.commit()
    db.close()

    _record_call(tmp_path, "fresh", "models/customers.sql", "get_model", CUSTOMERS_FQN, "now", 40)
    assert {item.session_id for item in load_session_files(tmp_path)} == {"recent", "fresh"}


def test_record_resolves_a_model_name_and_skips_a_missing_one(tmp_path: Path) -> None:
    _seed(tmp_path, {"models/customers.sql": "SELECT 1\n"})
    source = (tmp_path / "models" / "customers.sql").read_text(encoding="utf-8")
    _spawn(tmp_path, "window-a", "get_model", CUSTOMERS_FQN, CUSTOMERS_FQN, "symbol")
    _spawn(tmp_path, "window-a", "get_model", "missing", "missing.model", "nope")
    recorded = _wait_path(tmp_path, "models/customers.sql", 1)
    assert len(recorded) == 1
    assert recorded[0].current_file_tokens == len(source) // 4
    assert recorded[0].outputs[0].tool_symbol_qualified_name == CUSTOMERS_FQN
    time.sleep(0.05)
    assert load_session_files(tmp_path) == recorded


def test_record_skips_a_file_that_is_not_on_disk(tmp_path: Path) -> None:
    _seed(tmp_path, {"models/customers.sql": "SELECT 1\n"})
    (tmp_path / "models" / "customers.sql").unlink()
    _record(tmp_path, "window-a", "get_model", CUSTOMERS_FQN, "models/customers.sql", "body")
    assert load_session_files(tmp_path) == []


def test_client_records_only_the_token_saving_tools(
    mcp_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQLPARSE_WORKSPACE", str(FIXTURE_PROJECT))
    customers = (FIXTURE_PROJECT / "models" / "customers.sql").read_text(encoding="utf-8")

    async def run() -> None:
        async with mcp_client:
            model = _text(await mcp_client.call_tool("get_model", {"target": "sushi.customers"}))
            query = _text(
                await mcp_client.call_tool(
                    "get_query",
                    {"target": "sushi.customers", "query_name": "$"},
                )
            )
            span = _text(
                await mcp_client.call_tool(
                    "get_span_at_lines",
                    {"file_path": "models/orders.sql", "start_line": 1},
                )
            )
            test = _text(
                await mcp_client.call_tool(
                    "get_test",
                    {"file_path": "tests/test_orders.yaml", "test_name": "test_orders_exist"},
                )
            )
            macro = _text(
                await mcp_client.call_tool(
                    "get_macro",
                    {"file_path": "macros/cents_to_dollars.sql", "macro_name": "cents_to_dollars"},
                )
            )
            audit = _text(
                await mcp_client.call_tool(
                    "get_audit",
                    {
                        "file_path": "audits/not_null_customer_id.sql",
                        "audit_name": "not_null_customer_id",
                    },
                )
            )
            await mcp_client.call_tool("search", {"query": "customers", "limit": 5})
            await mcp_client.call_tool(
                "get_model_relations",
                {"model_name": "sushi.customers", "relation": "dependents"},
            )
            customers_rows = _wait_path(FIXTURE_PROJECT, "models/customers.sql", 2)
            orders_rows = _wait_path(FIXTURE_PROJECT, "models/orders.sql", 1)
            test_rows = _wait_path(FIXTURE_PROJECT, "tests/test_orders.yaml", 1)
            macro_rows = _wait_path(FIXTURE_PROJECT, "macros/cents_to_dollars.sql", 1)
            audit_rows = _wait_path(FIXTURE_PROJECT, "audits/not_null_customer_id.sql", 1)

        recorded = customers_rows + orders_rows + test_rows + macro_rows + audit_rows
        outputs = [call for item in recorded for call in item.outputs]
        assert sum(item.tool_call_count for item in recorded) == 6
        assert {item.current_file_tokens for item in customers_rows} == {len(customers) // 4}
        assert {(call.tool, call.tool_symbol_qualified_name) for call in outputs} == {
            ("get_model", "sushi.customers"),
            ("get_query", "sushi.customers/$"),
            ("get_span_at_lines", None),
            ("get_test", "test_orders_exist"),
            ("get_macro", "cents_to_dollars"),
            ("get_audit", "not_null_customer_id"),
        }
        assert sum(call.output_tokens for call in outputs) == (
            len(model) // 4
            + len(query) // 4
            + len(span) // 4
            + len(test) // 4
            + len(macro) // 4
            + len(audit) // 4
        )

    asyncio.run(run())
