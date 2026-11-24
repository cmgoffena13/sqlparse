import shutil
from pathlib import Path

from sqlmesh.core.context import Context

from src.db import ProjectDB
from src.parse.column_lineage import (
    extract_model_column_references,
    extract_model_columns,
    extract_model_queries,
)
from src.parse.parse_only import install_parse_only_engine_support
from src.processor import ProjectProcessor
from tests.conftest import FIXTURE_PROJECT

UNION_CTE_MODEL = Path(__file__).resolve().parent / "fixtures" / "union_cte_model.sql"
BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"


def test_extract_model_queries_marks_models_read_count() -> None:
    install_parse_only_engine_support()
    context = Context(paths=FIXTURE_PROJECT, load=False)
    context.load(update_schemas=True)
    customers = next(model for model in context.models.values() if model.name == "sushi.customers")
    status = next(
        model for model in context.models.values() if model.name == "sushi.customer_status"
    )
    by_name = {
        query["name"]: query["models_read_count"] for query in extract_model_queries(customers)
    }
    assert by_name["$cte"] == 2
    assert by_name["$"] == 0
    status_by_name = {
        query["name"]: query["models_read_count"] for query in extract_model_queries(status)
    }
    assert status_by_name["$base"] == 1
    assert status_by_name["$filtered"] == 0
    assert status_by_name["$"] == 0


def test_processor_stores_models_read_count() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        rows = {
            (str(row["qualified_name"]), str(row["name"])): int(row["models_read_count"])
            for row in db.fetch(
                """
                SELECT models.qualified_name, queries.name, queries.models_read_count
                FROM queries
                INNER JOIN models
                    ON models.id = queries.model_id
                WHERE models.qualified_name IN ('sushi.customers', 'sushi.customer_status')
                """
            )
        }
    finally:
        db.close()
    assert rows[("sushi.customers", "$cte")] == 2
    assert rows[("sushi.customers", "$")] == 0
    assert rows[("sushi.customer_status", "$base")] == 1
    assert rows[("sushi.customer_status", "$filtered")] == 0
    assert rows[("sushi.customer_status", "$")] == 0


def test_unnest_source_is_not_a_synthetic_query_name() -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name == "fake.unnest_ids")
    columns = extract_model_columns(model)
    product = next(column for column in columns if column["name"] == "product_id")
    assert product["from_table"] is None
    assert product["qualified_name"] == "fake.unnest_ids/$/product_id"
    assert not any(
        column["from_table"] is not None and column["from_table"].startswith("$_")
        for column in columns
    )


def test_union_cte_column_lineage_does_not_raise(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(UNION_CTE_MODEL, root / "models" / "union_cte.sql")
    install_parse_only_engine_support()
    context = Context(paths=root, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name == "sushi.union_cte")
    columns = extract_model_columns(model)
    references = extract_model_column_references(model)
    assert any(column["name"] == "customer_id" for column in columns)
    assert any(
        reference["ref_column_qualified_name"].endswith("customer_id") for reference in references
    )
