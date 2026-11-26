from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model_utils import model_not_found_message
from src.sqlparse_mcp.query import get_query, get_query_schema, get_span_at_lines
from tests.conftest import FIXTURE_PROJECT

_FINAL = (
    "File: models/customers.sql\n"
    "\n"
    "L22 | SELECT\n"
    "L23 |   customer_id, -- Customer identifier\n"
    "L24 |   {{ cents_to_dollars('amount_cents') }} AS amount, /* Order amount in dollars */\n"
    "L25 |   status -- Customer status\n"
    "L26 | FROM cte\n"
    "\n"
    "## Macro Refs\n"
    "\n"
    "  • cents_to_dollars\n"
)

_cte = (
    "File: models/customers.sql\n"
    "\n"
    "L12 | WITH cte AS (\n"
    "L13 |   SELECT\n"
    "L14 |     s.customer_id,\n"
    "L15 |     o.customer_id,\n"
    "L16 |     s.status,\n"
    "L17 |     o.amount_cents\n"
    "L18 |   FROM raw.customers AS s\n"
    "L19 |   JOIN raw.orders AS o\n"
    "L20 |     ON s.customer_id = o.customer_id\n"
    "L21 | )\n"
)

_FINAL_SCHEMA = (
    "  • sushi.customers.customer_id INT NOT NULL UNIQUE\n"
    "  • sushi.customers.amount      DOUBLE\n"
    "  • sushi.customers.status      TEXT\n"
)

_CTE_SCHEMA = (
    "  • $cte.customer_id  INT\n"
    "  • $cte.customer_id  INT\n"
    "  • $cte.status       TEXT\n"
    "  • $cte.amount_cents INT\n"
)


_RENDERED_FINAL = (
    "File: models/customers.sql\n"
    "\n"
    "SELECT\n"
    '  "cte"."customer_id" AS "customer_id", /* Customer identifier */\n'
    '  "cte"."amount_cents" / 100 AS "amount", /* Order amount in dollars */\n'
    '  "cte"."status" AS "status" /* Customer status */\n'
    'FROM "cte" AS "cte"\n'
    "\n"
    "## Macros Rendered\n"
    "\n"
    "  • cents_to_dollars\n"
)

_RENDERED_CTE = (
    "File: models/customers.sql\n"
    "\n"
    "SELECT\n"
    '  "s"."customer_id" AS "customer_id",\n'
    '  "o"."customer_id" AS "customer_id",\n'
    '  "s"."status" AS "status",\n'
    '  "o"."amount_cents" AS "amount_cents"\n'
    'FROM "memory"."raw"."customers" AS "s"\n'
    'JOIN "memory"."raw"."orders" AS "o"\n'
    '  ON "o"."customer_id" = "s"."customer_id"\n'
)


def test_query_lists_the_final_select() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "sushi.customers", None)
    finally:
        db.close()
    assert out == _FINAL


def test_query_schema_lists_only_select_columns() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query_schema(db, "sushi.customer_orders", "$")
    finally:
        db.close()
    assert out.count(".customer_id") == 1
    assert ".order_id" in out
    assert ".status" in out
    assert len([line for line in out.splitlines() if line.startswith("  • ")]) == 3


def test_query_schema_lists_final_and_cte_columns() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        final = get_query_schema(db, "sushi.customers", None)
        cte = get_query_schema(db, "sushi.customers", "cte")
        query = get_query(db, "sushi.customers", None)
        query_cte = get_query(db, "sushi.customers", "cte")
    finally:
        db.close()
    assert final == _FINAL_SCHEMA
    assert cte == _CTE_SCHEMA
    assert "## Output Schema" not in query
    assert "## Output Schema" not in query_cte


def test_query_defaults_to_the_final_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        explicit = get_query(db, "sushi.customers", "$")
        defaulted = get_query(db, "sushi.customers", None)
    finally:
        db.close()
    assert defaulted == explicit == _FINAL


def test_query_render_expands_macros_without_file_lines() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        final = get_query(db, "sushi.customers", None, render=True)
        cte = get_query(db, "sushi.customers", "cte", render=True)
    finally:
        db.close()
    assert final == _RENDERED_FINAL
    assert cte == _RENDERED_CTE


