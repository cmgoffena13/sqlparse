from pathlib import Path

from sqlmesh.core.context import Context

from src.assigner import GlobalIDAssigner
from src.db import FileSnapshot, ModelSnapshot, ProjectDB


class SQLMeshParser:
    def __init__(self, db: ProjectDB, assigner: GlobalIDAssigner, root: Path) -> None:
        self.db = db
        self.assigner = assigner
        self.root = root
        self.context = Context(paths=self.root, load=False)

    def load(self) -> None:
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

    def _file_id(self, path: Path | None, files_snapshot: dict[str, FileSnapshot]) -> int | None:
        file_id = None
        if path is not None:
            relative = path.resolve().relative_to(self.root).as_posix()
            file_row = files_snapshot.get(relative)
            file_id = None if file_row is None else file_row["id"]
        return file_id
