from pathlib import Path

from sqlmesh.core.context import Context

from src.assigner import GlobalIDAssigner
from src.db import ColumnSnapshot, FileSnapshot, ModelSnapshot, ProjectDB
from src.parsers.column_lineage import extract_model_columns


class SQLMeshParser:
    def __init__(self, db: ProjectDB, assigner: GlobalIDAssigner, root: Path) -> None:
        self.db = db
        self.assigner = assigner
        self.root = root
        self.context = Context(paths=self.root, load=False)
        self.context.load(update_schemas=False)

    def sync_models(
        self,
        files_snapshot: dict[str, FileSnapshot],
        models_snapshot: dict[str, ModelSnapshot],
        model_batch: list[dict[str, object]],
    ) -> None:
        for model in self.context.models.values():
            qualified_name = model.fqn
            kind = model.kind.name
            file_id = self._file_id(model._path, files_snapshot)
            prior = models_snapshot.get(qualified_name)
            if prior is None:
                model_id = self.assigner.reserve("models", 1)[0]
                model_batch.append(
                    {
                        "id": model_id,
                        "file_id": file_id,
                        "qualified_name": qualified_name,
                        "kind": kind,
                    }
                )
                models_snapshot[qualified_name] = {
                    "id": model_id,
                    "file_id": file_id,
                    "kind": kind,
                    "seen": True,
                }
                continue
            model_id = prior["id"]
            changed = prior["kind"] != kind or prior["file_id"] != file_id
            if changed:
                model_batch.append(
                    {
                        "id": model_id,
                        "file_id": file_id,
                        "qualified_name": qualified_name,
                        "kind": kind,
                    }
                )
            models_snapshot[qualified_name] = {
                "id": model_id,
                "file_id": file_id,
                "kind": kind,
                "seen": True,
            }

    def sync_columns(
        self,
        models_snapshot: dict[str, ModelSnapshot],
        columns_snapshot: dict[str, ColumnSnapshot],
        column_batch: list[dict[str, object]],
    ) -> None:
        for model in self.context.models.values():
            model_id = models_snapshot[model.fqn]["id"]
            for column in extract_model_columns(model):
                query_name = column["query_name"]
                from_table = column["from_table"]
                name = column["name"]
                qualified_name = column["qualified_name"]
                line_start = column["line_start"]
                line_end = column["line_end"]
                context = column["context"]
                prior = columns_snapshot.get(qualified_name)
                if prior is None:
                    column_id = self.assigner.reserve("columns", 1)[0]
                    column_batch.append(
                        {
                            "id": column_id,
                            "model_id": model_id,
                            "query_name": query_name,
                            "from_table": from_table,
                            "name": name,
                            "qualified_name": qualified_name,
                            "line_start": line_start,
                            "line_end": line_end,
                            "context": context,
                        }
                    )
                    columns_snapshot[qualified_name] = {
                        "id": column_id,
                        "qualified_name": qualified_name,
                        "line_start": line_start,
                        "line_end": line_end,
                        "seen": True,
                    }
                    continue
                column_id = prior["id"]
                if prior["line_start"] != line_start or prior["line_end"] != line_end:
                    column_batch.append(
                        {
                            "id": column_id,
                            "model_id": model_id,
                            "query_name": query_name,
                            "from_table": from_table,
                            "name": name,
                            "qualified_name": qualified_name,
                            "line_start": line_start,
                            "line_end": line_end,
                            "context": context,
                        }
                    )
                columns_snapshot[qualified_name] = {
                    "id": column_id,
                    "qualified_name": qualified_name,
                    "line_start": line_start,
                    "line_end": line_end,
                    "seen": True,
                }

    def _file_id(self, path: Path | None, files_snapshot: dict[str, FileSnapshot]) -> int | None:
        file_id = None
        if path is not None:
            relative = path.resolve().relative_to(self.root).as_posix()
            file_row = files_snapshot.get(relative)
            file_id = None if file_row is None else file_row["id"]
        return file_id
