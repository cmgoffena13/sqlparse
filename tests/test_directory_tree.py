from src.db import ProjectDB
from src.processor import ProjectProcessor
from src.sqlparse_mcp.directory_tree import get_directory_tree
from tests.conftest import FIXTURE_PROJECT


def test_directory_tree_lists_files() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_directory_tree(db, None)
    finally:
        db.close()
    assert out.startswith("PROJECT CONFIG FILE: config.yaml\n.\n")
    assert "models/" in out
    assert "customers.sql" in out
    assert "sushi.customers" not in out
    assert ", 0S)" not in out
    assert "L, " not in out
    assert "external_models.yaml" in out
    assert "— raw." not in out


def test_directory_tree_path_scopes_to_models() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_directory_tree(db, "models")
    finally:
        db.close()
    assert out.startswith("models/")
    assert "PROJECT CONFIG FILE:" not in out
    assert "customers.sql" in out
    assert "sushi.customers" not in out
    assert "macros/" not in out
    assert "config.yaml" not in out


def test_directory_tree_missing_directory() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        out = get_directory_tree(db, "does-not-exist")
    finally:
        db.close()
    assert out == "No directory found."
