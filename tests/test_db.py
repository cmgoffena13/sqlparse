from pathlib import Path

import pytest
from pathspec import PathSpec

from src.db import ProjectDB, remove_index_files
from src.git_utils import relative_path_is_ignored
from src.utils import line_count


def test_recreate_schema_resets_the_watermark(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path)
    try:
        db.set_watermark(5, 6)
        db.recreate_schema()
        watermark = db.get_watermark()
        reference_columns = [
            row["name"] for row in db.fetch("PRAGMA table_info(column_references)")
        ]
        with pytest.raises(ValueError, match="unsupported table"):
            db.table_max_id("not_a_table")
    finally:
        db.close()
    assert watermark == (0, 0)
    assert reference_columns == [
        "id",
        "ref_column_id",
        "ref_column_model_id",
        "ref_column_query_name",
        "ref_column_qualified_name",
        "source_column_id",
        "source_models_id",
        "source_query_name",
        "source_column_qualified_name",
        "source_line",
        "source_column",
        "ref_kind",
        "context",
    ]


def test_remove_index_files_deletes_the_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = ProjectDB(tmp_path)
    db_file = db.db_file
    db.close()
    remove_index_files()
    assert not db_file.exists()
    assert "Removed all index files." in capsys.readouterr().out


def test_line_count_counts_a_final_partial_line() -> None:
    assert line_count(b"") == 0
    assert line_count(b"a\n") == 1
    assert line_count(b"a") == 1


def test_relative_path_is_ignored_rejects_an_absolute_path() -> None:
    spec = PathSpec.from_lines("gitignore", [])
    with pytest.raises(ValueError, match="absolute"):
        relative_path_is_ignored("/abs/models", is_directory=True, spec=spec)
