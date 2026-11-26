import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from src.assigner import GlobalIDAssigner
from src.db import ProjectDB
from src.parse.sqlmesh_parser import SQLMeshParser
from src.processor import ProjectProcessor
from tests.conftest import FIXTURE_PROJECT, memory_fqn

CUSTOMERS_FQN = memory_fqn("sushi.customers")
CUSTOMER_ORDERS_FQN = memory_fqn("sushi.customer_orders")
CUSTOMER_STATUS_FQN = memory_fqn("sushi.customer_status")
ORDERS_FQN = memory_fqn("sushi.orders")
WAITERS_FQN = memory_fqn("sushi.waiters")
RAW_SEED_FQN = memory_fqn("sushi.raw_seed")
RAW_CUSTOMERS_FQN = memory_fqn("raw.customers")
RAW_ORDERS_FQN = memory_fqn("raw.orders")
CUSTOMERS_CTE_CUSTOMER_ID = f"{CUSTOMERS_FQN}/$/$cte.customer_id"
CUSTOMERS_CTE_AMOUNT = f"{CUSTOMERS_FQN}/$/$cte.amount"
CUSTOMERS_CTE_STATUS = f"{CUSTOMERS_FQN}/$/$cte.status"
CUSTOMERS_CTE_RAW_CUSTOMER_ID = f"{CUSTOMERS_FQN}/$cte/{RAW_CUSTOMERS_FQN}.customer_id"
CUSTOMERS_CTE_RAW_STATUS = f"{CUSTOMERS_FQN}/$cte/{RAW_CUSTOMERS_FQN}.status"
CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID = f"{CUSTOMERS_FQN}/$cte/{RAW_ORDERS_FQN}.customer_id"
CUSTOMERS_CTE_RAW_AMOUNT_CENTS = f"{CUSTOMERS_FQN}/$cte/{RAW_ORDERS_FQN}.amount_cents"


def test_processor_releases_sqlmesh_before_the_next_index() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    first = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        first.process(full=True)
        first.close()
        second = ProjectProcessor(db, FIXTURE_PROJECT)
        try:
            second.process()
            rows = db.fetch(
                "SELECT qualified_name FROM models WHERE qualified_name = ?",
                (CUSTOMERS_FQN,),
            )
            assert rows[0]["qualified_name"] == CUSTOMERS_FQN
        finally:
            second.close()
    finally:
        db.close()


def test_sync_flushes_every_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.parse import sqlmesh_parser as parser_mod

    flush_calls = {"count": 0}
    real_flush = SQLMeshParser._flush

    def counting_flush(self: SQLMeshParser) -> None:
        flush_calls["count"] += 1
        real_flush(self)

    monkeypatch.setattr(SQLMeshParser, "_flush", counting_flush)
    monkeypatch.setattr(parser_mod, "FLUSH_BATCH_SIZE", 10)
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)
        total_rows = (
            int(db.fetch("SELECT COUNT(*) AS c FROM models")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM macros")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM audits")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM queries")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM columns")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM column_lineage")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM search_docs")[0]["c"])
            + int(db.fetch("SELECT COUNT(*) AS c FROM tests")[0]["c"])
        )
        assert total_rows > 10
        assert flush_calls["count"] >= total_rows // 10
    finally:
        processor.close()
        db.close()


def test_full_sync_extracts_models_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from sqlmesh.core.model import Model

    from src.parse import column_lineage
    from src.parse.column_lineage import ModelExtractBundle

    bundle_calls = {"count": 0}
    real_bundle = column_lineage.extract_model_bundle

    def tracking_bundle(model: Model) -> ModelExtractBundle:
        bundle_calls["count"] += 1
        return real_bundle(model)

    submitted: list[int] = []

    class TrackingExecutor(ThreadPoolExecutor):
        def map(self, fn, *iterables, timeout=None, chunksize=1):
            items = list(iterables[0])
            submitted.append(len(items))
            return super().map(fn, items, timeout=timeout, chunksize=chunksize)

    monkeypatch.setattr("src.parse.sqlmesh_parser.extract_model_bundle", tracking_bundle)
    monkeypatch.setattr("src.parse.sqlmesh_parser.ThreadPoolExecutor", TrackingExecutor)
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)
        assert bundle_calls["count"] > 0
        assert submitted
        assert submitted[0] == bundle_calls["count"]
        assert db.fetch("SELECT COUNT(*) AS c FROM column_lineage")[0]["c"] > 0
    finally:
        processor.close()
        db.close()


def test_second_full_sync_skips_prepare_when_model_hashes_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlmesh.core.model import Model

    from src.parse import column_lineage
    from src.parse.column_lineage import PreparedModelQuery

    prepared_names: list[str] = []
    real_prepare = column_lineage.prepare_model_query

    def tracking_prepare(model: Model) -> PreparedModelQuery:
        prepared_names.append(model.name)
        return real_prepare(model)

    monkeypatch.setattr(column_lineage, "prepare_model_query", tracking_prepare)
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)
        rows = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch("SELECT qualified_name, data_hash, metadata_hash FROM models")
        }
        customers = next(
            model
            for model in processor.parser.context.models.values()
            if model.name == "sushi.customers"
        )
        assert rows[CUSTOMERS_FQN]["data_hash"] == customers.data_hash
        assert rows[CUSTOMERS_FQN]["metadata_hash"] == customers.metadata_hash
        first_prepare_count = len(prepared_names)
        assert first_prepare_count > 0
        lineage_before = db.fetch("SELECT COUNT(*) AS c FROM column_lineage")[0]["c"]
        processor.process(full=True)
        assert len(prepared_names) == first_prepare_count
        assert db.fetch("SELECT COUNT(*) AS c FROM column_lineage")[0]["c"] == lineage_before
    finally:
        processor.close()
        db.close()


