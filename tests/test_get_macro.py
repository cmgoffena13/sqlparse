from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.macro import get_macro
from tests.conftest import FIXTURE_PROJECT

_MACRO = (
    "L1 | {% macro cents_to_dollars(column) %}\n"
    "L2 |   {{ column }} / 100\n"
    "L3 | {% endmacro %}\n"
    "\n"
    "## Models\n"
    "\n"
    "  • sushi.customers\n"
)

_UNUSED_MACRO = "L4 | @macro()\nL5 | def identity(evaluator, expr):\nL6 |     return expr\n"


def test_get_macro_returns_the_named_macro_with_line_numbers() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        used = get_macro(db, "macros/cents_to_dollars.sql", "cents_to_dollars")
        unused = get_macro(db, "macros/identity.py", "identity")
        missing = get_macro(db, "macros/cents_to_dollars.sql", "missing")
    finally:
        db.close()
    assert used == _MACRO
    assert unused == _UNUSED_MACRO
    assert missing == "No macro found."
