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
        "Direct Model Dependents: 2\n"
        "Direct Model Dependencies: 2\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "L12-21 $cte (1J, 4S, 2M)\n"
        "L22-26 └── $ (1E, 3S)\n"
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
        "Direct Model Dependents: 2\n"
        "Direct Model Dependencies: 2\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "L12-21 $cte (1J, 4S, 2M)\n"
        "L22-26 └── $ (1E, 3S)\n"
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


def test_sql_tree_lists_ctes_above_the_final_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "sushi.customer_status")
    finally:
        db.close()
    assert out == (
        "File: models/customer_status.sql\n"
        "Kind: FULL\n"
        "Direct Model Dependents: 0\n"
        "Direct Model Dependencies: 1\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "L7-12  $base (1A, 2S, 1M)\n"
        "L13-19 ├── $filtered (1W, 1A, 2S)\n"
        "L20-23 └── $ (2S)\n"
    )


def test_sql_tree_counts_where_ands_and_one_group_by() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "sushi.customer_orders")
    finally:
        db.close()
    assert out == (
        "File: models/customer_orders.sql\n"
        "Kind: FULL\n"
        "Direct Model Dependents: 0\n"
        "Direct Model Dependencies: 2\n"
        "\n"
        "## SQL Tree\n"
        "\n"
        "L6-17 $ (1J, 1W, 3G, 3S, 2M)\n"
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


def test_query_counts_rolls_union_arm_stats_onto_set_operation() -> None:
    union = cast(
        exp.Union,
        parse_one(
            "SELECT a, b FROM t1 JOIN t2 ON t1.a = t2.a WHERE x = 1 AND y = 2 "
            "UNION ALL "
            "SELECT a, b FROM t3 WHERE z = 1"
        ),
    )
    assert _query_counts(union) == (2, 0, 0, 3, 1, 0, 0, 0)


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
        "Direct Model Dependents: 1\n"
        "Direct Model Dependencies: 2\n"
        "\n"
        "## SQL Tree\n"
    )
    assert (
        "## Test Refs\n"
        "\n"
        "tests/test_orders.yaml\n"
        "  • test_orders_exist\n"
        "  • test_orders_csv\n"
        "  • test_orders_query\n"
    ) in orders
    assert "## Test Refs" not in customers
    assert "Time Column:" not in customers
    assert "Direct Model Dependents: 2\nDirect Model Dependencies: 2\n" in customers


def test_sql_tree_missing_target() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model(db, "missing.model")
    finally:
        db.close()
    from src.sqlparse_mcp.model_utils import model_not_found_message

    assert out == model_not_found_message()
