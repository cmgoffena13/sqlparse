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


def test_search_finds_models_queries_and_columns() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "customers", limit=30)
    finally:
        db.close()
    assert "models" in out
    assert "sushi.customers" in out
    assert "queries" in out
    assert "sushi.customers / cte" in out
    assert "columns" in out
    assert "raw.customers.customer_id" in out or "customer_id" in out


def test_search_cte_name_includes_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "filtered", limit=20)
    finally:
        db.close()
    assert "sushi.customer_status / filtered" in out


def test_search_column_prefers_smart_identifier() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = search(db, "amount_cents", limit=20)
    finally:
        db.close()
    assert "sushi.customers / cte / raw.orders.amount_cents" in out
