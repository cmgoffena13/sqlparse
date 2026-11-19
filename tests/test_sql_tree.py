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
    assert out.startswith("sushi.customers\n")
    assert "• $ (3 columns)" in out
    assert "• cte (4 columns" in out
    assert "joins)" in out


def test_sql_tree_by_file_path() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "models/customers.sql")
    finally:
        db.close()
    assert out.startswith("sushi.customers\n")
    assert "• $ (3 columns)" in out


def test_sql_tree_missing_target() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_sql_tree(db, "missing.model")
    finally:
        db.close()
    assert out == "No model found."