def test_processor_reuses_context_across_process_calls() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)
        context = processor.parser.context
        processor.process()
        assert processor.parser.context is context
        rows = db.fetch(
            "SELECT qualified_name FROM models WHERE qualified_name = ?",
            (CUSTOMERS_FQN,),
        )
        assert rows[0]["qualified_name"] == CUSTOMERS_FQN
    finally:
        processor.close()
        db.close()


def test_process_prints_files_and_models_count(capsys: pytest.CaptureFixture[str]) -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)
        model_count = len(processor.parser.context.models)
        full_line = next(
            line for line in capsys.readouterr().err.splitlines() if line.startswith("Indexed ")
        )
        assert full_line.startswith(
            f"Indexed {processor.files_indexed} files and {model_count} models in "
        )
        assert full_line.endswith("ms")
        assert "incrementally" not in full_line
        processor.process()
        incremental_line = next(
            line for line in capsys.readouterr().err.splitlines() if line.startswith("Indexed ")
        )
        assert incremental_line.startswith(
            f"Indexed {processor.files_indexed} files and 0 models incrementally in "
        )
        assert incremental_line.endswith("ms")
    finally:
        processor.close()
        db.close()


def test_processor_start_time_covers_sqlmesh_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_started: list[float] = []
    real_init = SQLMeshParser.__init__

    def tracking_init(
        self: SQLMeshParser,
        db: ProjectDB,
        assigner: GlobalIDAssigner,
        root: Path,
    ) -> None:
        parser_started.append(time.perf_counter())
        real_init(self, db, assigner, root)

    monkeypatch.setattr(SQLMeshParser, "__init__", tracking_init)
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        assert len(parser_started) == 1
        assert processor.start_time is not None
        assert processor.start_time <= parser_started[0]
        processor.process(full=True)
        assert processor.start_time is None
        processor.process()
        assert processor.start_time is None
    finally:
        processor.close()
        db.close()


def test_concurrent_run_query_does_not_raise() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)

        def worker() -> int:
            return processor.run_query(
                lambda conn: conn.connection.execute("SELECT COUNT(*) AS c FROM models").fetchone()[
                    "c"
                ]
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker) for _ in range(8)]
            results = [future.result() for future in as_completed(futures)]

        assert len(results) == 8
        assert all(isinstance(count, int) for count in results)
    finally:
        processor.close()
        db.close()


