from src.db import ProjectDB
from src.parse.macro_utils import macro_call_lines, query_name_for_line
from src.processor import ProjectProcessor
from tests.conftest import FIXTURE_PROJECT


def test_macro_call_lines_finds_jinja_calls() -> None:
    text = "WITH cte AS (SELECT 1)\nSELECT {{ cents_to_dollars('x') }} AS amount\nFROM cte\n"
    assert macro_call_lines(text, "cents_to_dollars") == [2]
    assert macro_call_lines(text, "missing") == []


def test_query_name_for_line_picks_the_tightest_span() -> None:
    spans = [("$cte", 1, 10), ("$", 12, 20)]
    assert query_name_for_line(spans, 2) == "$cte"
    assert query_name_for_line(spans, 15) == "$"
    assert query_name_for_line(spans, 11) is None


def test_indexed_macro_call_maps_to_final_query_only() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        rows = list(
            db.connection.execute(
                """
                SELECT queries.name
                FROM model_macros
                INNER JOIN queries
                    ON queries.id = model_macros.query_id
                INNER JOIN models
                    ON models.id = model_macros.model_id
                WHERE model_macros.macro_name = 'cents_to_dollars'
                  AND models.qualified_name = 'memory.sushi.customers'
                """
            )
        )
    finally:
        db.close()
    assert [str(row["name"]) for row in rows] == ["$"]
