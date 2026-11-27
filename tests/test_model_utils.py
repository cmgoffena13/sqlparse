import shutil
from pathlib import Path

import pytest
from sqlmesh.core.context import Context

from src.db import ProjectDB
from src.parse.model_utils import model_config_lines, model_is_blueprint
from src.parse.sqlmesh_utils import install_parse_only_engine_support, normalized_model_name
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model_utils import resolve_column_ids, resolve_model_qualified_name
from tests.conftest import FIXTURE_PROJECT, memory_fqn

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
    assert rows["memory.bp1.bp_items"] is True
    assert rows["memory.bp2.bp_items"] is True
    assert rows["memory.sushi.customers"] is False


def test_read_model_file_reflects_disk_changes(tmp_path: Path) -> None:
    from src.parse.model_utils import read_model_file

    path = tmp_path / "model.sql"
    path.write_text("first\n", encoding="utf-8")
    assert read_model_file(str(path)) == "first\n"
    path.write_text("second\n", encoding="utf-8")
    assert read_model_file(str(path)) == "second\n"


def test_model_config_lines_parses_with_the_model_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name.endswith("subscriptions"))
    seen: dict[str, str | None] = {}
    parse_calls = {"count": 0}

    def tracking_parse(
        text: str,
        default_dialect: str | None = None,
        match_dialect: bool = True,
    ) -> list:
        from sqlmesh.core.dialect import parse as real_parse

        parse_calls["count"] += 1
        seen["default_dialect"] = default_dialect
        return real_parse(text, default_dialect=default_dialect, match_dialect=match_dialect)

    monkeypatch.setattr("src.parse.model_utils.sqlmesh_parse", tracking_parse)
    start_line, end_line = model_config_lines(model)
    assert model_config_lines(model) == (start_line, end_line)
    assert seen["default_dialect"] == "bigquery"
    assert start_line == 1
    assert end_line == 5
    assert parse_calls["count"] == 2


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


def test_resolve_model_qualified_name_uses_model_gateway_catalog() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        gateway = db.connection.execute(
            "SELECT id, catalog_name, dialect FROM project_gateways WHERE name = 'local'"
        ).fetchone()
        model = db.connection.execute(
            """
            SELECT qualified_name, gateway_id
            FROM models
            WHERE qualified_name = ?
            """,
            (memory_fqn("sushi.customers"),),
        ).fetchone()
        assert gateway is not None
        assert model is not None
        assert int(model["gateway_id"]) == int(gateway["id"])
        assert gateway["catalog_name"] == "memory"
        assert resolve_model_qualified_name(db, "sushi.customers") == memory_fqn("sushi.customers")
        assert resolve_model_qualified_name(db, memory_fqn("sushi.customers")) == memory_fqn(
            "sushi.customers"
        )
    finally:
        db.close()


def test_resolve_model_qualified_name_short_external_uses_gateway() -> None:
    install_parse_only_engine_support()
    db = ProjectDB(QUOTED_EXTERNAL_FIXTURE)
    try:
        ProjectProcessor(db, QUOTED_EXTERNAL_FIXTURE).process(full=True)
        expected = normalized_model_name(
            "beehiiv.publications", "fake-gcp-project-123456", "bigquery"
        )
        gateway = db.connection.execute(
            "SELECT id FROM project_gateways WHERE name = 'local'"
        ).fetchone()
        model = db.connection.execute(
            "SELECT gateway_id FROM models WHERE qualified_name = ?",
            (expected,),
        ).fetchone()
        assert gateway is not None
        assert model is not None
        assert int(model["gateway_id"]) == int(gateway["id"])
        assert resolve_model_qualified_name(db, "beehiiv.publications") == expected
    finally:
        db.close()


def test_resolve_column_ids_accepts_unquoted_and_bare_names() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        model = memory_fqn("sushi.customer_orders")
        quoted = f"{memory_fqn('sushi.customers')}.customer_id"
        full = resolve_column_ids(db, model, "$", "memory.sushi.customers.customer_id")
        short = resolve_column_ids(db, model, "$", "sushi.customers.customer_id")
        exact = resolve_column_ids(db, model, "$", quoted)
        bare = resolve_column_ids(db, model, "$", "customer_id")
        missing = resolve_column_ids(db, model, "$", "missing_col")
    finally:
        db.close()
    assert full == exact
    assert short == exact
    assert len(exact) == 1
    assert len(bare) == 2
    assert missing == []


def test_resolve_column_ids_accepts_cte_without_dollar() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        model = memory_fqn("sushi.customer_status")
        with_dollar = resolve_column_ids(db, model, "$", "$filtered.customer_id")
        without = resolve_column_ids(db, model, "$", "filtered.customer_id")
    finally:
        db.close()
    assert with_dollar == without
    assert len(with_dollar) == 1


def test_resolve_column_ids_accepts_get_query_model_qualified_names() -> None:
    root = Path(__file__).resolve().parent / "fixtures" / "shop_column_project"
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        clean = memory_fqn("shop.orders_clean")
        external = memory_fqn("ext_shop.orders")
        bare = resolve_column_ids(db, clean, "$", "event_date_et")
        model_qn = resolve_column_ids(db, clean, "$", f"{clean}.event_date_et")
        short_model = resolve_column_ids(db, clean, "$", "shop.orders_clean.event_date_et")
        source = resolve_column_ids(db, clean, "$", f"{external}.event_date")
        external_bare = resolve_column_ids(db, external, "$", "event_date")
        external_qn = resolve_column_ids(db, external, "$", f"{external}.event_date")
        external_short = resolve_column_ids(db, external, "$", "ext_shop.orders.event_date")
    finally:
        db.close()
    assert bare == model_qn == short_model
    assert len(bare) == 1
    assert len(source) == 1
    assert external_bare == external_qn == external_short
    assert len(external_bare) == 1
