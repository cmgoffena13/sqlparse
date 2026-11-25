import shutil
from pathlib import Path

import pytest
from sqlmesh.core.context import Context

from src.db import ProjectDB
from src.parse.model_utils import model_config_lines, model_is_blueprint
from src.parse.sqlmesh_utils import install_parse_only_engine_support
from src.processor import ProjectProcessor
from tests.conftest import FIXTURE_PROJECT

BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"
QUOTED_EXTERNAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "quoted_external_project"
BLUEPRINT_MODEL = Path(__file__).resolve().parent / "fixtures" / "blueprint_items.sql"


def test_model_is_blueprint_from_python_env(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(BLUEPRINT_MODEL, root / "models" / "blueprint_items.sql")
    install_parse_only_engine_support()
    context = Context(paths=root, load=False)
    context.load(update_schemas=True)
    blueprints = [model for model in context.models.values() if "bp_items" in model.name]
    customers = next(model for model in context.models.values() if model.name == "sushi.customers")
    assert len(blueprints) == 2
    assert all(model_is_blueprint(model) for model in blueprints)
    assert model_is_blueprint(customers) is False


def test_processor_stores_is_blueprint(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(BLUEPRINT_MODEL, root / "models" / "blueprint_items.sql")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        rows = {
            str(row["qualified_name"]): bool(row["is_blueprint"])
            for row in db.fetch("SELECT qualified_name, is_blueprint FROM models")
        }
    finally:
        db.close()
    assert rows["bp1.bp_items"] is True
    assert rows["bp2.bp_items"] is True
    assert rows["sushi.customers"] is False


def test_model_config_lines_parses_with_the_model_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name.endswith("subscriptions"))
    seen: dict[str, str | None] = {}

    def tracking_parse(
        text: str,
        default_dialect: str | None = None,
        match_dialect: bool = True,
    ) -> list:
        from sqlmesh.core.dialect import parse as real_parse

        seen["default_dialect"] = default_dialect
        return real_parse(text, default_dialect=default_dialect, match_dialect=match_dialect)

    monkeypatch.setattr("src.parse.model_utils.sqlmesh_parse", tracking_parse)
    start_line, end_line = model_config_lines(model)
    assert seen["default_dialect"] == "bigquery"
    assert start_line == 1
    assert end_line == 5


def test_model_config_lines_matches_sqlmesh_external_yaml_names() -> None:
    install_parse_only_engine_support()
    context = Context(paths=QUOTED_EXTERNAL_FIXTURE, load=False)
    context.load(update_schemas=True)
    by_name = {
        model.name: model for model in context.models.values() if model.source_type == "external"
    }
    publications = by_name["`fake-gcp-project-123456`.`beehiiv`.`publications`"]
    hem_data = by_name["fake-gcp-project-123456.resonate.hem_data"]
    assert model_config_lines(publications) == (1, 3)
    assert model_config_lines(hem_data) == (4, 6)