def test_processor_indexes_files_and_directories() -> None:
    db = ProjectDB(FIXTURE_PROJECT)
    processor = ProjectProcessor(db, FIXTURE_PROJECT)
    try:
        processor.process(full=True)
        first_projects = {
            str(row["name"]): dict(row) for row in db.fetch("SELECT id, name FROM projects")
        }
        first_gateways = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                """
                SELECT id, project_id, name, catalog_name, dialect, is_default, snapshot_hash
                FROM project_gateways
                """
            )
        }
        first_models = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, gateway_id, dialect, schema_name, qualified_name, kind, "
                "time_column, grain, config_start_line, config_end_line, description, "
                "snapshot_hash, data_hash, metadata_hash FROM models"
            )
        }
        first_columns = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT c.id, c.model_id, c.file_id, c.query_id, "
                "m.qualified_name || '/' || q.name AS query_name, c.from_table, c.name, "
                "c.column_name, "
                "c.qualified_name, c.data_type, c.nullable, c.unique_constraint, "
                "c.line_start, c.line_end, c.context, c.description, c.is_select, "
                "c.snapshot_hash "
                "FROM columns AS c "
                "INNER JOIN queries AS q ON q.id = c.query_id "
                "INNER JOIN models AS m ON m.id = c.model_id"
            )
        }
        first_queries = {
            (int(row["model_id"]), str(row["name"])): dict(row)
            for row in db.fetch(
                "SELECT id, model_id, name, line_start, line_end, depth, file_id, snapshot_hash, "
                "select_col_count, select_expr_count, select_alias_count, where_condition_count, "
                "join_statement_count, group_by_col_count, having_condition_count, "
                "order_by_col_count FROM queries"
            )
        }
        first_macros = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, kind, line_start, line_end, snapshot_hash FROM macros"
            )
        }
        first_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        first_audits = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, line_start, line_end, snapshot_hash FROM audits"
            )
        }
        first_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
        }
        first_references = {
            (
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                int(row["ref_line"]),
                str(row["ref_kind"]),
            ): dict(row)
            for row in db.fetch(
                "SELECT id, ref_column_id, ref_column_model_id, ref_column_query_name, "
                "ref_column_qualified_name, source_column_id, source_models_id, "
                "source_query_name, source_column_qualified_name, "
                "source_line, ref_line, ref_kind, ref_context, snapshot_hash "
                "FROM column_lineage"
            )
        }
        first_tests = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, model_id, name, line_start, line_end, snapshot_hash FROM tests"
            )
        }
        first_test_references = {
            (int(row["test_id"]), str(row["qualified_name"]))
            for row in db.fetch(
                "SELECT tr.test_id, c.qualified_name FROM test_references tr "
                "INNER JOIN columns c ON c.id = tr.column_id"
            )
        }
        processor.process()
        second_projects = {
            str(row["name"]): dict(row) for row in db.fetch("SELECT id, name FROM projects")
        }
        second_gateways = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                """
                SELECT id, project_id, name, catalog_name, dialect, is_default, snapshot_hash
                FROM project_gateways
                """
            )
        }
        second_models = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, gateway_id, dialect, schema_name, qualified_name, kind, "
                "time_column, grain, config_start_line, config_end_line, description, "
                "snapshot_hash, data_hash, metadata_hash FROM models"
            )
        }
        second_columns = {
            str(row["qualified_name"]): dict(row)
            for row in db.fetch(
                "SELECT c.id, c.model_id, c.file_id, c.query_id, "
                "m.qualified_name || '/' || q.name AS query_name, c.from_table, c.name, "
                "c.column_name, "
                "c.qualified_name, c.data_type, c.nullable, c.unique_constraint, "
                "c.line_start, c.line_end, c.context, c.description, c.is_select, "
                "c.snapshot_hash "
                "FROM columns AS c "
                "INNER JOIN queries AS q ON q.id = c.query_id "
                "INNER JOIN models AS m ON m.id = c.model_id"
            )
        }
        second_queries = {
            (int(row["model_id"]), str(row["name"])): dict(row)
            for row in db.fetch(
                "SELECT id, model_id, name, line_start, line_end, depth, file_id, snapshot_hash, "
                "select_col_count, select_expr_count, select_alias_count, where_condition_count, "
                "join_statement_count, group_by_col_count, having_condition_count, "
                "order_by_col_count FROM queries"
            )
        }
        second_macros = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, kind, line_start, line_end, snapshot_hash FROM macros"
            )
        }
        second_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        second_audits = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, name, line_start, line_end, snapshot_hash FROM audits"
            )
        }
        second_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
        }
        second_references = {
            (
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                int(row["ref_line"]),
                str(row["ref_kind"]),
            ): dict(row)
            for row in db.fetch(
                "SELECT id, ref_column_id, ref_column_model_id, ref_column_query_name, "
                "ref_column_qualified_name, source_column_id, source_models_id, "
                "source_query_name, source_column_qualified_name, "
                "source_line, ref_line, ref_kind, ref_context, snapshot_hash "
                "FROM column_lineage"
            )
        }
        second_tests = {
            str(row["name"]): dict(row)
            for row in db.fetch(
                "SELECT id, file_id, model_id, name, line_start, line_end, snapshot_hash FROM tests"
            )
        }
        second_test_references = {
            (int(row["test_id"]), str(row["qualified_name"]))
            for row in db.fetch(
                "SELECT tr.test_id, c.qualified_name FROM test_references tr "
                "INNER JOIN columns c ON c.id = tr.column_id"
            )
        }
        directories = sorted(str(row["path"]) for row in db.fetch("SELECT path FROM directories"))
        config = db.fetch(
            "SELECT directory_id, language, normalized_path, is_test, is_config "
            "FROM files WHERE path = ?",
            ("config.yaml",),
        )[0]
        waiter = db.fetch(
            "SELECT id, language, normalized_path, is_test, is_config FROM files WHERE path = ?",
            ("models/waiters.py",),
        )[0]
        customer = db.fetch(
            "SELECT id, language, normalized_path, is_test, is_config FROM files WHERE path = ?",
            ("models/customers.sql",),
        )[0]
        orders = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("models/orders.sql",),
        )[0]
        raw_seed = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("models/raw_seed.sql",),
        )[0]
        external = db.fetch(
            "SELECT id, is_test, is_config FROM files WHERE path = ?",
            ("external_models.yaml",),
        )[0]
        test_orders = db.fetch(
            "SELECT id, is_test, is_config FROM files WHERE path = ?",
            ("tests/test_orders.yaml",),
        )[0]
        jinja_macro_file = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("macros/cents_to_dollars.sql",),
        )[0]
        python_macro_file = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("macros/identity.py",),
        )[0]
        audit_file = db.fetch(
            "SELECT id FROM files WHERE path = ?",
            ("audits/not_null_customer_id.sql",),
        )[0]
        file_count = db.fetch("SELECT COUNT(*) AS file_count FROM files")[0]["file_count"]
    finally:
        processor.close()
        db.close()
    assert directories == ["audits", "macros", "models", "seeds", "tests"]
    assert config["directory_id"] is None
    assert config["language"] == "yaml"
    assert config["normalized_path"] == "config"
    assert config["is_test"] == 0
    assert config["is_config"] == 1
    assert waiter["language"] == "python"
    assert waiter["normalized_path"] == "models.waiters"
    assert waiter["is_test"] == 0
    assert waiter["is_config"] == 0
    assert customer["language"] == "sql"
    assert customer["normalized_path"] == "models/customers"
    assert customer["is_test"] == 0
    assert customer["is_config"] == 0
    assert external["is_test"] == 0
    assert external["is_config"] == 0
    assert test_orders["is_test"] == 1
    assert test_orders["is_config"] == 0
    assert file_count == 14
    assert set(first_projects) == {"sushi"}
    assert set(first_gateways) == {"local"}
    assert first_gateways["local"]["project_id"] == first_projects["sushi"]["id"]
    assert first_gateways["local"]["catalog_name"] == "memory"
    assert first_gateways["local"]["dialect"] == "duckdb"
    assert first_gateways["local"]["is_default"] == 1
    assert first_gateways["local"]["snapshot_hash"]
    assert second_projects == first_projects
    assert second_gateways == first_gateways
    assert set(first_models) == {
        CUSTOMERS_FQN,
        CUSTOMER_ORDERS_FQN,
        CUSTOMER_STATUS_FQN,
        ORDERS_FQN,
        WAITERS_FQN,
        RAW_SEED_FQN,
        RAW_CUSTOMERS_FQN,
        RAW_ORDERS_FQN,
    }
    assert first_models[CUSTOMERS_FQN]["kind"] == "FULL"
    assert first_models[CUSTOMERS_FQN]["time_column"] is None
    assert first_models[CUSTOMERS_FQN]["grain"] is None
    assert first_models[CUSTOMERS_FQN]["file_id"] == customer["id"]
    assert first_models[CUSTOMERS_FQN]["gateway_id"] == first_gateways["local"]["id"]
    assert first_models[CUSTOMERS_FQN]["dialect"] == "duckdb"
    assert first_models[CUSTOMERS_FQN]["config_start_line"] == 1
    assert first_models[CUSTOMERS_FQN]["config_end_line"] == 9
    assert first_models[CUSTOMERS_FQN]["description"] == "Customer grain with order amounts"
    assert first_models[CUSTOMERS_FQN]["snapshot_hash"]
    assert first_models[CUSTOMERS_FQN]["data_hash"]
    assert first_models[CUSTOMERS_FQN]["metadata_hash"]
    assert first_models[ORDERS_FQN]["kind"] == "INCREMENTAL_BY_TIME_RANGE"
    assert first_models[ORDERS_FQN]["time_column"] == "order_id"
    assert first_models[ORDERS_FQN]["grain"] is None
    assert first_models[ORDERS_FQN]["description"] is None
    assert first_models[ORDERS_FQN]["file_id"] == orders["id"]
    assert first_models[ORDERS_FQN]["gateway_id"] == first_gateways["local"]["id"]
    assert first_models[ORDERS_FQN]["dialect"] == "duckdb"
    assert first_models[ORDERS_FQN]["config_start_line"] == 1
    assert first_models[ORDERS_FQN]["config_end_line"] == 7
    assert first_models[WAITERS_FQN]["kind"] == "FULL"
    assert first_models[WAITERS_FQN]["file_id"] == waiter["id"]
    assert first_models[WAITERS_FQN]["gateway_id"] == first_gateways["local"]["id"]
    assert first_models[WAITERS_FQN]["dialect"] == "duckdb"
    assert first_models[WAITERS_FQN]["config_start_line"] == 4
    assert first_models[WAITERS_FQN]["config_end_line"] == 10
    assert first_models[RAW_SEED_FQN]["kind"] == "SEED"
    assert first_models[RAW_SEED_FQN]["file_id"] == raw_seed["id"]
    assert first_models[RAW_SEED_FQN]["config_start_line"] == 1
    assert first_models[RAW_SEED_FQN]["config_end_line"] == 6
    assert first_models[RAW_CUSTOMERS_FQN]["kind"] == "EXTERNAL"
    assert first_models[RAW_CUSTOMERS_FQN]["file_id"] == external["id"]
    assert first_models[RAW_CUSTOMERS_FQN]["config_start_line"] == 1
    assert first_models[RAW_CUSTOMERS_FQN]["config_end_line"] == 4
    assert first_models[RAW_ORDERS_FQN]["kind"] == "EXTERNAL"
    assert first_models[RAW_ORDERS_FQN]["file_id"] == external["id"]
    assert first_models[RAW_ORDERS_FQN]["config_start_line"] == 5
    assert first_models[RAW_ORDERS_FQN]["config_end_line"] == 9
    assert first_models[CUSTOMER_ORDERS_FQN]["config_start_line"] == 1
    assert first_models[CUSTOMER_ORDERS_FQN]["config_end_line"] == 4
    assert all(
        row["gateway_id"] == first_gateways["local"]["id"] and row["dialect"] == "duckdb"
        for row in first_models.values()
    )
    assert second_models == first_models
    assert first_models[CUSTOMERS_FQN]["schema_name"] == "sushi"
    assert first_models[RAW_CUSTOMERS_FQN]["schema_name"] == "raw"
    assert first_models[RAW_SEED_FQN]["schema_name"] == "sushi"
    assert first_models[CUSTOMERS_FQN]["qualified_name"] == CUSTOMERS_FQN
    assert '"' not in first_models[CUSTOMERS_FQN]["qualified_name"]
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["query_name"] == f"{CUSTOMERS_FQN}/$"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["name"] == "customer_id"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["description"] == "Customer identifier"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["data_type"] == "INT"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["nullable"] == 0
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["unique_constraint"] == 1
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["is_select"] == 1
    assert first_columns[f"{ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id"]["is_select"] == 0
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["snapshot_hash"]
    assert first_columns[CUSTOMERS_CTE_AMOUNT]["description"] == "Order amount in dollars"
    assert first_columns[CUSTOMERS_CTE_AMOUNT]["data_type"] == "DOUBLE"
    assert first_columns[CUSTOMERS_CTE_AMOUNT]["nullable"] == 1
    assert first_columns[CUSTOMERS_CTE_AMOUNT]["unique_constraint"] == 0
    assert first_columns[CUSTOMERS_CTE_STATUS]["description"] == "Customer status"
    assert first_columns[CUSTOMERS_CTE_STATUS]["data_type"] == "TEXT"
    assert first_columns[CUSTOMERS_CTE_STATUS]["nullable"] == 1
    assert first_columns[CUSTOMERS_CTE_STATUS]["unique_constraint"] == 0
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["description"] is None
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["data_type"] == "INT"
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["nullable"] is None
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["unique_constraint"] is None
    assert first_columns[CUSTOMERS_CTE_RAW_AMOUNT_CENTS]["data_type"] == "INT"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["model_id"] == first_models[CUSTOMERS_FQN]["id"]
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["query_name"] == (f"{CUSTOMERS_FQN}/$cte")
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["from_table"] == RAW_CUSTOMERS_FQN
    assert first_columns[CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID]["from_table"] == (RAW_ORDERS_FQN)
    assert first_columns[CUSTOMERS_CTE_RAW_STATUS]["name"] == "status"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["from_table"] == "$cte"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["column_name"] == "$cte.customer_id"
    assert first_columns[f"{RAW_CUSTOMERS_FQN}/$/customer_id"]["column_name"] == "customer_id"
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["line_start"] == 12
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["line_end"] == 12
    assert first_columns[CUSTOMERS_CTE_AMOUNT]["line_start"] == 14
    assert first_columns[CUSTOMERS_CTE_AMOUNT]["line_end"] == 15
    assert first_columns[CUSTOMERS_CTE_STATUS]["line_start"] == 16
    assert first_columns[CUSTOMERS_CTE_STATUS]["line_end"] == 16
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["line_start"] == 3
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["line_end"] == 3
    assert first_columns[CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID]["line_start"] == 4
    assert first_columns[CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID]["line_end"] == 4
    assert first_columns[CUSTOMERS_CTE_RAW_STATUS]["line_start"] == 5
    assert first_columns[CUSTOMERS_CTE_RAW_STATUS]["line_end"] == 5
    assert first_columns[CUSTOMERS_CTE_RAW_AMOUNT_CENTS]["line_start"] == 6
    assert first_columns[CUSTOMERS_CTE_RAW_AMOUNT_CENTS]["line_end"] == 6
    assert first_columns[CUSTOMERS_CTE_RAW_AMOUNT_CENTS]["from_table"] == (RAW_ORDERS_FQN)
    assert first_columns[f"{RAW_CUSTOMERS_FQN}/$/customer_id"]["from_table"] is None
    assert (
        first_columns[f"{RAW_CUSTOMERS_FQN}/$/customer_id"]["query_name"]
        == f"{RAW_CUSTOMERS_FQN}/$"
    )
    assert (
        first_columns[f"{RAW_CUSTOMERS_FQN}/$/customer_id"]["model_id"]
        == first_models[RAW_CUSTOMERS_FQN]["id"]
    )
    assert second_columns == first_columns
    customers_id = first_models[CUSTOMERS_FQN]["id"]
    status_id = first_models[CUSTOMER_STATUS_FQN]["id"]
    customers_root = first_queries[(customers_id, "$")]
    customers_cte = first_queries[(customers_id, "$cte")]
    assert customers_root["depth"] == 0
    assert customers_root["line_start"] == 12
    assert customers_root["line_end"] == 17
    assert customers_root["file_id"] == customer["id"]
    assert customers_root["model_id"] == customers_id
    assert customers_root["snapshot_hash"]
    assert customers_root["select_col_count"] == 3
    assert customers_root["select_expr_count"] == 1
    assert customers_root["select_alias_count"] == 0
    assert customers_root["where_condition_count"] == 0
    assert customers_root["join_statement_count"] == 0
    assert customers_root["group_by_col_count"] == 0
    assert customers_root["having_condition_count"] == 0
    assert customers_root["order_by_col_count"] == 0
    assert customers_cte["depth"] == 1
    assert customers_cte["line_start"] == 1
    assert customers_cte["line_end"] == 9
    assert customers_cte["select_col_count"] == 4
    assert customers_cte["select_expr_count"] == 0
    assert customers_cte["select_alias_count"] == 0
    assert customers_cte["where_condition_count"] == 0
    assert customers_cte["join_statement_count"] == 1
    assert customers_cte["group_by_col_count"] == 0
    customer_orders = first_queries[(first_models[CUSTOMER_ORDERS_FQN]["id"], "$")]
    assert customer_orders["select_col_count"] == 3
    assert customer_orders["where_condition_count"] == 1
    assert customer_orders["join_statement_count"] == 1
    assert customer_orders["group_by_col_count"] == 3
    assert customers_cte["file_id"] == customer["id"]
    assert first_queries[(status_id, "$base")]["depth"] == 1
    assert first_queries[(status_id, "$base")]["select_col_count"] == 2
    assert first_queries[(status_id, "$base")]["select_alias_count"] == 1
    assert first_queries[(status_id, "$filtered")]["depth"] == 1
    assert first_queries[(status_id, "$filtered")]["select_col_count"] == 2
    assert first_queries[(status_id, "$filtered")]["select_alias_count"] == 1
    assert first_queries[(status_id, "$filtered")]["where_condition_count"] == 1
    assert first_queries[(status_id, "$filtered")]["join_statement_count"] == 0
    assert first_queries[(status_id, "$filtered")]["group_by_col_count"] == 0
    assert first_queries[(status_id, "$")]["depth"] == 0
    assert first_queries[(status_id, "$")]["line_start"] == 21
    assert first_queries[(status_id, "$")]["line_end"] == 23
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["query_id"] == customers_root["id"]
    assert first_columns[CUSTOMERS_CTE_CUSTOMER_ID]["file_id"] == customer["id"]
    assert first_columns[CUSTOMERS_CTE_RAW_CUSTOMER_ID]["query_id"] == customers_cte["id"]
    assert second_queries == first_queries
    assert set(first_macros) == {"cents_to_dollars", "identity"}
    assert first_macros["cents_to_dollars"]["kind"] == "jinja"
    assert first_macros["cents_to_dollars"]["file_id"] == jinja_macro_file["id"]
    assert first_macros["cents_to_dollars"]["line_start"] == 1
    assert first_macros["cents_to_dollars"]["line_end"] == 3
    assert first_macros["cents_to_dollars"]["snapshot_hash"]
    assert first_macros["identity"]["kind"] == "python"
    assert first_macros["identity"]["file_id"] == python_macro_file["id"]
    assert first_macros["identity"]["line_start"] == 4
    assert first_macros["identity"]["line_end"] == 6
    assert first_macros["identity"]["snapshot_hash"]
    assert "star" not in first_macros
    assert second_macros == first_macros
    assert first_model_macros == {("cents_to_dollars", first_models[CUSTOMERS_FQN]["id"])}
    assert second_model_macros == first_model_macros
    assert set(first_audits) == {"not_null_customer_id"}
    assert first_audits["not_null_customer_id"]["file_id"] == audit_file["id"]
    assert first_audits["not_null_customer_id"]["line_start"] == 1
    assert first_audits["not_null_customer_id"]["line_end"] == 7
    assert first_audits["not_null_customer_id"]["snapshot_hash"]
    assert second_audits == first_audits
    assert first_model_audits == {("not_null_customer_id", first_models[CUSTOMERS_FQN]["id"])}
    assert second_model_audits == first_model_audits
    assert set(first_tests) == {
        "test_orders_exist",
        "test_orders_csv",
        "test_orders_query",
    }
    assert first_tests["test_orders_exist"]["file_id"] == test_orders["id"]
    assert first_tests["test_orders_exist"]["model_id"] == first_models[ORDERS_FQN]["id"]
    assert first_tests["test_orders_exist"]["line_start"] == 1
    assert first_tests["test_orders_exist"]["line_end"] == 13
    assert first_tests["test_orders_exist"]["snapshot_hash"]
    assert first_tests["test_orders_csv"]["file_id"] == test_orders["id"]
    assert first_tests["test_orders_csv"]["model_id"] == first_models[ORDERS_FQN]["id"]
    assert first_tests["test_orders_csv"]["line_start"] == 14
    assert first_tests["test_orders_csv"]["line_end"] == 31
    assert first_tests["test_orders_query"]["file_id"] == test_orders["id"]
    assert first_tests["test_orders_query"]["model_id"] == first_models[ORDERS_FQN]["id"]
    assert first_tests["test_orders_query"]["line_start"] == 32
    assert first_tests["test_orders_query"]["line_end"] == 41
    assert second_tests == first_tests
    test_orders_id = first_tests["test_orders_exist"]["id"]
    test_orders_csv_id = first_tests["test_orders_csv"]["id"]
    test_orders_query_id = first_tests["test_orders_query"]["id"]
    assert first_test_references == {
        (test_orders_id, CUSTOMERS_CTE_CUSTOMER_ID),
        (test_orders_id, CUSTOMERS_CTE_STATUS),
        (test_orders_id, f"{ORDERS_FQN}/$/{RAW_ORDERS_FQN}.order_id"),
        (test_orders_id, f"{ORDERS_FQN}/$/customer_id"),
        (test_orders_csv_id, f"{RAW_ORDERS_FQN}/$/order_id"),
        (test_orders_csv_id, f"{RAW_ORDERS_FQN}/$/customer_id"),
        (test_orders_csv_id, CUSTOMERS_CTE_CUSTOMER_ID),
        (test_orders_csv_id, CUSTOMERS_CTE_STATUS),
        (test_orders_csv_id, f"{ORDERS_FQN}/$/{RAW_ORDERS_FQN}.order_id"),
        (test_orders_csv_id, f"{ORDERS_FQN}/$/customer_id"),
        (test_orders_query_id, f"{RAW_ORDERS_FQN}/$/order_id"),
        (test_orders_query_id, f"{RAW_ORDERS_FQN}/$/customer_id"),
        (test_orders_query_id, CUSTOMERS_CTE_CUSTOMER_ID),
        (test_orders_query_id, CUSTOMERS_CTE_STATUS),
        (test_orders_query_id, f"{ORDERS_FQN}/$/{RAW_ORDERS_FQN}.order_id"),
        (test_orders_query_id, f"{ORDERS_FQN}/$/customer_id"),
    }
    assert second_test_references == first_test_references
    customer_id_ref = first_references[
        (
            CUSTOMERS_CTE_CUSTOMER_ID,
            CUSTOMERS_CTE_RAW_CUSTOMER_ID,
            3,
            12,
            "select",
        )
    ]
    assert customer_id_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$"
    assert customer_id_ref["source_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    amount_ref = first_references[
        (
            CUSTOMERS_CTE_AMOUNT,
            CUSTOMERS_CTE_RAW_AMOUNT_CENTS,
            6,
            15,
            "expression",
        )
    ]
    assert amount_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$"
    assert amount_ref["source_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    assert "/ 100" in str(amount_ref["ref_context"])
    cte_amount_ref = first_references[
        (
            CUSTOMERS_CTE_RAW_AMOUNT_CENTS,
            f"{RAW_ORDERS_FQN}/$/amount_cents",
            6,
            6,
            "select",
        )
    ]
    assert cte_amount_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    assert cte_amount_ref["source_query_name"] == f"{RAW_ORDERS_FQN}/$"
    cte_customer_ref = first_references[
        (
            CUSTOMERS_CTE_RAW_CUSTOMER_ID,
            f"{RAW_CUSTOMERS_FQN}/$/customer_id",
            3,
            3,
            "select",
        )
    ]
    assert cte_customer_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    assert cte_customer_ref["source_query_name"] == f"{RAW_CUSTOMERS_FQN}/$"
    cte_orders_customer_ref = first_references[
        (
            CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID,
            f"{RAW_ORDERS_FQN}/$/customer_id",
            4,
            4,
            "select",
        )
    ]
    assert cte_orders_customer_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    assert cte_orders_customer_ref["source_query_name"] == f"{RAW_ORDERS_FQN}/$"
    assert second_references == first_references
    assert all(
        row["ref_column_model_id"] == first_models[CUSTOMERS_FQN]["id"]
        for row in first_references.values()
        if str(row["ref_column_qualified_name"]).startswith(f"{CUSTOMERS_FQN}/")
    )
    assert all(row["source_column_id"] is not None for row in first_references.values())
    assert all("?" not in str(row["ref_context"]) for row in first_references.values())
    assert all(
        "?" not in str(row["source_column_qualified_name"]) for row in first_references.values()
    )
    customer_orders_customer_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id",
            CUSTOMERS_CTE_CUSTOMER_ID,
            10,
            7,
            "select",
        )
    ]
    assert customer_orders_customer_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    customer_orders_status_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.status",
            CUSTOMERS_CTE_STATUS,
            10,
            8,
            "select",
        )
    ]
    assert customer_orders_status_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    customer_orders_order_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{ORDERS_FQN}.order_id",
            f"{ORDERS_FQN}/$/{RAW_ORDERS_FQN}.order_id",
            11,
            9,
            "select",
        )
    ]
    assert customer_orders_order_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    assert (
        first_columns[f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id"]["query_name"]
        == f"{CUSTOMER_ORDERS_FQN}/$"
    )
    assert (
        first_columns[f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id"]["from_table"]
        == CUSTOMERS_FQN
    )
    assert (
        first_columns[f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.status"]["query_name"]
        == f"{CUSTOMER_ORDERS_FQN}/$"
    )
    assert first_columns[f"{CUSTOMER_ORDERS_FQN}/$/{ORDERS_FQN}.order_id"]["from_table"] == (
        ORDERS_FQN
    )
    join_customers_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id",
            CUSTOMERS_CTE_CUSTOMER_ID,
            12,
            12,
            "join",
        )
    ]
    assert join_customers_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    join_orders_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{ORDERS_FQN}.customer_id",
            f"{ORDERS_FQN}/$/customer_id",
            12,
            12,
            "join",
        )
    ]
    assert join_orders_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    where_status_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.status",
            CUSTOMERS_CTE_STATUS,
            13,
            13,
            "where",
        )
    ]
    assert where_status_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    group_customer_ref = first_references[
        (
            f"{CUSTOMER_ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id",
            CUSTOMERS_CTE_CUSTOMER_ID,
            15,
            15,
            "group",
        )
    ]
    assert group_customer_ref["ref_column_query_name"] == f"{CUSTOMER_ORDERS_FQN}/$"
    orders_join_ref = first_references[
        (
            f"{ORDERS_FQN}/$/{CUSTOMERS_FQN}.customer_id",
            CUSTOMERS_CTE_CUSTOMER_ID,
            14,
            14,
            "join",
        )
    ]
    assert orders_join_ref["ref_column_query_name"] == f"{ORDERS_FQN}/$"
    cte_join_customers_ref = first_references[
        (
            CUSTOMERS_CTE_RAW_CUSTOMER_ID,
            f"{RAW_CUSTOMERS_FQN}/$/customer_id",
            9,
            9,
            "join",
        )
    ]
    assert cte_join_customers_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    cte_join_orders_ref = first_references[
        (
            CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID,
            f"{RAW_ORDERS_FQN}/$/customer_id",
            9,
            9,
            "join",
        )
    ]
    assert cte_join_orders_ref["ref_column_query_name"] == f"{CUSTOMERS_FQN}/$cte"
    assert first_models[CUSTOMER_STATUS_FQN]["kind"] == "FULL"
    assert first_models[CUSTOMER_STATUS_FQN]["description"] == (
        "Nested CTE chain over raw customers"
    )
    assert first_columns[f"{CUSTOMER_STATUS_FQN}/$base/{RAW_CUSTOMERS_FQN}.id"]["query_name"] == (
        f"{CUSTOMER_STATUS_FQN}/$base"
    )
    assert first_columns[f"{CUSTOMER_STATUS_FQN}/$base/{RAW_CUSTOMERS_FQN}.id"]["from_table"] == (
        RAW_CUSTOMERS_FQN
    )
    assert first_columns[f"{CUSTOMER_STATUS_FQN}/$filtered/$base.customer_id"]["query_name"] == (
        f"{CUSTOMER_STATUS_FQN}/$filtered"
    )
    assert (
        first_columns[f"{CUSTOMER_STATUS_FQN}/$filtered/$base.customer_id"]["from_table"] == "$base"
    )
    assert first_columns[f"{CUSTOMER_STATUS_FQN}/$/$filtered.customer_id"]["query_name"] == (
        f"{CUSTOMER_STATUS_FQN}/$"
    )
    assert (
        first_columns[f"{CUSTOMER_STATUS_FQN}/$filtered/$base.status"]["query_name"]
        == f"{CUSTOMER_STATUS_FQN}/$filtered"
    )
    nested_base_customer_ref = first_references[
        (
            f"{CUSTOMER_STATUS_FQN}/$base/{RAW_CUSTOMERS_FQN}.id",
            f"{RAW_CUSTOMERS_FQN}/$/customer_id",
            9,
            9,
            "alias",
        )
    ]
    assert nested_base_customer_ref["ref_column_query_name"] == f"{CUSTOMER_STATUS_FQN}/$base"
    nested_filtered_customer_ref = first_references[
        (
            f"{CUSTOMER_STATUS_FQN}/$filtered/$base.customer_id",
            f"{CUSTOMER_STATUS_FQN}/$base/{RAW_CUSTOMERS_FQN}.id",
            15,
            15,
            "alias",
        )
    ]
    assert nested_filtered_customer_ref["ref_column_query_name"] == (
        f"{CUSTOMER_STATUS_FQN}/$filtered"
    )
    assert nested_filtered_customer_ref["source_query_name"] == f"{CUSTOMER_STATUS_FQN}/$base"
    nested_outer_customer_ref = first_references[
        (
            f"{CUSTOMER_STATUS_FQN}/$/$filtered.customer_id",
            f"{CUSTOMER_STATUS_FQN}/$filtered/$base.customer_id",
            15,
            21,
            "select",
        )
    ]
    assert nested_outer_customer_ref["ref_column_query_name"] == f"{CUSTOMER_STATUS_FQN}/$"
    assert nested_outer_customer_ref["source_query_name"] == f"{CUSTOMER_STATUS_FQN}/$filtered"
    nested_where_ref = first_references[
        (
            f"{CUSTOMER_STATUS_FQN}/$filtered/$base.status",
            f"{CUSTOMER_STATUS_FQN}/$base/{RAW_CUSTOMERS_FQN}.status",
            18,
            18,
            "where",
        )
    ]
    assert nested_where_ref["ref_column_query_name"] == f"{CUSTOMER_STATUS_FQN}/$filtered"


