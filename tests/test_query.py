from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.query import get_query, get_query_at_lines
from tests.conftest import FIXTURE_PROJECT

_FINAL = (
    "File: models/customers.sql\n"
    "\n"
    "L19 | SELECT\n"
    "L20 |   customer_id, -- Customer identifier\n"
    "L21 |   {{ cents_to_dollars('amount_cents') }} AS amount, /* Order amount in dollars */\n"
    "L22 |   status -- Customer status\n"
    "L23 | FROM CTE\n"
    "\n"
    "## Output\n"
    "\n"
    "  • sushi.customers.customer_id INT NOT NULL\n"
    "  • sushi.customers.amount DOUBLE\n"
    "  • sushi.customers.status TEXT\n"
)

_CTE = (
    "File: models/customers.sql\n"
    "\n"
    "L9  | WITH CTE AS (\n"
    "L10 |   SELECT\n"
    "L11 |     s.customer_id,\n"
    "L12 |     o.customer_id,\n"
    "L13 |     s.status,\n"
    "L14 |     o.amount_cents\n"
    "L15 |   FROM raw.customers AS s\n"
    "L16 |   JOIN raw.orders AS o\n"
    "L17 |     ON s.customer_id = o.customer_id\n"
    "L18 | )\n"
    "\n"
    "## Output\n"
    "\n"
    "  • CTE.customer_id INT\n"
    "  • CTE.customer_id INT\n"
    "  • CTE.status TEXT\n"
    "  • CTE.amount_cents INT\n"
)


def test_query_lists_the_final_select() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "sushi.customers", None)
    finally:
        db.close()
    assert out == _FINAL


def test_query_defaults_to_the_final_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        explicit = get_query(db, "sushi.customers", "$")
        defaulted = get_query(db, "sushi.customers", None)
    finally:
        db.close()
    assert defaulted == explicit == _FINAL


def test_query_lists_the_cte() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "sushi.customers", "cte")
    finally:
        db.close()
    assert out == _CTE


def test_query_missing_model_and_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing_model = get_query(db, "sushi.missing", None)
        missing_query = get_query(db, "sushi.customers", "missing")
        empty = get_query(db, "  ", None)
    finally:
        db.close()
    assert missing_model == "No model found."
    assert missing_query == "No query found."
    assert empty == "No target given; pass a model name or file path."


def test_query_header_follows_the_input_kind() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        by_model = get_query(db, "sushi.customers", "cte")
        by_file = get_query(db, "models/customers.sql", "cte")
    finally:
        db.close()
    assert by_model == _CTE
    assert "Model:" not in by_model
    assert by_file == (
        "Model: sushi.customers\n"
        "\n"
        "L9  | WITH CTE AS (\n"
        "L10 |   SELECT\n"
        "L11 |     s.customer_id,\n"
        "L12 |     o.customer_id,\n"
        "L13 |     s.status,\n"
        "L14 |     o.amount_cents\n"
        "L15 |   FROM raw.customers AS s\n"
        "L16 |   JOIN raw.orders AS o\n"
        "L17 |     ON s.customer_id = o.customer_id\n"
        "L18 | )\n"
        "\n"
        "## Output\n"
        "\n"
        "  • CTE.customer_id INT\n"
        "  • CTE.customer_id INT\n"
        "  • CTE.status TEXT\n"
        "  • CTE.amount_cents INT\n"
    )
    assert "File:" not in by_file


def test_query_file_with_several_models_asks_for_a_name() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "external_models.yaml", None)
    finally:
        db.close()
    assert out == "File contains more than one model; pass a model name."


def test_query_python_model_has_no_sql_source() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "sushi.waiters", "$")
    finally:
        db.close()
    assert out == "No SQL source for this query."


def test_query_at_lines_returns_the_containing_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        cte = get_query_at_lines(db, "models/customers.sql", 12)
        final = get_query_at_lines(db, "models/customers.sql", 21)
    finally:
        db.close()
    assert cte == _CTE.replace(
        "File: models/customers.sql", "Model: sushi.customers\nQuery: CTE", 1
    )
    assert final == _FINAL.replace(
        "File: models/customers.sql", "Model: sushi.customers\nQuery: $", 1
    )


def test_query_at_lines_on_model_config_shows_the_config() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query_at_lines(db, "models/customers.sql", 2, 4)
    finally:
        db.close()
    assert out == (
        "Model: sushi.customers\n"
        "\n"
        "L1 | MODEL (\n"
        "L2 |   name sushi.customers,\n"
        "L3 |   kind FULL,\n"
        "L4 |   audits [not_null_customer_id],\n"
        "L5 |   description 'Customer grain with order amounts'\n"
        "L6 | );\n"
    )


def test_query_at_lines_lists_overlapping_query_names() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query_at_lines(db, "models/customer_status.sql", 11, 16)
    finally:
        db.close()
    assert out == (
        "Multiple queries found:\n"
        "  • sushi.customer_status/base L7-L12\n"
        "  • sushi.customer_status/filtered L13-L19\n"
    )


def test_query_at_lines_uses_the_closest_query_beside_the_range() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query_at_lines(db, "models/customers.sql", 8)
    finally:
        db.close()
    assert out == _CTE.replace(
        "File: models/customers.sql", "Model: sushi.customers\nQuery: CTE", 1
    )


def test_query_at_lines_python_body_has_no_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing = get_query_at_lines(db, "models/missing.sql", 1)
        python_body = get_query_at_lines(db, "models/waiters.py", 12)
        blank = get_query_at_lines(db, " ", 1)
    finally:
        db.close()
    assert missing == "No model found."
    assert python_body == "No query found."
    assert blank == "No file path given; pass a model file path."
