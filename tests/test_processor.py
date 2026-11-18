import os
from pathlib import Path

from src.db import ProjectDB
from src.processor import ProjectProcessor
from tests.conftest import FIXTURE_PROJECT


def test_processor_indexes_files_and_directories() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    try:
        ProjectProcessor(db, FIXTURE_PROJECT).process(full=True)
        ProjectProcessor(db, FIXTURE_PROJECT).process()
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        config = db.fetch(
            "SELECT directory_id, language, normalized_path FROM files WHERE path = ?",
            ("config.yaml",),
        )[0]
        waiter = db.fetch(
            "SELECT language, normalized_path FROM files WHERE path = ?",
            ("models/waiters.py",),
        )[0]
        customer = db.fetch(
            "SELECT language, normalized_path FROM files WHERE path = ?",
            ("models/customers.sql",),
        )[0]
        file_count = db.fetch("SELECT COUNT(*) AS file_count FROM files")[0]["file_count"]
    finally:
        db.close()
    assert directories == ["audits", "macros", "models", "seeds", "tests"]
    assert config["directory_id"] is None
    assert config["language"] == "yaml"
    assert config["normalized_path"] == "config"
    assert waiter["language"] == "python"
    assert waiter["normalized_path"] == "models.waiters"
    assert customer["language"] == "sql"
    assert customer["normalized_path"] == "models/customers"
    assert file_count == 9


def test_processor_records_plain_files_and_drops_deleted_ones(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("hello\n")
    (root / "settings.yml").write_text("enabled: true\n")
    (root / "LICENSE").write_text("mit\n")
    os.mkfifo(root / "pipe")
    blocked = root / "blocked.txt"
    blocked.write_text("secret")
    blocked.chmod(0)
    notes = root / "notes"
    notes.mkdir()
    (notes / "keep.txt").write_text("x")
    hidden = root / ".sqlparse"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("no")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    module = pkg / "worker.py"
    module.write_text("VALUE = 1\n")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def main() -> None:\n    pass\n")
    fundamentals = root / "src" / "fundamentals"
    fundamentals.mkdir()
    (fundamentals / "__init__.py").write_text("")
    (fundamentals / "xxx.py").write_text("def y() -> int:\n    return 1\n")
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        paths = {
            str(row["path"]): row["language"]
            for row in db.fetch("SELECT path, language FROM files")
        }
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        lines = db.fetch("SELECT line_count FROM files WHERE path = ?", ("README.md",))[0]
        normalized = {
            str(row["path"]): row["normalized_path"]
            for row in db.fetch("SELECT path, normalized_path FROM files")
        }
        module.write_text("VALUE = 1\nVALUE = 2\n")
        (root / "README.md").unlink()
        (notes / "keep.txt").unlink()
        notes.rmdir()
        ProjectProcessor(db, root).process()
        remaining = {str(row["path"]) for row in db.fetch("SELECT path FROM files")}
        remaining_dirs = {str(row["path"]) for row in db.fetch("SELECT path FROM directories")}
        updated = db.fetch("SELECT line_count FROM files WHERE path = ?", ("pkg/worker.py",))[0]
    finally:
        blocked.chmod(0o644)
        db.close()
    assert directories == ["notes", "pkg", "src", "src/fundamentals"]
    assert paths["README.md"] is None
    assert paths["settings.yml"] == "yaml"
    assert paths["LICENSE"] is None
    assert paths["notes/keep.txt"] is None
    assert paths["pkg/worker.py"] == "python"
    assert paths["pkg/__init__.py"] == "python"
    assert normalized["pkg/worker.py"] == "pkg.worker"
    assert normalized["pkg/__init__.py"] == "pkg"
    assert normalized["src/app.py"] == "src.app"
    assert normalized["src/fundamentals/xxx.py"] == "fundamentals.xxx"
    assert normalized["src/fundamentals/__init__.py"] == "fundamentals"
    assert normalized["notes/keep.txt"] == "notes/keep"
    assert "pipe" not in paths
    assert "blocked.txt" not in paths
    assert ".sqlparse/secret.txt" not in paths
    assert int(lines["line_count"]) == 2
    assert remaining == {
        "LICENSE",
        "pkg/__init__.py",
        "pkg/worker.py",
        "settings.yml",
        "src/app.py",
        "src/fundamentals/__init__.py",
        "src/fundamentals/xxx.py",
    }
    assert remaining_dirs == {"pkg", "src", "src/fundamentals"}
    assert int(updated["line_count"]) == 3
