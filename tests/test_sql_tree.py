from typing import cast

from sqlglot import exp, parse_one

from src.db import ProjectDB
from src.parse.column_lineage import _clause_nodes, _query_counts
from src.processor import ProjectProcessor
from src.sqlparse_mcp.sql_tree import get_sql_tree
from tests.conftest import FIXTURE_PROJECT


def test_sql_tree_by_model_name_lists_queries_with_counts() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "sushi.customers")
    finally:
        db.close()
    assert out == (
        "sushi.customers\n└── $ (3 select columns)\n    └── cte (4 select columns, 1 join)\n"
    )


def test_sql_tree_by_file_path() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "models/customers.sql")
    finally:
        db.close()
    assert out == (
        "sushi.customers\n└── $ (3 select columns)\n    └── cte (4 select columns, 1 join)\n"
    )


def test_sql_tree_nests_ctes_under_the_final_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "sushi.customer_status")
    finally:
        db.close()
    assert out == (
        "sushi.customer_status\n"
        "└── $ (2 select columns)\n"
        "    ├── base (2 select columns)\n"
        "    └── filtered (2 select columns, 1 where condition)\n"
    )


def test_sql_tree_counts_where_ands_and_one_group_by() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "sushi.customer_orders")
    finally:
        db.close()
    assert out == (
        "sushi.customer_orders\n"
        "└── $ (3 select columns, 1 join, 1 where condition, grouped by 3 columns)\n"
    )


def test_where_and_is_another_clause_and_group_by_is_one() -> None:
    select = cast(
        exp.Select,
        parse_one("SELECT a FROM t JOIN u ON t.a = u.a WHERE a = 1 AND b = 2 GROUP BY a, b"),
    )
    kinds = [kind for kind, _node in _clause_nodes(select)]
    assert kinds == ["join", "where", "where", "group"]
    assert _query_counts(select) == (1, 2, 1, 2)


def test_sql_tree_missing_target() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "missing.model")
    finally:
        db.close()
    assert out == "No model found."
