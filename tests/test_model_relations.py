import pytest

import src.sqlparse_mcp.model_relations as model_relations_mod
from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.model_relations import get_model_relations
from tests.conftest import FIXTURE_PROJECT


def test_model_relations_dependencies_tree() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customer_orders", "dependencies")
    finally:
        db.close()
    assert out == (
        "sushi.customers\n"
        "├── raw.customers (EXTERNAL)\n"
        "└── raw.orders (EXTERNAL)\n"
        "\n"
        "sushi.orders\n"
        "├── raw.orders (EXTERNAL)\n"
        "└── sushi.customers\n"
        "    ├── raw.customers (EXTERNAL)\n"
        "    └── raw.orders (EXTERNAL)\n"
    )


def test_model_relations_dependents_tree() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customers", "dependents")
    finally:
        db.close()
    assert out == ("sushi.customer_orders\n\nsushi.orders\n└── sushi.customer_orders\n")


def test_model_relations_dependents_include_tests() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customers", "dependents", include_tests=True)
        dependencies = get_model_relations(
            db, "sushi.customer_orders", "dependencies", include_tests=True
        )
    finally:
        db.close()
    assert out == (
        "sushi.customer_orders\n"
        "\n"
        "sushi.orders\n"
        "├── tests/test_orders.yaml\n"
        "│   • test_orders_exist\n"
        "│   • test_orders_csv\n"
        "│   • test_orders_query\n"
        "└── sushi.customer_orders\n"
    )
    assert "tests/" not in dependencies


def test_model_relations_missing_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "missing.model", "dependencies")
    finally:
        db.close()
    assert out == "No relations."


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
    assert page_one == ("sushi.customer_orders\n\n… page 1 of 2 (1 of 2 dependents)\n")
    assert page_two == (
        "sushi.orders\n└── sushi.customer_orders\n\n… page 2 of 2 (1 of 2 dependents)\n"
    )
    assert missing == "No more dependents; page 3 is past 2."
    assert invalid == "Invalid page; pass page >= 1."
