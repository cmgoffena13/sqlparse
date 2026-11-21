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
    assert out.startswith("sushi.customer_orders\n")
    assert "├── sushi.customers" in out or "└── sushi.customers" in out
    assert "sushi.orders" in out
    assert "sushi.customers (EXTERNAL)" not in out
    assert "sushi.orders (EXTERNAL)" not in out
    assert "raw.customers (EXTERNAL)" in out
    assert "raw.orders (EXTERNAL)" in out
    assert "└── sushi.orders\n    ├── raw.orders (EXTERNAL)\n    └── sushi.customers\n" in out


def test_model_relations_dependents_tree() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "sushi.customers", "dependents")
    finally:
        db.close()
    assert out.startswith("sushi.customers\n")
    assert "sushi.customer_orders" in out
    assert "sushi.orders" in out
    assert "sushi.orders\n    └── sushi.customer_orders\n" in out
    assert "(EXTERNAL)" not in out


def test_model_relations_missing_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "missing.model", "dependencies")
    finally:
        db.close()
    assert out == "No model found."
