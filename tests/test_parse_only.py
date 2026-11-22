from pathlib import Path

from sqlmesh.core.config.connection import BigQueryConnectionConfig
from sqlmesh.core.context import Context

from src.parse.parse_only import install_parse_only_engine_support
from tests.conftest import FIXTURE_PROJECT

BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"


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
