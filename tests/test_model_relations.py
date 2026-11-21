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


def test_model_relations_missing_model() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_model_relations(db, "missing.model", "dependencies")
    finally:
        db.close()
    assert out == "No model found."