def test_processor_drops_models_when_their_files_disappear(tmp_path: Path) -> None:
    root = tmp_path / "sushi"
    shutil.copytree(FIXTURE_PROJECT, root)
    db = ProjectDB(root)
    processor = ProjectProcessor(db, root)
    try:
        processor.process(full=True)
        before = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM models")
        }
        before_columns = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM columns")
        }
        before_macros = {str(row["name"]) for row in db.fetch("SELECT name FROM macros")}
        before_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        before_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
        }
        before_references = {
            str(row["ref_column_qualified_name"])
            for row in db.fetch("SELECT ref_column_qualified_name FROM column_lineage")
        }
        customers_model_id = db.fetch(
            "SELECT id FROM models WHERE qualified_name = ?",
            (CUSTOMERS_FQN,),
        )[0]["id"]
        (root / "models" / "customers.sql").unlink()
        (root / "macros" / "cents_to_dollars.sql").unlink()
        processor.process()
        after = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM models")
        }
        after_columns = {
            str(row["qualified_name"]) for row in db.fetch("SELECT qualified_name FROM columns")
        }
        after_macros = {str(row["name"]) for row in db.fetch("SELECT name FROM macros")}
        after_model_macros = {
            (str(row["macro_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT macro_name, model_id FROM model_macros")
        }
        after_model_audits = {
            (str(row["audit_name"]), int(row["model_id"]))
            for row in db.fetch("SELECT audit_name, model_id FROM model_audits")
        }
        after_references = {
            str(row["ref_column_qualified_name"])
            for row in db.fetch("SELECT ref_column_qualified_name FROM column_lineage")
        }
    finally:
        processor.close()
        db.close()
    assert CUSTOMERS_FQN in before
    assert after == {
        CUSTOMER_ORDERS_FQN,
        CUSTOMER_STATUS_FQN,
        ORDERS_FQN,
        WAITERS_FQN,
        RAW_SEED_FQN,
        RAW_CUSTOMERS_FQN,
        RAW_ORDERS_FQN,
    }
    assert CUSTOMERS_CTE_CUSTOMER_ID in before_columns
    assert CUSTOMERS_CTE_RAW_CUSTOMER_ID in before_columns
    assert CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID in before_columns
    assert CUSTOMERS_CTE_CUSTOMER_ID not in after_columns
    assert CUSTOMERS_CTE_RAW_CUSTOMER_ID not in after_columns
    assert f"{RAW_CUSTOMERS_FQN}/$/customer_id" in after_columns
    assert "cents_to_dollars" in before_macros
    assert "cents_to_dollars" not in after_macros
    assert ("cents_to_dollars", customers_model_id) in before_model_macros
    assert after_model_macros == set()
    assert ("not_null_customer_id", customers_model_id) in before_model_audits
    assert after_model_audits == set()
    assert CUSTOMERS_CTE_CUSTOMER_ID in before_references
    assert CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID in before_references
    assert CUSTOMERS_CTE_CUSTOMER_ID not in after_references
    assert CUSTOMERS_CTE_RAW_ORDERS_CUSTOMER_ID not in after_references


def test_processor_records_plain_files_and_drops_deleted_ones(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "config.yaml").write_text(
        "gateways:\n  local:\n    connection:\n      type: duckdb\n"
        "default_gateway: local\nmodel_defaults:\n  dialect: duckdb\n",
        encoding="utf-8",
    )
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
    processor = ProjectProcessor(db, root)
    try:
        processor.process(full=True)
        paths = {
            str(row["path"]): row["language"]
            for row in db.fetch("SELECT path, language FROM files")
        }
        model_count = db.fetch("SELECT COUNT(*) AS model_count FROM models")[0]["model_count"]
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
        processor.process()
        remaining = {str(row["path"]) for row in db.fetch("SELECT path FROM files")}
        remaining_dirs = {str(row["path"]) for row in db.fetch("SELECT path FROM directories")}
        updated = db.fetch("SELECT line_count FROM files WHERE path = ?", ("pkg/worker.py",))[0]
    finally:
        blocked.chmod(0o644)
        processor.close()
        db.close()
    assert directories == ["notes", "pkg", "src", "src/fundamentals"]
    assert paths["README.md"] is None
    assert paths["config.yaml"] == "yaml"
    assert paths["settings.yml"] == "yaml"
    assert paths["LICENSE"] is None
    assert paths["notes/keep.txt"] is None
    assert paths["pkg/worker.py"] == "python"
    assert paths["pkg/__init__.py"] == "python"
    assert model_count == 0
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
        "config.yaml",
        "pkg/__init__.py",
        "pkg/worker.py",
        "settings.yml",
        "src/app.py",
        "src/fundamentals/__init__.py",
        "src/fundamentals/xxx.py",
    }
    assert remaining_dirs == {"pkg", "src", "src/fundamentals"}
    assert int(updated["line_count"]) == 3
