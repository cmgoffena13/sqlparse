from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.column_relations import get_column_relations
from tests.conftest import FIXTURE_PROJECT


def test_column_relations_dependencies_groups_by_model_and_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            None,
            "customer_id",
            "dependencies",
        )
    finally:
        db.close()
    assert "sushi.customers" in out
    assert "sushi.customers (EXTERNAL)" not in out
    assert "  cte" in out
    assert "    • raw.customers.customer_id (EXTERNAL) (alias)" in out


def test_column_relations_marks_external_source_models() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            "cte",
            "amount_cents",
            "dependencies",
        )
    finally:
        db.close()
    assert "raw.orders (EXTERNAL)" in out
    assert "raw.orders\n" not in out


def test_column_relations_dependents_leave_external_models_unmarked() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "raw.orders",
            "$",
            "amount_cents",
            "dependents",
        )
    finally:
        db.close()
    assert "sushi.customers" in out
    assert "(EXTERNAL)" not in out


def test_column_relations_dependents_include_downstream_models() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            "$",
            "customer_id",
            "dependents",
        )
    finally:
        db.close()
    assert "sushi.customer_orders" in out
    assert "sushi.orders" in out
    assert "sushi.customers.customer_id (alias)" in out
    assert "sushi.customers.customer_id (join)" in out
    assert "## Tests" not in out


def test_column_relations_dependents_include_tests_when_requested() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            "$",
            "customer_id",
            "dependents",
            include_tests=True,
        )
    finally:
        db.close()
    assert "## Tests" in out
    assert "tests/test_orders.yaml" in out
    assert "• test_orders_exist" in out
    assert "• test_orders_csv" in out


def test_column_relations_missing_column() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            "$",
            "missing_col",
            "dependencies",
        )
    finally:
        db.close()
    assert out == "No column found."


def test_column_relations_join_column_uses_table_qualified_label() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        bare = get_column_relations(
            db,
            "sushi.customer_orders",
            "$",
            "customer_id",
            "dependencies",
        )
        join_col = get_column_relations(
            db,
            "sushi.customer_orders",
            "$",
            "sushi.customers.customer_id",
            "dependencies",
        )
    finally:
        db.close()
    assert "sushi.customers" in bare
    assert "• customer_id (alias)" in bare or "customer_id (alias)" in bare
    assert "sushi.customers" in join_col
    assert "join" in join_col
    assert bare != join_col
