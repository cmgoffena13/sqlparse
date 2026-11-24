import shutil
from pathlib import Path

from sqlmesh.core.context import Context

from src.parse.column_lineage import extract_model_column_references, extract_model_columns
from src.parse.parse_only import install_parse_only_engine_support
from tests.conftest import FIXTURE_PROJECT

UNION_CTE_MODEL = Path(__file__).resolve().parent / "fixtures" / "union_cte_model.sql"
BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"


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
