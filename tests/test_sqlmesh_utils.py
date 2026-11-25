from pathlib import Path

from sqlmesh.core.config.connection import BigQueryConnectionConfig
from sqlmesh.core.context import Context

from src.parse.sqlmesh_utils import (
    column_label,
    install_parse_only_engine_support,
    normalized_column_name,
    normalized_model_name,
)
from tests.conftest import FIXTURE_PROJECT

BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"
QUOTED_EXTERNAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "quoted_external_project"


def test_normalized_model_name_matches_sqlmesh_fqn() -> None:
    install_parse_only_engine_support()
    context = Context(paths=QUOTED_EXTERNAL_FIXTURE, load=False)
    context.load(update_schemas=True)
    publications = next(
        model
        for model in context.models.values()
        if model.name == "`fake-gcp-project-123456`.`beehiiv`.`publications`"
    )
    expected = "fake-gcp-project-123456.beehiiv.publications"
    assert (
        normalized_model_name(publications.name, context.default_catalog, publications.dialect)
        == expected
    )
    assert (
        normalized_model_name(
            "beehiiv.publications",
            "fake-gcp-project-123456",
            publications.dialect,
        )
        == expected
    )
    assert normalized_model_name(publications.fqn, None, publications.dialect) == expected


def test_bigquery_connection_config_constructs_without_google_package() -> None:
    install_parse_only_engine_support()
    config = BigQueryConnectionConfig(project="fake-project")
    assert config.get_catalog() == "fake-project"


def test_bigquery_fixture_loads_without_engine_library() -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    assert '"fake-project"."fake"."products"' in context.models
    assert context.default_catalog == "fake-project"


def test_duckdb_fixture_keeps_memory_catalog_without_creating_remote_engines() -> None:
    install_parse_only_engine_support()
    context = Context(paths=FIXTURE_PROJECT, load=False)
    assert context.default_catalog_per_gateway == {"local": "memory"}
    context.load(update_schemas=True)
    assert len(context.models) > 0


def test_normalized_column_name_fills_catalog_without_quotes() -> None:
    assert (
        normalized_column_name("memory.raw.orders.order_id", "memory", "duckdb")
        == "memory.raw.orders.order_id"
    )
    assert (
        normalized_column_name("raw.orders.order_id", "memory", "duckdb")
        == "memory.raw.orders.order_id"
    )
    assert normalized_column_name("order_id", "memory", "duckdb") == "order_id"
    assert normalized_column_name("$cte.customer_id", "memory", "duckdb") == "$cte.customer_id"
    assert (
        normalized_column_name("beehiiv.publications.id", "fake-gcp-project-123456", "bigquery")
        == "fake-gcp-project-123456.beehiiv.publications.id"
    )


def test_column_label_is_unquoted() -> None:
    assert column_label("memory.raw.orders", "order_id", "duckdb") == "memory.raw.orders.order_id"
    assert column_label("$cte", "customer_id", "duckdb") == "$cte.customer_id"
    assert column_label(None, "order_id", "duckdb") == "order_id"
