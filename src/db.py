import sqlite3
from pathlib import Path
from typing import TypedDict

from src.utils import db_path_for_index_root, get_sqlparse_config_dir

TABLE_BATCH_MAP = {
    "directories",
    "files",
    "models",
    "columns",
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
    line_count: int


class ModelSnapshot(TypedDict):
    id: int
    file_id: int | None
    kind: str
    seen: bool


class ColumnSnapshot(TypedDict):
    id: int
    qualified_name: str
    line_start: int
    line_end: int
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
        if table not in TABLE_BATCH_MAP:
            raise ValueError(f"unsupported table: {table}")
        query = f"SELECT COALESCE(MAX(id), 0) AS max_id FROM {table}"  # noqa: S608
        row = self.connection.execute(query).fetchone()
        return 0 if row is None else int(row["max_id"])

    def get_watermark(self) -> tuple[int, int]:
        row = self.connection.execute(
            "SELECT last_full_parse, last_incremental FROM watermarks WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("watermarks row is missing")
        last_incremental = 0 if row["last_incremental"] is None else int(row["last_incremental"])
        return int(row["last_full_parse"]), last_incremental

    def set_watermark(self, last_full_parse: int | None, last_incremental: int) -> None:
        if last_full_parse is not None:
            query = "UPDATE watermarks SET last_full_parse = ?, last_incremental = ? WHERE id = 1"
            params = (last_full_parse, last_incremental)
        else:
            query = "UPDATE watermarks SET last_incremental = ? WHERE id = 1"
            params = (last_incremental,)
        self.exec_tran(query, params)

    def delete_ids(self, table: str, ids: list[int]) -> None:
        if not ids:
            return
        if table not in TABLE_BATCH_MAP:
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
            "SELECT id, directory_id, path, content_hash, mtime_ns, size_bytes, "
            "line_count FROM files"
        )
        return {str(row["path"]): self._file_snapshot(row) for row in cursor}

    def delete_files(self, files: dict[str, FileSnapshot]) -> None:
        file_ids = [row["id"] for row in files.values() if not row["seen"]]
        self.delete_ids("files", file_ids)

    def get_models_snapshot(self) -> dict[str, ModelSnapshot]:
        cursor = self.connection.execute("SELECT id, file_id, qualified_name, kind FROM models")
        return {str(row["qualified_name"]): self._model_snapshot(row) for row in cursor}

    def delete_models(self, models: dict[str, ModelSnapshot]) -> None:
        model_ids = [row["id"] for row in models.values() if not row["seen"]]
        self.delete_ids("models", model_ids)

    def get_columns_snapshot(self) -> dict[str, ColumnSnapshot]:
        cursor = self.connection.execute(
            "SELECT id, qualified_name, line_start, line_end FROM columns"
        )
        return {str(row["qualified_name"]): self._column_snapshot(row) for row in cursor}

    def delete_columns(self, columns: dict[str, ColumnSnapshot]) -> None:
        column_ids = [row["id"] for row in columns.values() if not row["seen"]]
        self.delete_ids("columns", column_ids)

    def _file_snapshot(self, row: sqlite3.Row) -> FileSnapshot:
        directory_id = row["directory_id"]
        return {
            "id": int(row["id"]),
            "directory_id": None if directory_id is None else int(directory_id),
            "seen": False,
            "content_hash": str(row["content_hash"]),
            "mtime_ns": int(row["mtime_ns"]),
            "size_bytes": int(row["size_bytes"]),
            "line_count": int(row["line_count"]),
        }

    def _model_snapshot(self, row: sqlite3.Row) -> ModelSnapshot:
        file_id = row["file_id"]
        return {
            "id": int(row["id"]),
            "file_id": None if file_id is None else int(file_id),
            "kind": str(row["kind"]),
            "seen": False,
        }

    def _column_snapshot(self, row: sqlite3.Row) -> ColumnSnapshot:
        return {
            "id": int(row["id"]),
            "qualified_name": str(row["qualified_name"]),
            "line_start": int(row["line_start"]),
            "line_end": int(row["line_end"]),
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
                    content_hash, mtime_ns, size_bytes, line_count
                ) VALUES (
                    :id, :directory_id, :name, :path, :normalized_path, :language,
                    :content_hash, :mtime_ns, :size_bytes, :line_count
                )
                """,
                batches["files"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO models (
                    id, file_id, qualified_name, kind
                ) VALUES (
                    :id, :file_id, :qualified_name, :kind
                )
                """,
                batches["models"],
            )
            self.connection.executemany(
                """
                INSERT OR REPLACE INTO columns (
                    id, model_id, query_name, from_table, name,
                    qualified_name, line_start, line_end, context
                ) VALUES (
                    :id, :model_id, :query_name, :from_table, :name,
                    :qualified_name, :line_start, :line_end, :context
                )
                """,
                batches["columns"],
            )

    def close(self) -> None:
        self.connection.close()
