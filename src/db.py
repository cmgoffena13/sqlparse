import sqlite3
from pathlib import Path
from typing import TypedDict

from src.utils import db_path_for_index_root, get_sqlparse_config_dir

BATCH_TABLES = {
    "directories",
    "files",
    "models",
    "macros",
    "model_macros",
    "audits",
    "model_audits",
    "columns",
    "column_lineage",
    "tests",
    "test_references",
}

ASSIGNER_TABLES = {
    "directories",
    "files",
    "models",
    "macros",
    "audits",
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


class ModelSnapshot(TypedDict):
    id: int
    file_id: int | None
    kind: str
    config_start_line: int
    config_end_line: int
    description: str | None
    seen: bool


class ColumnSnapshot(TypedDict):
    id: int
    qualified_name: str
    line_start: int
    line_end: int
    description: str | None
    seen: bool


class MacroSnapshot(TypedDict):
    id: int
    kind: str
    seen: bool


class ModelMacroSnapshot(TypedDict):
    macro_name: str
    model_id: int
    seen: bool


class AuditSnapshot(TypedDict):
    id: int
    seen: bool


class ModelAuditSnapshot(TypedDict):
    audit_name: str
    model_id: int
    seen: bool


class ColumnLineageSnapshot(TypedDict):
    id: int
    ref_column_id: int
    source_column_id: int
    seen: bool


class TestSnapshot(TypedDict):
    id: int
    file_id: int
    name: str
    seen: bool


class TestReferenceSnapshot(TypedDict):
    test_id: int
    column_id: int
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

    def get_models_snapshot(self) -> dict[str, ModelSnapshot]:
        cursor = self.connection.execute(
            "SELECT id, file_id, qualified_name, kind, config_start_line, "
            "config_end_line, description FROM models"
        )
        return {str(row["qualified_name"]): self._model_snapshot(row) for row in cursor}

    def delete_models(self, models: dict[str, ModelSnapshot]) -> None:
        model_ids = [row["id"] for row in models.values() if not row["seen"]]
        self.delete_ids("models", model_ids)

    def get_columns_snapshot(self) -> dict[str, ColumnSnapshot]:
        cursor = self.connection.execute(
            "SELECT id, qualified_name, line_start, line_end, description FROM columns"
        )
        return {str(row["qualified_name"]): self._column_snapshot(row) for row in cursor}

    def delete_columns(self, columns: dict[str, ColumnSnapshot]) -> None:
        column_ids = [row["id"] for row in columns.values() if not row["seen"]]
        self.delete_ids("columns", column_ids)

    def get_macros_snapshot(self) -> dict[str, MacroSnapshot]:
        cursor = self.connection.execute("SELECT id, name, kind FROM macros")
        return {str(row["name"]): self._macro_snapshot(row) for row in cursor}

    def delete_macros(self, macros: dict[str, MacroSnapshot]) -> None:
        macro_ids = [row["id"] for row in macros.values() if not row["seen"]]
        self.delete_ids("macros", macro_ids)

    def get_model_macros_snapshot(self) -> dict[str, ModelMacroSnapshot]:
        cursor = self.connection.execute("SELECT macro_name, model_id FROM model_macros")
        return {
            f"{row['macro_name']}:{row['model_id']}": self._model_macro_snapshot(row)
            for row in cursor
        }

    def delete_model_macros(self, model_macros: dict[str, ModelMacroSnapshot]) -> None:
        rows = [
            (row["macro_name"], row["model_id"]) for row in model_macros.values() if not row["seen"]
        ]
        with self.connection:
            self.connection.executemany(
                "DELETE FROM model_macros WHERE macro_name = ? AND model_id = ?",
                rows,
            )

    def get_audits_snapshot(self) -> dict[str, AuditSnapshot]:
        cursor = self.connection.execute("SELECT id, name FROM audits")
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
            "SELECT id, ref_column_id, ref_column_qualified_name, source_column_id, "
            "source_column_qualified_name, source_line, ref_kind "
            "FROM column_lineage"
        )
        return {
            self._column_lineage_key(
                str(row["ref_column_qualified_name"]),
                str(row["source_column_qualified_name"]),
                int(row["source_line"]),
                str(row["ref_kind"]),
            ): self._column_lineage_snapshot(row)
            for row in cursor
        }

    def delete_column_lineage(self, column_lineage: dict[str, ColumnLineageSnapshot]) -> None:
        reference_ids = [row["id"] for row in column_lineage.values() if not row["seen"]]
        self.delete_ids("column_lineage", reference_ids)

    def get_tests_snapshot(self) -> dict[str, TestSnapshot]:
        cursor = self.connection.execute("SELECT id, file_id, model_id, name FROM tests")
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
        ref_kind: str,
    ) -> str:
        return f"{ref_qn}\0{source_qn}\0{source_line}\0{ref_kind}"

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

    def _model_snapshot(self, row: sqlite3.Row) -> ModelSnapshot:
        file_id = row["file_id"]
        description = row["description"]
        return {
            "id": int(row["id"]),
            "file_id": None if file_id is None else int(file_id),
            "kind": str(row["kind"]),
            "config_start_line": int(row["config_start_line"]),
            "config_end_line": int(row["config_end_line"]),
            "description": None if description is None else str(description),
            "seen": False,
        }

    def _column_snapshot(self, row: sqlite3.Row) -> ColumnSnapshot:
        description = row["description"]
        return {
            "id": int(row["id"]),
            "qualified_name": str(row["qualified_name"]),
            "line_start": int(row["line_start"]),
            "line_end": int(row["line_end"]),
            "description": None if description is None else str(description),
            "seen": False,
        }

    def _macro_snapshot(self, row: sqlite3.Row) -> MacroSnapshot:
        return {
            "id": int(row["id"]),
            "kind": str(row["kind"]),
            "seen": False,
        }

    def _model_macro_snapshot(self, row: sqlite3.Row) -> ModelMacroSnapshot:
        return {
            "macro_name": str(row["macro_name"]),
            "model_id": int(row["model_id"]),
            "seen": False,
        }

    def _audit_snapshot(self, row: sqlite3.Row) -> AuditSnapshot:
        return {
            "id": int(row["id"]),
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
            "ref_column_id": int(row["ref_column_id"]),
            "source_column_id": int(row["source_column_id"]),
            "seen": False,
        }

    def _test_snapshot(self, row: sqlite3.Row) -> TestSnapshot:
        return {
            "id": int(row["id"]),
            "file_id": int(row["file_id"]),
            "name": str(row["name"]),
            "seen": False,
        }

    def _test_reference_snapshot(self, row: sqlite3.Row) -> TestReferenceSnapshot:
        return {
            "test_id": int(row["test_id"]),
            "column_id": int(row["column_id"]),
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
                    content_hash, mtime_ns, size_bytes, line_count, is_test
                ) VALUES (
                    :id, :directory_id, :name, :path, :normalized_path, :language,
                    :content_hash, :mtime_ns, :size_bytes, :line_count, :is_test
                )
                """,
                batches["files"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO models (
                    id, file_id, qualified_name, kind,
                    config_start_line, config_end_line, description
                ) VALUES (
                    :id, :file_id, :qualified_name, :kind,
                    :config_start_line, :config_end_line, :description
                )
                """,
                batches["models"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO macros (
                    id, name, kind
                ) VALUES (
                    :id, :name, :kind
                )
                """,
                batches["macros"],
            )
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO model_macros (
                    macro_name, model_id
                ) VALUES (
                    :macro_name, :model_id
                )
                """,
                batches["model_macros"],
            )
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO audits (
                    id, name
                ) VALUES (
                    :id, :name
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
                INSERT OR REPLACE INTO columns (
                    id, model_id, query_name, from_table, name,
                    qualified_name, line_start, line_end, context, description
                ) VALUES (
                    :id, :model_id, :query_name, :from_table, :name,
                    :qualified_name, :line_start, :line_end, :context, :description
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
                    source_line, ref_kind, context
                ) VALUES (
                    :id, :ref_column_id, :ref_column_model_id, :ref_column_query_name,
                    :ref_column_qualified_name, :source_column_id, :source_models_id,
                    :source_query_name, :source_column_qualified_name,
                    :source_line, :ref_kind, :context
                )
                """,
                batches["column_lineage"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO tests (
                    id, file_id, model_id, name
                ) VALUES (
                    :id, :file_id, :model_id, :name
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

    def close(self) -> None:
        self.connection.close()
