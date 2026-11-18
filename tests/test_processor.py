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
            "SELECT directory_id FROM files WHERE path = ?",
            ("config.yaml",),
        )[0]
        waiter = db.fetch(
            "SELECT language, normalized_path FROM files WHERE path = ?",
            ("models/waiters.py",),
        )[0]
        file_count = db.fetch("SELECT COUNT(*) AS file_count FROM files")[0]["file_count"]
    finally:
        db.close()
    assert directories == ["audits", "macros", "models", "seeds", "tests"]
    assert config["directory_id"] is None
    assert waiter["language"] is None
    assert waiter["normalized_path"] == "models/waiters"
    assert file_count == 9


def test_processor_records_plain_files_and_drops_deleted_ones(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("hello\n")
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
    db = ProjectDB(root)
    try:
        ProjectProcessor(db, root).process(full=True)
        paths = {
            str(row["path"]): row["language"]
            for row in db.fetch("SELECT path, language FROM files")
        }
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        lines = db.fetch("SELECT line_count FROM files WHERE path = ?", ("README.md",))[0]
        normalized = db.fetch(
            "SELECT normalized_path FROM files WHERE path = ?",
            ("pkg/worker.py",),
        )[0]
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
    assert directories == ["notes", "pkg"]
    assert paths["README.md"] is None
    assert paths["LICENSE"] is None
    assert paths["notes/keep.txt"] is None
    assert paths["pkg/worker.py"] is None
    assert paths["pkg/__init__.py"] is None
    assert normalized["normalized_path"] == "pkg/worker"
    assert "pipe" not in paths
    assert "blocked.txt" not in paths
    assert ".sqlparse/secret.txt" not in paths
    assert int(lines["line_count"]) == 2
    assert remaining == {"LICENSE", "pkg/__init__.py", "pkg/worker.py"}
    assert remaining_dirs == {"pkg"}
    assert int(updated["line_count"]) == 3
