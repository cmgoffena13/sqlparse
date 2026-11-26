import shutil
from pathlib import Path

from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.listing import list_catalogs, list_models, list_schemas
from tests.conftest import FIXTURE_PROJECT

BLUEPRINT_MODEL = Path(__file__).resolve().parent / "fixtures" / "blueprint_items.sql"


def test_list_catalogs_shows_schema_and_table_counts() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = list_catalogs(db)
    finally:
        db.close()
    assert out == "1 Catalog\n\n  • memory (DEFAULT) - 2 schemas, 8 tables\n"


def test_list_schemas_uses_default_catalog_when_omitted() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        defaulted = list_schemas(db)
        explicit = list_schemas(db, "memory")
        missing = list_schemas(db, "missing")
        blank = list_schemas(db, " ")
    finally:
        db.close()
    assert defaulted == ("2 Schemas\n\n  • raw (EXTERNAL) - 2 tables\n  • sushi - 6 tables\n")
    assert explicit == defaulted
    assert missing == "No schemas found."
    assert blank == defaulted


def test_list_models_scopes_to_catalog_and_schema() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        sushi = list_models(db, "sushi")
        raw = list_models(db, "raw", "memory")
        missing = list_models(db, "missing")
        blank = list_models(db, " ")
        wrong_catalog = list_models(db, "sushi", "missing")
    finally:
        db.close()
    assert sushi == (
        "6 Models\n"
        "\n"
        "  • sushi.customer_orders\n"
        "  • sushi.customer_status\n"
        "  • sushi.customers\n"
        "  • sushi.orders\n"
        "  • sushi.raw_seed\n"
        "  • sushi.waiters\n"
    )
    assert raw == ("2 Models\n\nEXTERNAL SCHEMA\n\n  • raw.customers\n  • raw.orders\n")
    assert missing == "No models found."
    assert blank == "No schema given; pass a schema name."
    assert wrong_catalog == "No models found."


def test_list_models_marks_blueprints(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(BLUEPRINT_MODEL, root / "models" / "blueprint_items.sql")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        out = list_models(db, "bp1")
    finally:
        db.close()
    assert out == "1 Model\n\n  • bp1.bp_items (BLUEPRINT)\n"
