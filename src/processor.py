import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import xxhash

from src.assigner import GlobalIDAssigner
from src.db import BATCH_TABLES, ProjectDB
from src.git_utils import path_spec_for_indexing, relative_path_is_ignored
from src.parse.sqlmesh_parser import SQLMeshParser

T = TypeVar("T")


def _language(file_extension: str) -> str | None:
    languages = {
        ".py": "python",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".sql": "sql",
    }
    return languages.get(file_extension)


def file_path_is_test(relative_path: str) -> bool:
    parts = relative_path.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or (name.startswith("test_") and name.endswith((".yaml", ".yml")))
        or name.endswith(("_test.yaml", "_test.yml"))
    )


def _join_rel(dir_rel: str, name: str) -> str:
    return name if not dir_rel else f"{dir_rel}/{name}"


class ProjectProcessor:
    def __init__(self, db: ProjectDB, root: Path):
        self.start_time: float | None = time.perf_counter()
        self.db = db
        self.assigner = GlobalIDAssigner(db)
        self.root = root.resolve()
        self._index_ignore_spec = path_spec_for_indexing(self.root)
        self.db_batch_size = 1000
        self.db_batches = self._new_batches()
        self.files_skipped: int = 0
        self.files_indexed: int = 0
        self._lock = threading.RLock()
        self.directories_snapshot = self.db.get_directories_snapshot()
        self.files_snapshot = self.db.get_files_snapshot()
        self.parser = SQLMeshParser(self.db, self.assigner, self.root)

    def _process_directories(self, directory_names: list[str], dir_rel: str) -> None:
        for directory_name in directory_names:
            directory_relative_path = _join_rel(dir_rel, directory_name)
            if directory_relative_path in self.directories_snapshot:
                self.directories_snapshot[directory_relative_path]["seen"] = True
                continue

            directory_id = self.assigner.reserve("directories", 1)[0]
            parent_key = dir_rel if dir_rel else None
            parent_row = None if parent_key is None else self.directories_snapshot.get(parent_key)
            parent_id = None if parent_row is None else parent_row["id"]
            depth = directory_relative_path.count("/")
            self.db_batches["directories"].append(
                {
                    "id": directory_id,
                    "parent_id": parent_id,
                    "name": directory_name,
                    "path": directory_relative_path,
                    "depth": depth,
                }
            )
            self.directories_snapshot[directory_relative_path] = {
                "id": directory_id,
                "seen": True,
            }

    def _python_import_path(self, relative: str) -> str:
        parts = relative.split("/")
        dirs = parts[:-1]
        index = 0
        found = False
        while index < len(dirs) and not found:
            package = self.root.joinpath(*dirs[: index + 1])
            found = (package / "__init__.py").is_file()
            index += 1
        return "/".join(parts[index - 1 :]) if found else relative

    def _normalize_path(self, path: str, language: str | None) -> str:
        module_path = self._python_import_path(path) if language == "python" else path
        dot = module_path.rfind(".")
        slash = module_path.rfind("/")
        stem = module_path[:dot] if dot > slash else module_path
        posix = stem.lower()
        if language == "python":
            posix = posix.replace("/", ".").removesuffix(".__init__")
        return posix

    def _process_file(self, file_name: str, directory_path: str, dir_rel: str, full: bool) -> None:
        file_relative_path = _join_rel(dir_rel, file_name)
        file_abs = f"{directory_path}{os.sep}{file_name}"
        try:
            file_stat = os.lstat(file_abs)
        except OSError:
            self.files_skipped += 1
            return
        mtime_ns = file_stat.st_mtime_ns
        size_bytes = file_stat.st_size
        dot = file_name.rfind(".")
        file_extension = file_name[dot:] if dot != -1 else ""

        if not file_extension and not os.path.isfile(file_abs):  # noqa: PTH113
            return

        directory_id = None if not dir_rel else self.directories_snapshot[dir_rel]["id"]

        existed = file_relative_path in self.files_snapshot
        if existed:
            prior = self.files_snapshot[file_relative_path]
            file_id = prior["id"]
            prior_hash = prior["content_hash"]
            prior_mtime_ns = prior["mtime_ns"]
            prior_size_bytes = prior["size_bytes"]
            if not full and prior_mtime_ns == mtime_ns and prior_size_bytes == size_bytes:
                self.files_snapshot[file_relative_path] = {
                    "id": file_id,
                    "directory_id": directory_id,
                    "seen": True,
                    "content_hash": prior_hash,
                    "mtime_ns": mtime_ns,
                    "size_bytes": size_bytes,
                }
                return
        else:
            file_id = self.assigner.reserve("files", 1)[0]
            prior_hash = None
            prior_mtime_ns = None
            prior_size_bytes = None

        try:
            with open(file_abs, "rb") as handle:  # noqa: PTH123
                file_bytes = handle.read()
            file_hash = xxhash.xxh128(file_bytes).hexdigest()
            line_count = file_bytes.count(b"\n") + 1 if file_bytes else 0
        except OSError:
            self.files_skipped += 1
            return

        language = _language(file_extension)
        file_row: dict[str, object] = {
            "id": file_id,
            "directory_id": directory_id,
            "name": file_name,
            "path": file_relative_path,
            "normalized_path": self._normalize_path(file_relative_path, language),
            "language": language,
            "content_hash": file_hash,
            "mtime_ns": mtime_ns,
            "size_bytes": size_bytes,
            "line_count": line_count,
            "is_test": file_path_is_test(file_relative_path),
        }
        if (
            not existed
            or prior_hash != file_hash
            or prior_mtime_ns != mtime_ns
            or prior_size_bytes != size_bytes
        ):
            self.db_batches["files"].append(file_row)
        self.files_snapshot[file_relative_path] = {
            "id": file_id,
            "directory_id": directory_id,
            "seen": True,
            "content_hash": file_hash,
            "mtime_ns": mtime_ns,
            "size_bytes": size_bytes,
        }

        if full or file_hash != prior_hash:
            self.files_indexed += 1
            self._insert_batch()

    def _new_batches(self) -> dict[str, list[dict[str, object]]]:
        return {table: [] for table in BATCH_TABLES}

    def _process_files(
        self, file_names: list[str], directory_path: str, dir_rel: str, full: bool
    ) -> None:
        for file_name in file_names:
            self._process_file(file_name, directory_path, dir_rel, full)

    def _insert_batch(self, final: bool = False) -> None:
        if not final and not any(
            len(batch) >= self.db_batch_size for batch in self.db_batches.values()
        ):
            return
        self.db.bulk_insert(self.db_batches)
        self.db_batches = self._new_batches()

    def _reset_run_state(self) -> None:
        self.start_time = None
        self.files_skipped = 0
        self.files_indexed = 0
        for entry in self.directories_snapshot.values():
            entry["seen"] = False
        for entry in self.files_snapshot.values():
            entry["seen"] = False

    def process(self, full: bool = False) -> None:
        with self._lock:
            self._process_unlocked(full)

    def run_query(self, fn: Callable[[ProjectDB], T], *, full: bool = False) -> T:
        with self._lock:
            self._process_unlocked(full)
            return fn(self.db)

    def close(self) -> None:
        with self._lock:
            self.parser.context.close()

    def _process_unlocked(self, full: bool = False) -> None:
        start_time = time.perf_counter() if self.start_time is None else self.start_time
        self._reset_run_state()
        reloaded = any(loader.reload_needed() for loader in self.parser.context._loaders)
        if reloaded:
            self.parser.context.load(update_schemas=True)
        root_s = str(self.root)
        for directory_path, directory_names, file_names in os.walk(root_s):
            dir_rel = (
                ""
                if directory_path == root_s
                else os.path.relpath(directory_path, root_s).replace(os.sep, "/")
            )
            directory_names[:] = [
                directory
                for directory in directory_names
                if not relative_path_is_ignored(
                    _join_rel(dir_rel, directory),
                    is_directory=True,
                    spec=self._index_ignore_spec,
                )
            ]
            file_names[:] = [
                file
                for file in file_names
                if not relative_path_is_ignored(
                    _join_rel(dir_rel, file),
                    is_directory=False,
                    spec=self._index_ignore_spec,
                )
            ]
            self._process_directories(directory_names, dir_rel)
            self._process_files(file_names, directory_path, dir_rel, full)

        self._insert_batch(final=True)
        deleted = any(not row["seen"] for row in self.files_snapshot.values()) or any(
            not row["seen"] for row in self.directories_snapshot.values()
        )
        self.db.delete_files(self.files_snapshot)
        self.db.delete_directories(self.directories_snapshot)
        self.files_snapshot = {
            path: meta for path, meta in self.files_snapshot.items() if meta["seen"]
        }
        self.directories_snapshot = {
            path: meta for path, meta in self.directories_snapshot.items() if meta["seen"]
        }
        if reloaded or full or self.files_indexed or deleted:
            self.parser.sync(self.files_snapshot)

        duration_ms = round((time.perf_counter() - start_time) * 1000)
        indexed = (
            f"Indexed {self.files_indexed} files incrementally"
            if not full
            else f"Indexed {self.files_indexed} files"
        )
        print(
            f"{indexed} in {duration_ms}ms (files_skipped: {self.files_skipped})",
            file=sys.stderr,
        )
