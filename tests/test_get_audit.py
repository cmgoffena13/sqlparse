from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.audit import get_audit
from tests.conftest import FIXTURE_PROJECT

_AUDIT = (
    "L1 | AUDIT (\n"
    "L2 |   name not_null_customer_id\n"
    "L3 | );\n"
    "L4 | \n"
    "L5 | SELECT *\n"
    "L6 | FROM @this_model\n"
    "L7 | WHERE customer_id IS NULL\n"
    "\n"
    "## Models\n"
    "\n"
    "  • memory.sushi.customers\n"
)


def test_get_audit_returns_the_named_audit_with_line_numbers() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_audit(db, "audits/not_null_customer_id.sql", "not_null_customer_id")
        missing = get_audit(db, "audits/not_null_customer_id.sql", "missing")
    finally:
        db.close()
    assert out == _AUDIT
    assert missing == "No audit found."
