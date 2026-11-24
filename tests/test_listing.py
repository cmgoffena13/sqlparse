import shutil
from pathlib import Path

from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.listing import list_models, list_schemas
from tests.conftest import FIXTURE_PROJECT

BLUEPRINT_MODEL = Path(__file__).resolve().parent / "fixtures" / "blueprint_items.sql"


def test_list_schemas_is_alphabetical() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = list_schemas(db)
    finally:
        db.close()
    assert out == "2 Schemas\n\n  • raw (EXTERNAL)\n  • sushi\n"


def test_list_models_is_alphabetical() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        sushi = list_models(db, "sushi")
        raw = list_models(db, "raw")
        missing = list_models(db, "missing")
        blank = list_models(db, " ")
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
    assert out == ("1 Model\n\n  • bp1.bp_items (BLUEPRINT)\n")
