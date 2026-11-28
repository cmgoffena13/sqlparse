import sqlite3
from pathlib import Path
from typing import TypedDict

from src.utils import db_path_for_index_root, get_sqlparse_config_dir

BATCH_TABLES = {
    "directories",
    "files",
    "projects",
    "project_gateways",
    "models",
    "macros",
    "model_macros",
    "audits",
    "model_audits",
    "queries",
    "columns",
    "column_lineage",
    "tests",
    "test_references",
    "search_docs",
}

ASSIGNER_TABLES = {
    "directories",
    "files",
    "projects",
    "project_gateways",
    "models",
    "macros",
    "audits",
    "queries",
    "columns",
    "column_lineage",
    "tests",
}


class DirectorySnapshot(TypedDict):
    id: int
    seen: bool


class FileSnapshot(TypedDict):
    id: int
    directory_id: int | None
    seen: bool
    content_hash: str
    mtime_ns: int
    size_bytes: int


class ProjectSnapshot(TypedDict):
    id: int
    name: str
    seen: bool


class ProjectGatewaySnapshot(TypedDict):
    id: int
    snapshot_hash: str
    seen: bool


class ModelSnapshot(TypedDict):
    id: int
    snapshot_hash: str
    data_hash: str
    metadata_hash: str
    direct_dependencies_count: int
    direct_dependents_count: int
    seen: bool


class QuerySnapshot(TypedDict):
    id: int
    model_id: int
    name: str
    qualified_name: str
    line_start: int | None
    line_end: int | None
    snapshot_hash: str
    seen: bool


class ColumnSnapshot(TypedDict):
    id: int
    model_id: int
    snapshot_hash: str
    seen: bool


class MacroSnapshot(TypedDict):
    id: int
    snapshot_hash: str
    seen: bool


class ModelMacroSnapshot(TypedDict):
    macro_name: str
    model_id: int
    query_id: int
    seen: bool


class AuditSnapshot(TypedDict):
    id: int
    snapshot_hash: str
    seen: bool


class ModelAuditSnapshot(TypedDict):
    audit_name: str
    model_id: int
    seen: bool


class ColumnLineageSnapshot(TypedDict):
    id: int
    ref_column_model_id: int
    snapshot_hash: str
    seen: bool


class TestSnapshot(TypedDict):
    id: int
    snapshot_hash: str
    seen: bool


class TestReferenceSnapshot(TypedDict):
    test_id: int
    column_id: int
    seen: bool


class SearchDocSnapshot(TypedDict):
    id: int
    model_name: str
    snapshot_hash: str
    seen: bool


