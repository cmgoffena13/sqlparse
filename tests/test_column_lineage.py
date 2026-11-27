import shutil
from pathlib import Path

from sqlmesh.core.context import Context

from src.db import ProjectDB
from src.parse.column_lineage import (
    extract_model_column_references,
    extract_model_columns,
    extract_model_queries,
    prepare_model_query,
)
from src.parse.model_utils import model_qualified_name
from src.parse.sqlmesh_utils import install_parse_only_engine_support
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model import get_model
from tests.conftest import FIXTURE_PROJECT

UNION_CTE_MODEL = Path(__file__).resolve().parent / "fixtures" / "union_cte_model.sql"
UNION_FROM_CTE_MODEL = Path(__file__).resolve().parent / "fixtures" / "union_from_cte_model.sql"
BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"
DATE_EXPR_JOIN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "date_expr_join_project"


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
    line_counts = {query["name"]: query["line_count"] for query in extract_model_queries(customers)}
    assert line_counts["$"] == 5
    assert line_counts["$cte"] == 10
    status_by_name = {
        query["name"]: query["models_read_count"] for query in extract_model_queries(status)
    }
    assert status_by_name["$base"] == 1
    assert status_by_name["$filtered"] == 0
    assert status_by_name["$"] == 0


def test_prepare_model_query_reuse_matches_direct_extracts() -> None:
    install_parse_only_engine_support()
    context = Context(paths=FIXTURE_PROJECT, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name == "sushi.customers")
    prepared = prepare_model_query(model)
    assert extract_model_queries(model, prepared) == extract_model_queries(model)
    assert extract_model_columns(model, prepared) == extract_model_columns(model)
    assert extract_model_column_references(model, prepared) == extract_model_column_references(
        model
    )


def test_source_models_id_uses_qn_model_prefix() -> None:
    from src.parse.sqlmesh_parser import resolve_source_models_id

    mapping = {
        "memory.sushi.customers": 1,
        "memory.sushi.customer_orders": 2,
        "memory.sushi": 3,
    }
    assert resolve_source_models_id("memory.sushi.customers/$/id", mapping, 0) == 1
    assert resolve_source_models_id("memory.sushi.customer_orders/$cte/x", mapping, 0) == 2
    assert resolve_source_models_id("memory.other/$/x", mapping, 9) == 9


def test_column_lineage_source_models_id_matches_source_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        rows = db.fetch(
            """
            SELECT
                source_models.qualified_name AS source_model,
                column_lineage.source_column_qualified_name AS source_qn
            FROM column_lineage
            INNER JOIN models AS source_models
                ON source_models.id = column_lineage.source_models_id
            WHERE column_lineage.source_column_qualified_name LIKE 'memory.sushi.customers/%'
            """
        )
    finally:
        db.close()
    assert rows
    for row in rows:
        assert str(row["source_model"]) == "memory.sushi.customers"
        assert str(row["source_qn"]).startswith("memory.sushi.customers/")


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
                WHERE models.qualified_name IN (
                    'memory.sushi.customers',
                    'memory.sushi.customer_status'
                )
                """
            )
        }
    finally:
        db.close()
    assert rows[("memory.sushi.customers", "$cte")] == 2
    assert rows[("memory.sushi.customers", "$")] == 0
    assert rows[("memory.sushi.customer_status", "$base")] == 1
    assert rows[("memory.sushi.customer_status", "$filtered")] == 0
    assert rows[("memory.sushi.customer_status", "$")] == 0


def test_processor_stores_direct_model_relation_counts() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        rows = {
            str(row["qualified_name"]): (
                int(row["direct_dependencies_count"]),
                int(row["direct_dependents_count"]),
            )
            for row in db.fetch(
                """
                SELECT
                    qualified_name,
                    direct_dependencies_count,
                    direct_dependents_count
                FROM models
                WHERE qualified_name IN (
                    'memory.sushi.customers',
                    'memory.sushi.customer_orders',
                    'memory.sushi.customer_status',
                    'memory.sushi.orders'
                )
                """
            )
        }
    finally:
        db.close()
    assert rows["memory.sushi.customers"] == (2, 2)
    assert rows["memory.sushi.customer_orders"] == (2, 0)
    assert rows["memory.sushi.customer_status"] == (1, 0)
    assert rows["memory.sushi.orders"] == (2, 1)


def test_unnest_source_is_not_a_synthetic_query_name() -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name == "fake.unnest_ids")
    columns = extract_model_columns(model)
    product = next(column for column in columns if column["name"] == "product_id")
    assert product["from_table"] is None
    assert product["qualified_name"] == f"{model_qualified_name(model)}/$/product_id"
    assert not any(
        column["from_table"] is not None and column["from_table"].startswith("$_")
        for column in columns
    )


def test_extract_tolerates_unknown_table_qualified_columns() -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name == "fake.unknown_column")
    queries = extract_model_queries(model)
    columns = extract_model_columns(model)
    references = extract_model_column_references(model)
    assert any(query["name"] == "$" for query in queries)
    assert any(column["name"] == "missing_col" for column in columns)
    assert any(
        reference["ref_column_qualified_name"].endswith("missing_col") for reference in references
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


def test_union_cte_query_stats_use_output_width_and_arm_rollups(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(UNION_CTE_MODEL, root / "models" / "union_cte.sql")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        rows = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                """
                SELECT
                    queries.name,
                    queries.select_col_count,
                    queries.where_condition_count,
                    queries.join_statement_count,
                    queries.models_read_count
                FROM queries
                INNER JOIN models
                    ON models.id = queries.model_id
                WHERE models.qualified_name = 'memory.sushi.union_cte'
                """
            )
        }
        tree = get_model(db, "sushi.union_cte")
    finally:
        db.close()
    assert rows["$cte"]["select_col_count"] == 1
    assert rows["$cte"]["models_read_count"] == 2
    assert rows["$cte"]["where_condition_count"] == 0
    assert rows["$cte"]["join_statement_count"] == 0
    assert "L6-10  $cte (1S, 2M)" in tree
    assert "└── $" in tree


def test_union_cte_fed_by_cte_syncs_column_lineage(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(UNION_FROM_CTE_MODEL, root / "models" / "union_from_cte.sql")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        columns = {
            str(row["qualified_name"])
            for row in db.fetch(
                """
                SELECT columns.qualified_name
                FROM columns
                INNER JOIN models
                    ON models.id = columns.model_id
                WHERE models.qualified_name = 'memory.sushi.union_from_cte'
                """
            )
        }
        refs = {
            str(row["ref_column_qualified_name"])
            for row in db.fetch(
                """
                SELECT column_lineage.ref_column_qualified_name
                FROM column_lineage
                INNER JOIN models
                    ON models.id = column_lineage.ref_column_model_id
                WHERE models.qualified_name = 'memory.sushi.union_from_cte'
                """
            )
        }
    finally:
        db.close()
    assert "memory.sushi.union_from_cte/$combined/$base.id" in columns
    assert "memory.sushi.union_from_cte/$combined/$base.id" in refs


def test_date_expression_join_syncs_column_lineage(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(DATE_EXPR_JOIN_FIXTURE, root)
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        refs = {
            str(row["ref_column_qualified_name"])
            for row in db.fetch(
                """
                SELECT column_lineage.ref_column_qualified_name
                FROM column_lineage
                INNER JOIN models
                    ON models.id = column_lineage.ref_column_model_id
                WHERE models.qualified_name = 'memory.marketing.checkout'
                """
            )
        }
    finally:
        db.close()
    assert (
        "memory.marketing.checkout/$marketing_views/memory.marketing.page_views.event_date_et"
    ) in refs
