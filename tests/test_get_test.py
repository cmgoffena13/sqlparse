from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model_test import get_test
from tests.conftest import FIXTURE_PROJECT

_EXIST = (
    "Model: sushi.orders\n"
    "\n"
    "L1  | test_orders_exist:\n"
    "L2  |   model: sushi.orders\n"
    "L3  |   inputs:\n"
    "L4  |     sushi.customers:\n"
    "L5  |       rows:\n"
    "L6  |         - customer_id: 1\n"
    "L7  |           status: active\n"
    "L8  |   outputs:\n"
    "L9  |     query:\n"
    "L10 |       rows:\n"
    "L11 |         - order_id: 1\n"
    "L12 |           customer_id: 1\n"
    "L13 | \n"
)


def test_get_test_returns_the_named_test_with_line_numbers() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_test(db, "tests/test_orders.yaml", "test_orders_exist")
        missing = get_test(db, "tests/test_orders.yaml", "missing")
    finally:
        db.close()
    assert out == _EXIST
    assert missing == "No test found."
