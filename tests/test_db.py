from pathlib import Path

import pytest
from pathspec import PathSpec

from src.db import BATCH_TABLES, ProjectDB, remove_index_files
from src.git_utils import relative_path_is_ignored
from src.utils import line_count


def test_bulk_insert_upserts_search_docs_snapshot_and_fts(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path)
    try:
        batches = {table: [] for table in BATCH_TABLES}
        batches["search_docs"].append(
            {
                "id": 7,
                "model_name": "sushi.customers",
                "query_name": "cte",
                "column_name": "raw.orders.amount_cents",
                "snapshot_hash": "abc",
            }
        )
        db.bulk_insert(batches)
        docs = db.fetch(
            "SELECT id, model_name, query_name, column_name, snapshot_hash "
            "FROM search_docs ORDER BY id"
        )
        fts = db.fetch(
            "SELECT rowid, model_name, query_name, column_name FROM search_fts ORDER BY rowid"
        )
        snapshot = db.get_search_docs_snapshot()
    finally:
        db.close()
    assert len(docs) == 1
    assert int(docs[0]["id"]) == 7
    assert docs[0]["model_name"] == "sushi.customers"
    assert docs[0]["query_name"] == "cte"
    assert docs[0]["column_name"] == "raw.orders.amount_cents"
    assert docs[0]["snapshot_hash"] == "abc"
    assert len(fts) == 1
    assert int(fts[0]["rowid"]) == 7
    assert snapshot["7"]["id"] == 7
    assert snapshot["7"]["snapshot_hash"] == "abc"
    assert snapshot["7"]["seen"] is False


def test_recreate_schema_keeps_column_lineage_shape(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path)
    try:
        db.recreate_schema()
        reference_columns = [row["name"] for row in db.fetch("PRAGMA table_info(column_lineage)")]
        with pytest.raises(ValueError, match="unsupported table"):
            db.table_max_id("not_a_table")
    finally:
        db.close()
    assert reference_columns == [
        "id",
        "ref_column_id",
        "ref_query_id",
        "ref_column_model_id",
        "ref_column_query_name",
        "ref_column_qualified_name",
        "source_column_id",
        "source_query_id",
        "source_models_id",
        "source_query_name",
        "source_column_qualified_name",
        "source_line",
        "ref_line",
        "ref_kind",
        "ref_context",
        "snapshot_hash",
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
