import re

from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.search import build_fts_query, search
from tests.conftest import FIXTURE_PROJECT


def test_build_fts_query_ors_each_word() -> None:
    assert build_fts_query("customers") == (
        "(model_name: customers OR query_name: customers OR column_name: customers)"
    )
    assert build_fts_query("amount status") == (
        "(model_name: amount OR query_name: amount OR column_name: amount) OR "
        "(model_name: status OR query_name: status OR column_name: status)"
    )
    assert build_fts_query("   ") == ""


def test_search_rejects_a_bare_dollar() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        exact = search(db, "$", 20)
        padded = search(db, "  $  ", 20)
        named = search(db, "$cte", 20)
    finally:
        db.close()
    assert exact == "`$` is too broad; be more specific."
    assert padded == exact
    assert named != exact


def test_search_finds_models_queries_and_columns() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "customers", limit=30)
    finally:
        db.close()
    assert "## Models\n\n" in out
    assert "sushi.customers" in out
    assert "## Queries\n\n" in out
    assert "sushi.customers / $cte" in out
    assert "sushi.customers / $" in out
    assert "## Columns\n\n" in out
    assert "sushi.customers / $ / cte.customer_id" in out
    assert "raw.customers / $EXTERNAL" in out
    assert "raw.customers / $EXTERNAL / status" in out
    assert "• raw.customers / $\n" not in out


def test_search_cte_name_includes_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "filtered", limit=20)
    finally:
        db.close()
    assert "sushi.customer_status / $filtered" in out


def test_search_column_prefers_smart_identifier() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "amount_cents", limit=20)
    finally:
        db.close()
    assert "sushi.customers / $cte / raw.orders.amount_cents" in out


def test_search_ranks_globally_across_sections() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "customers", limit=20)
    finally:
        db.close()
    ranks = [int(match) for match in re.findall(r"#(\d+)\s+•", out)]
    assert ranks
    assert len(ranks) <= 20
    assert sorted(ranks) == list(range(1, len(ranks) + 1))


def test_search_can_keep_any_combination_of_sections() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        models = search(db, "customers", 30, search_queries=False, search_columns=False)
        queries_and_columns = search(db, "customers", 30, search_models=False)
    finally:
        db.close()
    assert models.startswith("## Models\n")
    assert "## Queries" not in models
    assert "## Columns" not in models
    assert "sushi.customers" in models
    assert queries_and_columns.startswith("## Queries\n")
    assert "## Models" not in queries_and_columns
    assert "## Columns" in queries_and_columns
    assert "sushi.customers / $cte" in queries_and_columns
    ranks = [int(match) for match in re.findall(r"#(\d+)\s+•", queries_and_columns)]
    assert sorted(ranks) == list(range(1, len(ranks) + 1))
