from typing import cast

from sqlglot import exp, parse_one

from src.db import ProjectDB
from src.parse.column_lineage import _clause_nodes, _query_counts
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model import get_model
from tests.conftest import FIXTURE_PROJECT


def test_sql_tree_by_model_name_lists_queries_with_counts() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "sushi.customers")
    finally:
        db.close()
    assert out == (
        "File: models/customers.sql\n"
        "Kind: FULL\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "$ (1E, 3S)\n"
        "└── $cte (1J, 4S)\n"
        "\n"
        "## Macro Refs\n"
        "\n"
        "macros/cents_to_dollars.sql\n"
        "  • cents_to_dollars\n"
        "\n"
        "## Audit Refs\n"
        "\n"
        "audits/not_null_customer_id.sql\n"
        "  • not_null_customer_id\n"
    )


def test_sql_tree_by_file_path() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "models/customers.sql")
    finally:
        db.close()
    assert out == (
        "Model: sushi.customers\n"
        "Kind: FULL\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "$ (1E, 3S)\n"
        "└── $cte (1J, 4S)\n"
        "\n"
        "## Macro Refs\n"
        "\n"
        "macros/cents_to_dollars.sql\n"
        "  • cents_to_dollars\n"
        "\n"
        "## Audit Refs\n"
        "\n"
        "audits/not_null_customer_id.sql\n"
        "  • not_null_customer_id\n"
    )


def test_sql_tree_nests_ctes_under_the_final_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "sushi.customer_status")
    finally:
        db.close()
    assert out == (
        "File: models/customer_status.sql\n"
        "Kind: FULL\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "$ (2S)\n"
        "├── $base (1A, 2S)\n"
        "└── $filtered (1W, 1A, 2S)\n"
    )


def test_sql_tree_counts_where_ands_and_one_group_by() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "sushi.customer_orders")
    finally:
        db.close()
    assert out == (
        "File: models/customer_orders.sql\nKind: FULL\n\n## SQL Tree\n\n$ (1J, 1W, 3G, 3S)\n"
    )


def test_where_and_is_another_clause_and_group_by_is_one() -> None:
    select = cast(
        exp.Select,
        parse_one("SELECT a FROM t JOIN u ON t.a = u.a WHERE a = 1 AND b = 2 GROUP BY a, b"),
    )
    kinds = [kind for kind, _node in _clause_nodes(select)]
    assert kinds == ["join", "where", "where", "group"]
    assert _query_counts(select) == (1, 0, 0, 2, 1, 2, 0, 0)


def test_query_counts_splits_select_kinds_and_having_order() -> None:
    select = cast(
        exp.Select,
        parse_one(
            "SELECT a, b AS id, a + 1 AS c FROM t "
            "GROUP BY a HAVING COUNT(*) > 1 AND x = 2 ORDER BY a, b"
        ),
    )
    assert _query_counts(select) == (3, 1, 1, 0, 0, 1, 2, 2)


def test_model_lists_kind_and_time_column_when_present() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        orders = get_model(db, "sushi.orders")
        customers = get_model(db, "sushi.customers")
    finally:
        db.close()
    assert orders.startswith(
        "File: models/orders.sql\n"
        "Kind: INCREMENTAL_BY_TIME_RANGE\n"
        "Time Column: order_id\n"
        "\n"
        "## SQL Tree\n"
    )
    assert "Time Column:" not in customers


def test_sql_tree_missing_target() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "missing.model")
    finally:
        db.close()
    assert out == "No model found."