def index_workspace_paths() -> list[tuple[Path, Path]]:
    records: list[tuple[Path, Path]] = []
    for db_file in sorted(get_sqlparse_config_dir("indexes").glob("*.db")):
        connection = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row: sqlite3.Row | None = None
        try:
            row = connection.execute("SELECT path FROM index_root WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            row = None
        finally:
            connection.close()
        if row is not None and row["path"]:
            records.append((db_file, Path(str(row["path"]))))
    return records


def _remove_db_sidecars(db_file: Path) -> None:
    db_file.unlink(missing_ok=True)
    db_file.with_suffix(".db-wal").unlink(missing_ok=True)
    db_file.with_suffix(".db-shm").unlink(missing_ok=True)


def remove_index_files() -> None:
    for db_file in sorted(get_sqlparse_config_dir("indexes").glob("*.db")):
        _remove_db_sidecars(db_file)
    print("Removed all index files.")


def cleanup_orphan_indexes() -> list[Path]:
    removed: list[Path] = []
    for db_file, root in index_workspace_paths():
        if not root.is_dir():
            print(f"Removing index for missing workspace {root}")
            _remove_db_sidecars(db_file)
            removed.append(db_file)
    if not removed:
        print("No orphan indexes found.")
    return removed


class ProjectDB:
    def __init__(self, root: Path, *, apply_schema: bool = True):
        self.root = root.resolve()
        self.db_file = db_path_for_index_root(self.root)
        self.connection = sqlite3.connect(str(self.db_file), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        if apply_schema:
            self._apply_schema()
            self._store_index_root()

    def _store_index_root(self) -> None:
        self.exec_tran(
            "INSERT OR REPLACE INTO index_root (id, path) VALUES (1, ?)",
            (str(self.root),),
        )

    def _script(self, name: str) -> None:
        path = Path(__file__).resolve().parent / name
        self.connection.executescript(path.read_text(encoding="utf-8"))

    def _apply_schema(self) -> None:
        self._script("schema.sql")

    def recreate_schema(self) -> None:
        self._script("drop_schema.sql")
        self._apply_schema()
        self._store_index_root()

    def exec_tran(self, query: str, params: tuple[object, ...]) -> None:
        try:
            self.connection.execute(query, params)
            self.connection.commit()
        except sqlite3.Error:
            self.connection.rollback()
            raise

    def fetch(self, query: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(query, params))

    def table_max_id(self, table: str) -> int:
        if table not in ASSIGNER_TABLES:
            raise ValueError(f"unsupported table: {table}")
        query = f"SELECT COALESCE(MAX(id), 0) AS max_id FROM {table}"  # noqa: S608
        row = self.connection.execute(query).fetchone()
        return 0 if row is None else int(row["max_id"])

    def delete_ids(self, table: str, ids: list[int]) -> None:
        if not ids:
            return
        if table not in ASSIGNER_TABLES:
            raise ValueError(f"unsupported table for delete_ids: {table}")
        placeholders = ",".join(["?"] * len(ids))
        query = f"DELETE FROM {table} WHERE id IN ({placeholders})"  # noqa: S608
        self.exec_tran(query, tuple(ids))

    def get_directories_snapshot(self) -> dict[str, DirectorySnapshot]:
        cursor = self.connection.execute("SELECT id, path FROM directories")
        return {str(row["path"]): {"id": int(row["id"]), "seen": False} for row in cursor}

    def delete_directories(self, directories: dict[str, DirectorySnapshot]) -> None:
        dir_ids = [row["id"] for row in directories.values() if not row["seen"]]
        self.delete_ids("directories", dir_ids)

    def get_files_snapshot(self) -> dict[str, FileSnapshot]:
        cursor = self.connection.execute(
            "SELECT id, directory_id, path, content_hash, mtime_ns, size_bytes FROM files"
        )
        return {str(row["path"]): self._file_snapshot(row) for row in cursor}

    def delete_files(self, files: dict[str, FileSnapshot]) -> None:
        file_ids = [row["id"] for row in files.values() if not row["seen"]]
        self.delete_ids("files", file_ids)

    def get_projects_snapshot(self) -> dict[str, ProjectSnapshot]:
        cursor = self.connection.execute("SELECT id, name FROM projects")
        return {str(row["name"]): self._project_snapshot(row) for row in cursor}

    def delete_projects(self, projects: dict[str, ProjectSnapshot]) -> None:
        project_ids = [row["id"] for row in projects.values() if not row["seen"]]
        self.delete_ids("projects", project_ids)

    def get_project_gateways_snapshot(self) -> dict[str, ProjectGatewaySnapshot]:
        cursor = self.connection.execute(
            "SELECT id, project_id, name, snapshot_hash FROM project_gateways"
        )
        return {
            f"{row['project_id']}:{row['name']}": self._project_gateway_snapshot(row)
            for row in cursor
        }

    def delete_project_gateways(self, gateways: dict[str, ProjectGatewaySnapshot]) -> None:
        gateway_ids = [row["id"] for row in gateways.values() if not row["seen"]]
        self.delete_ids("project_gateways", gateway_ids)

    def get_models_snapshot(self) -> dict[str, ModelSnapshot]:
        cursor = self.connection.execute(
            """
            SELECT
                id,
                qualified_name,
                snapshot_hash,
                data_hash,
                metadata_hash,
                direct_dependencies_count,
                direct_dependents_count
            FROM models
            """
        )
        return {str(row["qualified_name"]): self._model_snapshot(row) for row in cursor}

    def delete_models(self, models: dict[str, ModelSnapshot]) -> None:
        model_ids = [row["id"] for row in models.values() if not row["seen"]]
        self.delete_ids("models", model_ids)

    def update_model_relation_counts(self, model_ids: list[int]) -> None:
        if model_ids:
            placeholders = ",".join(["?"] * len(model_ids))
            params = tuple(model_ids)
            with self.connection:
                self.connection.execute(
                    f"""
                    WITH dependency_counts AS (
                        SELECT
                            ref_column_model_id AS model_id,
                            COUNT(DISTINCT source_models_id) AS dependencies_count
                        FROM column_lineage
                        WHERE ref_column_model_id != source_models_id
                            AND ref_column_model_id IN ({placeholders})
                        GROUP BY ref_column_model_id
                    ),
                    dependent_counts AS (
                        SELECT
                            source_models_id AS model_id,
                            COUNT(DISTINCT ref_column_model_id) AS dependents_count
                        FROM column_lineage
                        WHERE ref_column_model_id != source_models_id
                            AND source_models_id IN ({placeholders})
                        GROUP BY source_models_id
                    )
                    UPDATE models AS m
                    SET
                        direct_dependencies_count = IFNULL(dc.dependencies_count, 0),
                        direct_dependents_count = IFNULL(dt.dependents_count, 0)
                    FROM models AS targets
                    LEFT JOIN dependency_counts AS dc
                        ON dc.model_id = targets.id
                    LEFT JOIN dependent_counts AS dt
                        ON dt.model_id = targets.id
                    WHERE m.id = targets.id
                        AND targets.id IN ({placeholders})
                    """,  # noqa: S608
                    params + params + params,
                )

    def get_queries_snapshot(self) -> dict[str, QuerySnapshot]:
        cursor = self.connection.execute(
            """
            SELECT id, model_id, name, qualified_name, line_start, line_end, snapshot_hash
            FROM queries
            """
        )
        return {f"{row['model_id']}:{row['name']}": self._query_snapshot(row) for row in cursor}

    def delete_queries(self, queries: dict[str, QuerySnapshot]) -> None:
        query_ids = [row["id"] for row in queries.values() if not row["seen"]]
        self.delete_ids("queries", query_ids)

    def get_columns_snapshot(self) -> dict[str, ColumnSnapshot]:
        cursor = self.connection.execute(
            "SELECT id, model_id, qualified_name, snapshot_hash FROM columns"
        )
        return {str(row["qualified_name"]): self._column_snapshot(row) for row in cursor}

    def delete_columns(self, columns: dict[str, ColumnSnapshot]) -> None:
        column_ids = [row["id"] for row in columns.values() if not row["seen"]]
        self.delete_ids("columns", column_ids)

    def get_search_docs_snapshot(self) -> dict[str, SearchDocSnapshot]:
        cursor = self.connection.execute("SELECT id, model_name, snapshot_hash FROM search_docs")
        return {str(row["id"]): self._search_doc_snapshot(row) for row in cursor}

    def delete_search_docs(self, search_docs: dict[str, SearchDocSnapshot]) -> None:
        doc_ids = [row["id"] for row in search_docs.values() if not row["seen"]]
        if not doc_ids:
            return
        placeholders = ",".join(["?"] * len(doc_ids))
        with self.connection:
            self.connection.execute(
                f"DELETE FROM search_fts WHERE rowid IN ({placeholders})",  # noqa: S608
                doc_ids,
            )
            self.connection.execute(
                f"DELETE FROM search_docs WHERE id IN ({placeholders})",  # noqa: S608
                doc_ids,
            )

    def get_macros_snapshot(self) -> dict[str, MacroSnapshot]:
        cursor = self.connection.execute("SELECT id, name, snapshot_hash FROM macros")
        return {str(row["name"]): self._macro_snapshot(row) for row in cursor}

    def delete_macros(self, macros: dict[str, MacroSnapshot]) -> None:
        macro_ids = [row["id"] for row in macros.values() if not row["seen"]]
        self.delete_ids("macros", macro_ids)

    def get_model_macros_snapshot(self) -> dict[str, ModelMacroSnapshot]:
        cursor = self.connection.execute("SELECT macro_name, model_id, query_id FROM model_macros")
        return {
            f"{row['macro_name']}:{row['model_id']}:{row['query_id']}": self._model_macro_snapshot(
                row
            )
            for row in cursor
        }

    def delete_model_macros(self, model_macros: dict[str, ModelMacroSnapshot]) -> None:
        rows = [
            (row["macro_name"], row["model_id"], row["query_id"])
            for row in model_macros.values()
            if not row["seen"]
        ]
        with self.connection:
            self.connection.executemany(
                """
                DELETE FROM model_macros
                WHERE macro_name = ? AND model_id = ? AND query_id = ?
                """,
                rows,
            )

    def get_audits_snapshot(self) -> dict[str, AuditSnapshot]:
        cursor = self.connection.execute("SELECT id, name, snapshot_hash FROM audits")
        return {str(row["name"]): self._audit_snapshot(row) for row in cursor}

    def delete_audits(self, audits: dict[str, AuditSnapshot]) -> None:
        audit_ids = [row["id"] for row in audits.values() if not row["seen"]]
        self.delete_ids("audits", audit_ids)

    def get_model_audits_snapshot(self) -> dict[str, ModelAuditSnapshot]:
        cursor = self.connection.execute("SELECT audit_name, model_id FROM model_audits")
        return {
            f"{row['audit_name']}:{row['model_id']}": self._model_audit_snapshot(row)
            for row in cursor
        }

    def delete_model_audits(self, model_audits: dict[str, ModelAuditSnapshot]) -> None:
        rows = [
            (row["audit_name"], row["model_id"]) for row in model_audits.values() if not row["seen"]
        ]
        with self.connection:
            self.connection.executemany(
                "DELETE FROM model_audits WHERE audit_name = ? AND model_id = ?",
                rows,
            )

    def get_column_lineage_snapshot(self) -> dict[str, ColumnLineageSnapshot]:
        cursor = self.connection.execute(
            "SELECT id, ref_column_model_id, ref_column_qualified_name, "
            "source_column_qualified_name, source_line, ref_line, ref_kind, snapshot_hash "
            "FROM column_lineage"
        )
        return {
            self._column_lineage_key(
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                int(row["ref_line"]),
                str(row["ref_kind"]),
            ): self._column_lineage_snapshot(row)
            for row in cursor
        }

    def delete_column_lineage(self, column_lineage: dict[str, ColumnLineageSnapshot]) -> None:
        reference_ids = [row["id"] for row in column_lineage.values() if not row["seen"]]
        self.delete_ids("column_lineage", reference_ids)

    def get_tests_snapshot(self) -> dict[str, TestSnapshot]:
        cursor = self.connection.execute("SELECT id, file_id, name, snapshot_hash FROM tests")
        return {f"{row['file_id']}:{row['name']}": self._test_snapshot(row) for row in cursor}

    def delete_tests(self, tests: dict[str, TestSnapshot]) -> None:
        test_ids = [row["id"] for row in tests.values() if not row["seen"]]
        self.delete_ids("tests", test_ids)

    def get_test_references_snapshot(self) -> dict[str, TestReferenceSnapshot]:
        cursor = self.connection.execute("SELECT test_id, column_id FROM test_references")
        return {
            f"{row['test_id']}:{row['column_id']}": self._test_reference_snapshot(row)
            for row in cursor
        }

    def delete_test_references(self, test_references: dict[str, TestReferenceSnapshot]) -> None:
        rows = [
            (row["test_id"], row["column_id"])
            for row in test_references.values()
            if not row["seen"]
        ]
        with self.connection:
            self.connection.executemany(
                "DELETE FROM test_references WHERE test_id = ? AND column_id = ?",
                rows,
            )

    def _column_lineage_key(
        self,
        ref_qn: str,
        source_qn: str,
        source_line: int,
        ref_line: int,
        ref_kind: str,
    ) -> str:
        return f"{ref_qn}\0{source_qn}\0{source_line}\0{ref_line}\0{ref_kind}"

    def _file_snapshot(self, row: sqlite3.Row) -> FileSnapshot:
        directory_id = row["directory_id"]
        return {
            "id": int(row["id"]),
            "directory_id": None if directory_id is None else int(directory_id),
            "seen": False,
            "content_hash": str(row["content_hash"]),
            "mtime_ns": int(row["mtime_ns"]),
            "size_bytes": int(row["size_bytes"]),
        }

    def _project_snapshot(self, row: sqlite3.Row) -> ProjectSnapshot:
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "seen": False,
        }

    def _project_gateway_snapshot(self, row: sqlite3.Row) -> ProjectGatewaySnapshot:
        return {
            "id": int(row["id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _model_snapshot(self, row: sqlite3.Row) -> ModelSnapshot:
        return {
            "id": int(row["id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "data_hash": str(row["data_hash"]),
            "metadata_hash": str(row["metadata_hash"]),
            "direct_dependencies_count": int(row["direct_dependencies_count"]),
            "direct_dependents_count": int(row["direct_dependents_count"]),
            "seen": False,
        }

    def _query_snapshot(self, row: sqlite3.Row) -> QuerySnapshot:
        line_start = row["line_start"]
        line_end = row["line_end"]
        return {
            "id": int(row["id"]),
            "model_id": int(row["model_id"]),
            "name": str(row["name"]),
            "qualified_name": str(row["qualified_name"]),
            "line_start": int(line_start) if line_start is not None else None,
            "line_end": int(line_end) if line_end is not None else None,
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _column_snapshot(self, row: sqlite3.Row) -> ColumnSnapshot:
        return {
            "id": int(row["id"]),
            "model_id": int(row["model_id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _macro_snapshot(self, row: sqlite3.Row) -> MacroSnapshot:
        return {
            "id": int(row["id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _model_macro_snapshot(self, row: sqlite3.Row) -> ModelMacroSnapshot:
        return {
            "macro_name": str(row["macro_name"]),
            "model_id": int(row["model_id"]),
            "query_id": int(row["query_id"]),
            "seen": False,
        }

    def _audit_snapshot(self, row: sqlite3.Row) -> AuditSnapshot:
        return {
            "id": int(row["id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _model_audit_snapshot(self, row: sqlite3.Row) -> ModelAuditSnapshot:
        return {
            "audit_name": str(row["audit_name"]),
            "model_id": int(row["model_id"]),
            "seen": False,
        }

    def _column_lineage_snapshot(self, row: sqlite3.Row) -> ColumnLineageSnapshot:
        return {
            "id": int(row["id"]),
            "ref_column_model_id": int(row["ref_column_model_id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _test_snapshot(self, row: sqlite3.Row) -> TestSnapshot:
        return {
            "id": int(row["id"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def _test_reference_snapshot(self, row: sqlite3.Row) -> TestReferenceSnapshot:
        return {
            "test_id": int(row["test_id"]),
            "column_id": int(row["column_id"]),
            "seen": False,
        }

    def _search_doc_snapshot(self, row: sqlite3.Row) -> SearchDocSnapshot:
        return {
            "id": int(row["id"]),
            "model_name": str(row["model_name"]),
            "snapshot_hash": str(row["snapshot_hash"]),
            "seen": False,
        }

    def bulk_insert(self, batches: dict[str, list[dict[str, object]]]) -> None:
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO directories (id, parent_id, name, path, depth)
                VALUES (:id, :parent_id, :name, :path, :depth)
                """,
                batches["directories"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO files (
                    id, directory_id, name, path, normalized_path, language,
                    content_hash, mtime_ns, size_bytes, line_count, is_test, is_config
                ) VALUES (
                    :id, :directory_id, :name, :path, :normalized_path, :language,
                    :content_hash, :mtime_ns, :size_bytes, :line_count, :is_test,
                    :is_config
                )
                """,
                batches["files"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO projects (
                    id, name
                ) VALUES (
                    :id, :name
                )
                """,
                batches["projects"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO project_gateways (
                    id, project_id, name, catalog_name, dialect, is_default, snapshot_hash
                ) VALUES (
                    :id, :project_id, :name, :catalog_name, :dialect, :is_default,
                    :snapshot_hash
                )
                """,
                batches["project_gateways"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO models (
                    id, file_id, gateway_id, dialect, schema_name, qualified_name, kind,
                    is_blueprint, time_column, grain, config_start_line, config_end_line,
                    description, snapshot_hash, data_hash, metadata_hash,
                    direct_dependencies_count, direct_dependents_count
                ) VALUES (
                    :id, :file_id, :gateway_id, :dialect, :schema_name, :qualified_name, :kind,
                    :is_blueprint, :time_column, :grain, :config_start_line, :config_end_line,
                    :description, :snapshot_hash, :data_hash, :metadata_hash,
                    :direct_dependencies_count, :direct_dependents_count
                )
                """,
                batches["models"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO macros (
                    id, file_id, name, kind, line_start, line_end, snapshot_hash
                ) VALUES (
                    :id, :file_id, :name, :kind, :line_start, :line_end, :snapshot_hash
                )
                """,
                batches["macros"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO audits (
                    id, file_id, name, line_start, line_end, snapshot_hash
                ) VALUES (
                    :id, :file_id, :name, :line_start, :line_end, :snapshot_hash
                )
                """,
                batches["audits"],
            )
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO model_audits (
                    audit_name, model_id
                ) VALUES (
                    :audit_name, :model_id
                )
                """,
                batches["model_audits"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO queries (
                    id, model_id, qualified_name, name, line_start, line_end, depth, file_id,
                    snapshot_hash, select_col_count, select_expr_count, select_alias_count,
                    where_condition_count, join_statement_count, group_by_col_count,
                    having_condition_count, qualify_condition_count, order_by_col_count,
                    rendered_sql, models_read_count, line_count
                ) VALUES (
                    :id, :model_id, :qualified_name, :name, :line_start, :line_end, :depth,
                    :file_id, :snapshot_hash, :select_col_count, :select_expr_count,
                    :select_alias_count, :where_condition_count, :join_statement_count,
                    :group_by_col_count, :having_condition_count, :qualify_condition_count,
                    :order_by_col_count, :rendered_sql, :models_read_count, :line_count
                )
                """,
                batches["queries"],
            )
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO model_macros (
                    macro_name, model_id, query_id
                ) VALUES (
                    :macro_name, :model_id, :query_id
                )
                """,
                batches["model_macros"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO columns (
                    id, file_id, query_id, model_id, from_table, name, column_name,
                    qualified_name, data_type, nullable, unique_constraint, line_start,
                    line_end, context, description, is_select, snapshot_hash
                ) VALUES (
                    :id, :file_id, :query_id, :model_id, :from_table, :name, :column_name,
                    :qualified_name, :data_type, :nullable, :unique_constraint, :line_start,
                    :line_end, :context, :description, :is_select, :snapshot_hash
                )
                """,
                batches["columns"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO column_lineage (
                    id, ref_column_id, ref_column_model_id, ref_column_query_name,
                    ref_column_qualified_name, source_column_id, source_models_id,
                    source_query_name, source_column_qualified_name,
                    source_line, ref_line, ref_kind, ref_context, snapshot_hash
                ) VALUES (
                    :id, :ref_column_id, :ref_column_model_id, :ref_column_query_name,
                    :ref_column_qualified_name, :source_column_id, :source_models_id,
                    :source_query_name, :source_column_qualified_name,
                    :source_line, :ref_line, :ref_kind, :ref_context, :snapshot_hash
                )
                """,
                batches["column_lineage"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO tests (
                    id, file_id, model_id, name, line_start, line_end, snapshot_hash
                ) VALUES (
                    :id, :file_id, :model_id, :name, :line_start, :line_end, :snapshot_hash
                )
                """,
                batches["tests"],
            )
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO test_references (
                    test_id, column_id
                ) VALUES (
                    :test_id, :column_id
                )
                """,
                batches["test_references"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO search_docs (
                    id, model_name, model_kind, query_name, column_name, snapshot_hash
                ) VALUES (
                    :id, :model_name, :model_kind, :query_name, :column_name, :snapshot_hash
                )
                """,
                batches["search_docs"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO search_fts (
                    rowid, model_name, model_kind, query_name, column_name
                ) VALUES (
                    :id, :model_name, :model_kind, :query_name, :column_name
                )
                """,
                batches["search_docs"],
            )

    def close(self) -> None:
        self.connection.close()
