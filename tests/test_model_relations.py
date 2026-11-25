import shutil
from pathlib import Path

import pytest

import src.sqlparse_mcp.model_relations as model_relations_mod
from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model_relations import get_model_relations
from tests.conftest import FIXTURE_PROJECT, memory_fqn

BLUEPRINT_MODEL = Path(__file__).resolve().parent / "fixtures" / "blueprint_items.sql"
BLUEPRINT_CONSUMER = Path(__file__).resolve().parent / "fixtures" / "blueprint_consumer.sql"

CUSTOMERS = memory_fqn("sushi.customers")
CUSTOMER_ORDERS = memory_fqn("sushi.customer_orders")
ORDERS = memory_fqn("sushi.orders")
RAW_CUSTOMERS = memory_fqn("raw.customers")
RAW_ORDERS = memory_fqn("raw.orders")


def test_model_relations_dependencies_tree() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customer_orders", "dependencies")
    finally:
        db.close()
    assert out == (
        f"{CUSTOMERS}\n"
        f"├── {RAW_CUSTOMERS} (EXTERNAL)\n"
        f"└── {RAW_ORDERS} (EXTERNAL)\n"
        "\n"
        f"{ORDERS}\n"
        f"├── {RAW_ORDERS} (EXTERNAL)\n"
        f"└── {CUSTOMERS}\n"
        f"    ├── {RAW_CUSTOMERS} (EXTERNAL)\n"
        f"    └── {RAW_ORDERS} (EXTERNAL)\n"
    )


def test_model_relations_marks_blueprints(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    shutil.copy(BLUEPRINT_MODEL, root / "models" / "blueprint_items.sql")
    shutil.copy(BLUEPRINT_CONSUMER, root / "models" / "blueprint_consumer.sql")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        out = get_model_relations(db, "sushi.bp_consumer", "dependencies")
    finally:
        db.close()
    assert out == f"{memory_fqn('bp1.bp_items')} (BLUEPRINT)\n"


def test_model_relations_dependents_tree() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customers", "dependents")
    finally:
        db.close()
    assert out == (f"{CUSTOMER_ORDERS}\n\n{ORDERS}\n└── {CUSTOMER_ORDERS}\n")


def test_model_relations_dependents_include_tests() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customers", "dependents", include_tests=True)
        dependencies = get_model_relations(
            db, "memory.sushi.customer_orders", "dependencies", include_tests=True
        )
    finally:
        db.close()
    assert out == (
        f"{CUSTOMER_ORDERS}\n"
        "\n"
        f"{ORDERS}\n"
        "├── tests/test_orders.yaml\n"
        "│   • test_orders_exist\n"
        "│   • test_orders_csv\n"
        "│   • test_orders_query\n"
        f"└── {CUSTOMER_ORDERS}\n"
    )
    assert "tests/" not in dependencies


def test_model_relations_missing_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "missing.model", "dependencies")
    finally:
        db.close()
    from src.sqlparse_mcp.model_utils import model_not_found_message

    assert out == model_not_found_message()


def test_model_relations_pages_top_level_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_relations_mod, "_PAGE_SIZE", 1)
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        page_one = get_model_relations(db, "sushi.customers", "dependents", page=1)
        page_two = get_model_relations(db, "sushi.customers", "dependents", page=2)
        missing = get_model_relations(db, "sushi.customers", "dependents", page=3)
        invalid = get_model_relations(db, "sushi.customers", "dependents", page=0)
    finally:
        db.close()
    assert page_one == (f"{CUSTOMER_ORDERS}\n\n… page 1 of 2 (1 of 2 dependents)\n")
    assert page_two == (f"{ORDERS}\n└── {CUSTOMER_ORDERS}\n\n… page 2 of 2 (1 of 2 dependents)\n")
    assert missing == "No more dependents; page 3 is past 2."
    assert invalid == "Invalid page; pass page >= 1."
