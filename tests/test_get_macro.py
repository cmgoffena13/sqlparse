from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.macro import get_macro
from tests.conftest import FIXTURE_PROJECT

_MACRO = (
    "Type: jinja\n"
    "\n"
    "L1 | {% macro cents_to_dollars(column) %}\n"
    "L2 |   {{ column }} / 100\n"
    "L3 | {% endmacro %}\n"
)

_MACRO_WITH_SITES = (
    "Type: jinja\n"
    "\n"
    "L1 | {% macro cents_to_dollars(column) %}\n"
    "L2 |   {{ column }} / 100\n"
    "L3 | {% endmacro %}\n"
    "\n"
    "## Model Queries\n"
    "\n"
    "  • sushi.customers/$\n"
)

_UNUSED_MACRO = (
    "Type: python\n\nL4 | @macro()\nL5 | def identity(evaluator, expr):\nL6 |     return expr\n"
)


def test_get_macro_returns_the_named_macro_with_line_numbers() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        used = get_macro(db, "macros/cents_to_dollars.sql", "cents_to_dollars")
        with_sites = get_macro(
            db, "macros/cents_to_dollars.sql", "cents_to_dollars", include_call_sites=True
        )
        unused = get_macro(db, "macros/identity.py", "identity")
        missing = get_macro(db, "macros/cents_to_dollars.sql", "missing")
    finally:
        db.close()
    assert used == _MACRO
    assert with_sites == _MACRO_WITH_SITES
    assert unused == _UNUSED_MACRO
    assert missing == "No macro found."
