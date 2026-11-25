from pathlib import Path

from sqlglot import exp

from src.db import ProjectDB
from src.parse.column_lineage import _ref_kind
from src.parse.sqlmesh_utils import column_label
from src.processor import ProjectProcessor
from src.sqlparse_mcp.column_relations import (
    _column_parts_from_qn,
    get_column_relations,
)
from tests.conftest import FIXTURE_PROJECT, memory_fqn

CUSTOMERS_FQN = memory_fqn("sushi.customers")
CUSTOMER_ORDERS_FQN = memory_fqn("sushi.customer_orders")
ORDERS_FQN = memory_fqn("sushi.orders")
RAW_CUSTOMERS_FQN = memory_fqn("raw.customers")
CUSTOMERS = memory_fqn("sushi.customers")
CUSTOMER_ORDERS = memory_fqn("sushi.customer_orders")
ORDERS = memory_fqn("sushi.orders")
RAW_CUSTOMERS = memory_fqn("raw.customers")
RAW_ORDERS = memory_fqn("raw.orders")
CUSTOMER_STATUS = memory_fqn("sushi.customer_status")

SHOP_COLUMN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "shop_column_project"
EXT_ORDERS = memory_fqn("ext_shop.orders")
ORDERS_CLEAN = memory_fqn("shop.orders_clean")
DAILY = memory_fqn("shop.daily")


def test_column_parts_from_qn_splits_label_tail() -> None:
    assert _column_parts_from_qn(
        f"{CUSTOMERS_FQN}/$cte/{column_label(RAW_CUSTOMERS_FQN, 'customer_id', 'duckdb')}"
    ) == (
        "memory.raw.customers",
        "customer_id",
    )
    assert _column_parts_from_qn(
        f"{RAW_CUSTOMERS_FQN}/$/{column_label(None, 'customer_id', 'duckdb')}"
    ) == (None, "customer_id")


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
            "memory.sushi.customers",
            None,
            "$cte.customer_id",
            "dependencies",
        )
    finally:
        db.close()
    assert out == (
        f"{CUSTOMERS}/$cte/{RAW_CUSTOMERS}.customer_id (J, S, M)\n"
        f"└── {RAW_CUSTOMERS}/$EXTERNAL/customer_id\n"
    )


def test_column_relations_marks_external_source_models() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "memory.sushi.customers",
            "cte",
            "memory.raw.orders.amount_cents",
            "dependencies",
        )
    finally:
        db.close()
    assert f"{RAW_ORDERS}/$EXTERNAL" in out
    assert f"{RAW_ORDERS}\n" not in out


def test_column_relations_dependents_leave_external_models_unmarked() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "memory.raw.orders",
            "$",
            "amount_cents",
            "dependents",
        )
    finally:
        db.close()
    assert CUSTOMERS in out
    assert "(EXTERNAL)" not in out


def test_column_relations_dependents_include_downstream_models() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "memory.sushi.customers",
            "$",
            "$cte.customer_id",
            "dependents",
        )
    finally:
        db.close()
    assert out == (
        f"{ORDERS}/$/{CUSTOMERS}.customer_id (J, M)\n"
        f"└── {CUSTOMER_ORDERS}/$/{CUSTOMERS}.customer_id (J, G, S, M)\n"
    )


def test_column_relations_dependents_include_tests_when_requested() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "memory.sushi.customers",
            "$",
            "$cte.customer_id",
            "dependents",
            include_tests=True,
        )
    finally:
        db.close()
    assert (
        f"{ORDERS}/$/{CUSTOMERS}.customer_id (J, M)\n"
        "├── tests/test_orders.yaml\n"
        "│   • test_orders_exist\n"
        "│   • test_orders_csv\n"
        "│   • test_orders_query\n"
        f"└── {CUSTOMER_ORDERS}/$/{CUSTOMERS}.customer_id (J, G, S, M)\n"
    ) in out
    assert "## Tests" not in out


