from pathlib import Path

import pytest
from pathspec import PathSpec

from src.db import BATCH_TABLES, ProjectDB, remove_index_files
from src.git_utils import relative_path_is_ignored
from src.utils import line_count


def test_get_queries_snapshot_includes_line_spans(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path)
    try:
        db.connection.executescript(
            """
            INSERT INTO directories (id, parent_id, name, path, depth)
            VALUES (1, NULL, '.', '.', 0);
            INSERT INTO files (
                id, directory_id, name, path, normalized_path, language, content_hash,
                mtime_ns, size_bytes, line_count, is_test, is_config
            ) VALUES (1, 1, 'm.sql', 'm.sql', 'm.sql', 'sql', 'h', 0, 0, 1, 0, 0);
            INSERT INTO projects (id, name) VALUES (1, 'p');
            INSERT INTO project_gateways (
                id, project_id, name, catalog_name, dialect, is_default, snapshot_hash
            ) VALUES (1, 1, 'local', 'c', 'duckdb', 1, 'g');
            INSERT INTO models (
                id, file_id, gateway_id, dialect, schema_name, qualified_name, kind,
                is_blueprint, time_column, grain, config_start_line, config_end_line,
                description, snapshot_hash, data_hash, metadata_hash
            ) VALUES (
                1, 1, 1, 'duckdb', 's', 's.m', 'FULL', 0, NULL, NULL, 1, 1, NULL, 'mh', 'dh', 'mdh'
            );
            INSERT INTO queries (
                id, model_id, qualified_name, name, line_start, line_end, depth, file_id,
                snapshot_hash, select_col_count, models_read_count, line_count
            ) VALUES (1, 1, 's.m/$', '$', 10, 20, 0, 1, 'qh', 1, 0, 11);
            """
        )
        snapshot = db.get_queries_snapshot()
    finally:
        db.close()
    assert snapshot["1:$"]["name"] == "$"
    assert snapshot["1:$"]["line_start"] == 10
    assert snapshot["1:$"]["line_end"] == 20


def test_bulk_insert_upserts_search_docs_snapshot_and_fts(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path)
    try:
        batches = {table: [] for table in BATCH_TABLES}
        batches["search_docs"].append(
            {
                "id": 7,
                "model_name": "sushi.customers",
                "model_kind": "FULL",
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
        ref_index = [
            row["name"] for row in db.fetch("PRAGMA index_info(column_lineage_ref_column_id_index)")
        ]
        source_index = [
            row["name"]
            for row in db.fetch("PRAGMA index_info(column_lineage_source_column_id_index)")
        ]
        model_edge_index = [
            row["name"]
            for row in db.fetch(
                "PRAGMA index_info(column_lineage_ref_column_model_id_source_models_id_index)"
            )
        ]
        reverse_model_edge_index = [
            row["name"]
            for row in db.fetch(
                "PRAGMA index_info(column_lineage_source_models_id_ref_column_model_id_index)"
            )
        ]
        test_model_index = [
            row["name"] for row in db.fetch("PRAGMA index_info(tests_model_id_index)")
        ]
        names = {
            row["name"] for row in db.fetch("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        with pytest.raises(ValueError, match="unsupported table"):
            db.table_max_id("not_a_table")
        with pytest.raises(ValueError, match="unsupported table"):
            db.table_max_id("session_stats")
    finally:
        db.close()
    assert {
        "session_stats",
        "session_stats_files",
        "session_stats_tool_outputs",
    } <= names
    assert ref_index == ["ref_column_id"]
    assert source_index == ["source_column_id"]
    assert model_edge_index == ["ref_column_model_id", "source_models_id"]
    assert reverse_model_edge_index == ["source_models_id", "ref_column_model_id"]
    assert test_model_index == ["model_id"]
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