def test_query_lists_the_cte() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "sushi.customers", "cte")
    finally:
        db.close()
    assert out == _cte


def test_query_missing_model_and_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing_model = get_query(db, "sushi.missing", None)
        missing_query = get_query(db, "sushi.customers", "missing")
        empty = get_query(db, "  ", None)
    finally:
        db.close()
    assert missing_model == model_not_found_message()
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
    assert by_model == _cte
    assert "Model:" not in by_model
    assert by_file == (
        "Model: sushi.customers\n"
        "\n"
        "L12 | WITH cte AS (\n"
        "L13 |   SELECT\n"
        "L14 |     s.customer_id,\n"
        "L15 |     o.customer_id,\n"
        "L16 |     s.status,\n"
        "L17 |     o.amount_cents\n"
        "L18 |   FROM raw.customers AS s\n"
        "L19 |   JOIN raw.orders AS o\n"
        "L20 |     ON s.customer_id = o.customer_id\n"
        "L21 | )\n"
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


def test_query_named_model_returns_the_config() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        by_name = get_query(db, "sushi.customers", "$CONFIG")
        by_file = get_query(db, "models/customers.sql", "$CONFIG")
        rendered = get_query(db, "sushi.customers", "$CONFIG", render=True)
        external = get_query(db, "raw.customers", "$CONFIG")
        python = get_query(db, "sushi.waiters", "$CONFIG")
    finally:
        db.close()
    config = (
        "L1 | MODEL (\n"
        "L2 |   name sushi.customers,\n"
        "L3 |   kind FULL,\n"
        "L4 |   audits [\n"
        "L5 |     not_null_customer_id,\n"
        "L6 |     unique_values(columns := (customer_id)),\n"
        "L7 |   ],\n"
        "L8 |   description 'Customer grain with order amounts'\n"
        "L9 | );\n"
    )
    assert by_name == f"File: models/customers.sql\n\n{config}"
    assert by_file == f"Model: sushi.customers\n\n{config}"
    assert rendered == by_name
    assert external == "$EXTERNAL"
    assert python == (
        "File: models/waiters.py\n"
        "\n"
        "L4  | @model(\n"
        'L5  |     "sushi.waiters",\n'
        'L6  |     kind="FULL",\n'
        "L7  |     columns={\n"
        'L8  |         "waiter_id": "int",\n'
        "L9  |     },\n"
        "L10 | )\n"
    )
    assert "## Output" not in by_name


_EXTERNAL_FINAL = "File: external_models.yaml\n\n$EXTERNAL\n"

_EXTERNAL_SCHEMA = "  • raw.customers.customer_id INT\n  • raw.customers.status      TEXT\n"


def test_query_external_model_has_no_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "raw.customers", None)
        rendered = get_query(db, "raw.customers", "$", render=True)
        schema = get_query_schema(db, "raw.customers", None)
        stored = db.connection.execute(
            """
            SELECT queries.rendered_sql
            FROM queries
            INNER JOIN models ON models.id = queries.model_id
            WHERE models.qualified_name = ?
              AND queries.name = ?
            """,
            ("memory.raw.customers", "$"),
        ).fetchone()
    finally:
        db.close()
    assert out == _EXTERNAL_FINAL
    assert rendered == _EXTERNAL_FINAL
    assert schema == _EXTERNAL_SCHEMA
    assert stored["rendered_sql"] is None


def test_query_python_model_has_no_sql_source() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_query(db, "sushi.waiters", "$")
    finally:
        db.close()
    assert out == "No SQL source for this query."


def test_span_at_lines_returns_the_containing_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        cte = get_span_at_lines(db, "models/customers.sql", 15)
        final = get_span_at_lines(db, "models/customers.sql", 24)
    finally:
        db.close()
    assert cte == _cte.replace(
        "File: models/customers.sql", "Model: sushi.customers\nQuery: $cte", 1
    )
    assert final == _FINAL.replace(
        "File: models/customers.sql", "Model: sushi.customers\nQuery: $", 1
    )