def test_column_relations_missing_column() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_column_relations(
            db,
            "memory.sushi.customers",
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
            "memory.sushi.customer_status",
            "$",
            "$filtered.customer_id",
            "dependencies",
        )
        filtered = get_column_relations(
            db,
            "memory.sushi.customer_status",
            "filtered",
            "$base.customer_id",
            "dependencies",
        )
        base = get_column_relations(
            db,
            "memory.sushi.customer_status",
            "base",
            "memory.raw.customers.id",
            "dependencies",
        )
    finally:
        db.close()
    assert final == (
        f"{CUSTOMER_STATUS}/$filtered/$base.customer_id (A)\n"
        f"└── {CUSTOMER_STATUS}/$base/{RAW_CUSTOMERS}.id (A, M)\n"
        f"    └── {RAW_CUSTOMERS}/$EXTERNAL/customer_id\n"
    )
    assert filtered == (
        f"{CUSTOMER_STATUS}/$base/{RAW_CUSTOMERS}.id (A, M)\n"
        f"└── {RAW_CUSTOMERS}/$EXTERNAL/customer_id\n"
    )
    assert base == (f"{RAW_CUSTOMERS}/$EXTERNAL/customer_id\n")


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
        unquoted = get_column_relations(
            db,
            "sushi.customer_orders",
            "$",
            "sushi.customers.customer_id",
            "dependencies",
        )
        join_col = get_column_relations(
            db,
            "memory.sushi.customer_orders",
            "$",
            "memory.sushi.customers.customer_id",
            "dependencies",
        )
    finally:
        db.close()
    assert bare == join_col
    assert unquoted == join_col
    assert f"{CUSTOMERS}/$/$cte.customer_id (S)" in join_col
    assert f"{CUSTOMERS}/$cte/{RAW_CUSTOMERS}.customer_id (J, S, M)" in join_col


def test_column_relations_page_past_the_end() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing = get_column_relations(
            db,
            "memory.sushi.customers",
            None,
            "$cte.customer_id",
            "dependents",
            page=2,
        )
    finally:
        db.close()
    assert missing.startswith("No more dependents")


def test_column_relations_accepts_get_query_model_qualified_names() -> None:
    db = ProjectDB(SHOP_COLUMN_FIXTURE)
    try:
        ProjectProcessor(db, SHOP_COLUMN_FIXTURE).process(full=True)
        bare = get_column_relations(db, ORDERS_CLEAN, "$", "event_date_et", "dependencies")
        model_qualified = get_column_relations(
            db, ORDERS_CLEAN, "$", f"{ORDERS_CLEAN}.event_date_et", "dependencies"
        )
        source_original = get_column_relations(
            db, ORDERS_CLEAN, "$", f"{EXT_ORDERS}.event_date", "dependencies"
        )
        source_aliased = get_column_relations(
            db, ORDERS_CLEAN, "$", f"{EXT_ORDERS}.event_date_et", "dependencies"
        )
        customer_id = get_column_relations(db, ORDERS_CLEAN, "$", "customer_id", "dependencies")
        order_id = get_column_relations(db, ORDERS_CLEAN, "$", "id", "dependencies")
        article = get_column_relations(db, ORDERS_CLEAN, "$", "article_section", "dependencies")
        external_bare = get_column_relations(db, EXT_ORDERS, "$", "event_date", "dependents")
        external_qualified = get_column_relations(
            db, EXT_ORDERS, "$", f"{EXT_ORDERS}.event_date", "dependents"
        )
        daily = get_column_relations(db, DAILY, "$", "event_date_et", "dependencies")
    finally:
        db.close()
    expected_event_date = f"{EXT_ORDERS}/$EXTERNAL/event_date\n"
    assert bare == expected_event_date
    assert model_qualified == expected_event_date
    assert source_original == expected_event_date
    assert source_aliased == expected_event_date
    assert customer_id == f"{EXT_ORDERS}/$EXTERNAL/user_id\n"
    assert order_id == f"{EXT_ORDERS}/$EXTERNAL/id\n"
    assert f"{EXT_ORDERS}/$EXTERNAL/event_data_article_section" in article
    assert f"{EXT_ORDERS}/$EXTERNAL/event" in article
    assert external_bare == external_qualified
    assert external_bare == (
        f"{ORDERS_CLEAN}/$/{EXT_ORDERS}.event_date (W, M)\n"
        f"{ORDERS_CLEAN}/$/{EXT_ORDERS}.event_date_et (A, M)\n"
        f"└── {DAILY}\n"
    )
    assert daily == (
        f"{ORDERS_CLEAN}/$/{EXT_ORDERS}.event_date_et (A, M)\n"
        f"└── {EXT_ORDERS}/$EXTERNAL/event_date\n"
    )
