from sqlglot import exp

from src.db import ProjectDB
from src.parse.column_lineage import _ref_kind
from src.processor import ProjectProcessor
from src.sqlparse_mcp.column_relations import get_column_relations
from tests.conftest import FIXTURE_PROJECT


def test_ref_kind_reserves_alias_for_a_renamed_column() -> None:
    column = exp.column("customer_id", table="s")
    calculated = exp.alias_(exp.Literal.number(1), "amount")
    assert _ref_kind(column) == "select"
    assert _ref_kind(exp.alias_(column, "customer_id")) == "select"
    assert _ref_kind(exp.alias_(column.copy(), "id")) == "alias"
    assert _ref_kind(calculated) == "expression"


def test_column_relations_dependencies_groups_by_model_and_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            None,
            "$cte.customer_id",
            "dependencies",
        )
    finally:
        db.close()
    assert out == (
        "sushi.customers/$cte/raw.customers.customer_id (J, S, M)\n"
        "└── raw.customers/$EXTERNAL/customer_id\n"
    )


def test_column_relations_marks_external_source_models() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            "cte",
            "raw.orders.amount_cents",
            "dependencies",
        )
    finally:
        db.close()
    assert "raw.orders/$EXTERNAL" in out
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
            "$cte.customer_id",
            "dependents",
        )
    finally:
        db.close()
    assert out == (
        "sushi.orders/$/sushi.customers.customer_id (J, M)\n"
        "└── sushi.customer_orders/$/sushi.customers.customer_id (J, G, S, M)\n"
    )


def test_column_relations_dependents_include_tests_when_requested() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "sushi.customers",
            "$",
            "$cte.customer_id",
            "dependents",
            include_tests=True,
        )
    finally:
        db.close()
    assert (
        "sushi.orders/$/sushi.customers.customer_id (J, M)\n"
        "├── tests/test_orders.yaml\n"
        "│   • test_orders_exist\n"
        "│   • test_orders_csv\n"
        "│   • test_orders_query\n"
        "└── sushi.customer_orders/$/sushi.customers.customer_id (J, G, S, M)\n"
    ) in out
    assert "## Tests" not in out


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


def test_column_relations_customer_status_walks_each_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        final = get_column_relations(
            db,
            "sushi.customer_status",
            "$",
            "$filtered.customer_id",
            "dependencies",
        )
        filtered = get_column_relations(
            db,
            "sushi.customer_status",
            "filtered",
            "$base.customer_id",
            "dependencies",
        )
        base = get_column_relations(
            db,
            "sushi.customer_status",
            "base",
            "raw.customers.id",
            "dependencies",
        )
    finally:
        db.close()
    assert final == (
        "sushi.customer_status/$filtered/$base.customer_id (A)\n"
        "└── sushi.customer_status/$base/raw.customers.id (A, M)\n"
        "    └── raw.customers/$EXTERNAL/customer_id\n"
    )
    assert filtered == (
        "sushi.customer_status/$base/raw.customers.id (A, M)\n"
        "└── raw.customers/$EXTERNAL/customer_id\n"
    )
    assert base == ("raw.customers/$EXTERNAL/customer_id\n")


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
    assert bare == "No column found."
    assert "sushi.customers/$/$cte.customer_id (S)" in join_col
    assert "sushi.customers/$cte/raw.customers.customer_id (J, S, M)" in join_col


def test_column_relations_page_past_the_end() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing = get_column_relations(
            db,
            "sushi.customers",
            None,
            "$cte.customer_id",
            "dependencies",
            page=2,
        )
        invalid = get_column_relations(
            db,
            "sushi.customers",
            None,
            "$cte.customer_id",
            "dependencies",
            page=0,
        )
    finally:
        db.close()
    assert missing == "No more dependencies; page 2 is past 1."
    assert invalid == "Invalid page; pass page >= 1."