def test_span_at_lines_on_model_config_shows_the_config() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_span_at_lines(db, "models/customers.sql", 2, 4)
    finally:
        db.close()
    assert out == (
        "Model: sushi.customers\n"
        "Query: $CONFIG\n"
        "\n"
        "L1 | MODEL (\n"
        "L2 |   name sushi.customers,\n"
        "L3 |   kind FULL,\n"
        "L4 |   audits [\n"
        "L5 |     not_null_customer_id,\n"
        "L6 |     unique_values(columns := (customer_id)),\n"
        "L7 |   ],\n"
        "L8 |   description 'Customer grain with order amounts'\n"
        "L9 | );\n"
    )


def test_span_at_lines_lists_overlapping_query_names() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_span_at_lines(db, "models/customer_status.sql", 11, 16)
    finally:
        db.close()
    assert out == (
        "Multiple spans found:\n"
        "  • sushi.customer_status/$base L7-L12\n"
        "  • sushi.customer_status/$filtered L13-L19\n"
    )


def test_span_at_lines_uses_the_closest_query_beside_the_range() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_span_at_lines(db, "models/customers.sql", 11)
    finally:
        db.close()
    assert out == _cte.replace(
        "File: models/customers.sql", "Model: sushi.customers\nQuery: $cte", 1
    )


def test_span_at_lines_python_body_has_no_query() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing = get_span_at_lines(db, "models/missing.sql", 1)
        python_body = get_span_at_lines(db, "models/waiters.py", 12)
        blank = get_span_at_lines(db, " ", 1)
    finally:
        db.close()
    assert missing == "No model found."
    assert python_body == "No query found."
    assert blank == "No file path given; pass a file path."


def test_span_at_lines_returns_an_audit() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_span_at_lines(db, "audits/not_null_customer_id.sql", 6)
    finally:
        db.close()
    assert out == (
        "Audit: not_null_customer_id\n"
        "\n"
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
        "  • sushi.customers\n"
    )
    assert "## Output" not in out


def test_span_at_lines_returns_a_macro() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        jinja = get_span_at_lines(db, "macros/cents_to_dollars.sql", 2)
        python = get_span_at_lines(db, "macros/identity.py", 5)
    finally:
        db.close()
    assert jinja == (
        "Macro: cents_to_dollars\n"
        "Type: jinja\n"
        "\n"
        "L1 | {% macro cents_to_dollars(column) %}\n"
        "L2 |   {{ column }} / 100\n"
        "L3 | {% endmacro %}\n"
        "\n"
        "## Models\n"
        "\n"
        "  • sushi.customers/$\n"
    )
    assert python == (
        "Macro: identity\n"
        "Type: python\n"
        "\n"
        "L4 | @macro()\n"
        "L5 | def identity(evaluator, expr):\n"
        "L6 |     return expr\n"
    )
    assert "## Output" not in jinja
    assert "## Models" not in python
    assert "## Output" not in python


def test_span_at_lines_returns_a_test() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_span_at_lines(db, "tests/test_orders.yaml", 6)
    finally:
        db.close()
    assert out == (
        "Test: test_orders_exist\n"
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
    assert "## Output" not in out


def test_span_at_lines_keeps_audits_macros_and_tests_in_their_directories() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        missing_audit = get_span_at_lines(db, "audits/missing.sql", 1)
        missing_macro = get_span_at_lines(db, "macros/missing.sql", 1)
        missing_test = get_span_at_lines(db, "tests/missing.yaml", 1)
        nested_audit = get_span_at_lines(db, "team/audits/missing.sql", 1)
        nested_macro = get_span_at_lines(db, "team/macros/missing.py", 1)
        nested_test = get_span_at_lines(db, "team/tests/missing.yaml", 1)
        named_like_audit = get_span_at_lines(db, "models/audits.sql", 1)
        named_like_test = get_span_at_lines(db, "models/tests.sql", 1)
        model = get_span_at_lines(db, "models/customers.sql", 12)
    finally:
        db.close()
    assert missing_audit == "No audit found."
    assert missing_macro == "No macro found."
    assert missing_test == "No test found."
    assert nested_audit == "No audit found."
    assert nested_macro == "No macro found."
    assert nested_test == "No test found."
    assert named_like_audit == "No model found."
    assert named_like_test == "No model found."
    assert model.startswith("Model: sushi.customers\nQuery: $cte")
