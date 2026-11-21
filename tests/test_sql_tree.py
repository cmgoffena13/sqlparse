from src.db import ProjectDB
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
    assert out == ("sushi.customers\n└── $ (3 columns)\n    └── cte (4 columns, 2 joins)\n")


def test_sql_tree_by_file_path() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "models/customers.sql")
    finally:
        db.close()
    assert out == ("sushi.customers\n└── $ (3 columns)\n    └── cte (4 columns, 2 joins)\n")


def test_sql_tree_nests_ctes_under_the_final_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "sushi.customer_status")
    finally:
        db.close()
    assert out == (
        "sushi.customer_status\n"
        "└── $ (2 columns)\n"
        "    ├── base (2 columns)\n"
        "    └── filtered (3 columns, 1 where)\n"
    )


def test_sql_tree_missing_target() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "missing.model")
    finally:
        db.close()
    assert out == "No model found."
