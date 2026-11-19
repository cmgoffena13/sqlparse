from pathlib import Path

from sqlmesh.core.context import Context
from sqlmesh.core.model import Model

from src.assigner import GlobalIDAssigner
from src.db import (
    BATCH_TABLES,
    AuditSnapshot,
    ColumnLineageSnapshot,
    ColumnSnapshot,
    FileSnapshot,
    MacroSnapshot,
    ModelAuditSnapshot,
    ModelMacroSnapshot,
    ModelSnapshot,
    ProjectDB,
    TestReferenceSnapshot,
    TestSnapshot,
)
from src.parse.column_lineage import extract_model_column_references, extract_model_columns
from src.parse.macro_utils import macro_paths
from src.parse.model_utils import model_config_lines
from src.parse.test_utils import fixture_column_names
from src.utils import snapshot_hash


class SQLMeshParser:
    def __init__(self, db: ProjectDB, assigner: GlobalIDAssigner, root: Path) -> None:
        self.db = db
        self.assigner = assigner
        self.root = root
        self.context = Context(paths=self.root, load=False)
        self.context.load(update_schemas=True)
        self.batches = self._new_batches()

    def _new_batches(self) -> dict[str, list[dict[str, object]]]:
        return {table: [] for table in BATCH_TABLES}

    def _flush(self) -> None:
        self.db.bulk_insert(self.batches)
        self.batches = self._new_batches()

    def sync(self, files_snapshot: dict[str, FileSnapshot]) -> None:
        macros_snapshot = self.db.get_macros_snapshot()
        self._sync_macros(files_snapshot, macros_snapshot)
        audits_snapshot = self.db.get_audits_snapshot()
        self._sync_audits(files_snapshot, audits_snapshot)
        self._flush()

        models_snapshot = self.db.get_models_snapshot()
        model_macros_snapshot = self.db.get_model_macros_snapshot()
        model_audits_snapshot = self.db.get_model_audits_snapshot()
        columns_snapshot = self.db.get_columns_snapshot()
        for model in self.context.models.values():
            self._sync_model(model, files_snapshot, models_snapshot)
            self._sync_model_macros(model, models_snapshot, macros_snapshot, model_macros_snapshot)
            self._sync_model_audits(model, models_snapshot, audits_snapshot, model_audits_snapshot)
            self._sync_columns(model, models_snapshot, columns_snapshot)
            self._flush()

        self.db.delete_model_macros(model_macros_snapshot)
        self.db.delete_macros(macros_snapshot)
        self.db.delete_model_audits(model_audits_snapshot)
        self.db.delete_audits(audits_snapshot)

        tests_snapshot = self.db.get_tests_snapshot()
        test_references_snapshot = self.db.get_test_references_snapshot()
        self._sync_tests(
            files_snapshot,
            models_snapshot,
            columns_snapshot,
            tests_snapshot,
            test_references_snapshot,
        )
        self._flush()

        self.db.delete_test_references(test_references_snapshot)
        self.db.delete_tests(tests_snapshot)

        column_lineage_snapshot = self.db.get_column_lineage_snapshot()
        for model in self.context.models.values():
            self._sync_column_lineage(
                model, models_snapshot, columns_snapshot, column_lineage_snapshot
            )
            self._flush()

        self.db.delete_column_lineage(column_lineage_snapshot)
        self.db.delete_columns(columns_snapshot)
        self.db.delete_models(models_snapshot)

    def _sync_macros(
        self,
        files_snapshot: dict[str, FileSnapshot],
        macros_snapshot: dict[str, MacroSnapshot],
    ) -> None:
        paths = macro_paths(self.context)
        macros: list[tuple[str, str]] = [
            (name, "jinja") for name in self.context._jinja_macros.root_macros
        ]
        for name, macro in self.context._macros.items():
            if not getattr(macro, "__sqlmesh__builtin__", False):
                macros.append((name, "python"))
        for name, kind in macros:
            file_id = self._file_id(paths[name], files_snapshot)
            prior = macros_snapshot.get(name)
            if prior is None:
                macro_id = self.assigner.reserve("macros", 1)[0]
                self.batches["macros"].append(
                    {"id": macro_id, "file_id": file_id, "name": name, "kind": kind}
                )
                macros_snapshot[name] = {
                    "id": macro_id,
                    "file_id": file_id,
                    "kind": kind,
                    "seen": True,
                }
                continue
            macro_id = prior["id"]
            if prior["kind"] != kind or prior["file_id"] != file_id:
                self.batches["macros"].append(
                    {"id": macro_id, "file_id": file_id, "name": name, "kind": kind}
                )
            macros_snapshot[name] = {
                "id": macro_id,
                "file_id": file_id,
                "kind": kind,
                "seen": True,
            }

    def _sync_audits(
        self,
        files_snapshot: dict[str, FileSnapshot],
        audits_snapshot: dict[str, AuditSnapshot],
    ) -> None:
        audits = {
            **dict(self.context._audits.items()),
            **dict(self.context.standalone_audits.items()),
        }
        for name, audit in audits.items():
            file_id = self._file_id(Path(str(audit._path)), files_snapshot)
            prior = audits_snapshot.get(name)
            if prior is None:
                audit_id = self.assigner.reserve("audits", 1)[0]
                self.batches["audits"].append({"id": audit_id, "file_id": file_id, "name": name})
                audits_snapshot[name] = {"id": audit_id, "file_id": file_id, "seen": True}
                continue
            audit_id = prior["id"]
            if prior["file_id"] != file_id:
                self.batches["audits"].append({"id": audit_id, "file_id": file_id, "name": name})
            audits_snapshot[name] = {"id": audit_id, "file_id": file_id, "seen": True}

    def _sync_model(
        self,
        model: Model,
        files_snapshot: dict[str, FileSnapshot],
        models_snapshot: dict[str, ModelSnapshot],
    ) -> None:
        qualified_name = model.fqn
        kind = model.kind.name
        file_id = self._file_id(Path(str(model._path)), files_snapshot)
        config_start_line, config_end_line = model_config_lines(model)
        description = model.description
        digest = snapshot_hash(
            [
                file_id,
                qualified_name,
                kind,
                config_start_line,
                config_end_line,
                description,
            ]
        )
        prior = models_snapshot.get(qualified_name)
        if prior is None:
            model_id = self.assigner.reserve("models", 1)[0]
            self.batches["models"].append(
                {
                    "id": model_id,
                    "file_id": file_id,
                    "qualified_name": qualified_name,
                    "kind": kind,
                    "config_start_line": config_start_line,
                    "config_end_line": config_end_line,
                    "description": description,
                    "snapshot_hash": digest,
                }
            )
        else:
            model_id = prior["id"]
            if prior["snapshot_hash"] != digest:
                self.batches["models"].append(
                    {
                        "id": model_id,
                        "file_id": file_id,
                        "qualified_name": qualified_name,
                        "kind": kind,
                        "config_start_line": config_start_line,
                        "config_end_line": config_end_line,
                        "description": description,
                        "snapshot_hash": digest,
                    }
                )
        models_snapshot[qualified_name] = {
            "id": model_id,
            "snapshot_hash": digest,
            "seen": True,
        }

    def _sync_model_macros(
        self,
        model: Model,
        models_snapshot: dict[str, ModelSnapshot],
        macros_snapshot: dict[str, MacroSnapshot],
        model_macros_snapshot: dict[str, ModelMacroSnapshot],
    ) -> None:
        model_id = models_snapshot[model.fqn]["id"]
        macro_names = set(model.jinja_macros.root_macros)
        for name in model.python_env or {}:
            if name in macros_snapshot:
                macro_names.add(name)
        for macro_name in macro_names:
            key = f"{macro_name}:{model_id}"
            prior = model_macros_snapshot.get(key)
            if prior is None:
                self.batches["model_macros"].append(
                    {"macro_name": macro_name, "model_id": model_id}
                )
                model_macros_snapshot[key] = {
                    "macro_name": macro_name,
                    "model_id": model_id,
                    "seen": True,
                }
                continue
            model_macros_snapshot[key] = {
                "macro_name": macro_name,
                "model_id": model_id,
                "seen": True,
            }

    def _sync_model_audits(
        self,
        model: Model,
        models_snapshot: dict[str, ModelSnapshot],
        audits_snapshot: dict[str, AuditSnapshot],
        model_audits_snapshot: dict[str, ModelAuditSnapshot],
    ) -> None:
        model_id = models_snapshot[model.fqn]["id"]
        audit_names = {audit_name for audit_name, _ in model.audits}
        audit_names |= set(model.audit_definitions)
        for audit_name in audit_names:
            if audit_name not in audits_snapshot:
                continue
            key = f"{audit_name}:{model_id}"
            prior = model_audits_snapshot.get(key)
            if prior is None:
                self.batches["model_audits"].append(
                    {"audit_name": audit_name, "model_id": model_id}
                )
                model_audits_snapshot[key] = {
                    "audit_name": audit_name,
                    "model_id": model_id,
                    "seen": True,
                }
                continue
            model_audits_snapshot[key] = {
                "audit_name": audit_name,
                "model_id": model_id,
                "seen": True,
            }

    def _sync_columns(
        self,
        model: Model,
        models_snapshot: dict[str, ModelSnapshot],
        columns_snapshot: dict[str, ColumnSnapshot],
    ) -> None:
        model_id = models_snapshot[model.fqn]["id"]
        column_descriptions = model.column_descriptions
        for column in extract_model_columns(model):
            query_name = column["query_name"]
            from_table = column["from_table"]
            name = column["name"]
            qualified_name = column["qualified_name"]
            line_start = column["line_start"]
            line_end = column["line_end"]
            context = column["context"]
            description = column_descriptions.get(name) if query_name == model.name else None
            data_type = column["data_type"]
            digest = snapshot_hash(
                [
                    model_id,
                    query_name,
                    from_table,
                    name,
                    qualified_name,
                    data_type,
                    line_start,
                    line_end,
                    context,
                    description,
                ]
            )
            prior = columns_snapshot.get(qualified_name)
            if prior is None:
                column_id = self.assigner.reserve("columns", 1)[0]
                self.batches["columns"].append(
                    {
                        "id": column_id,
                        "model_id": model_id,
                        "query_name": query_name,
                        "from_table": from_table,
                        "name": name,
                        "qualified_name": qualified_name,
                        "data_type": data_type,
                        "line_start": line_start,
                        "line_end": line_end,
                        "context": context,
                        "description": description,
                        "snapshot_hash": digest,
                    }
                )
                columns_snapshot[qualified_name] = {
                    "id": column_id,
                    "snapshot_hash": digest,
                    "seen": True,
                }
                continue
            column_id = prior["id"]
            if prior["snapshot_hash"] != digest:
                self.batches["columns"].append(
                    {
                        "id": column_id,
                        "model_id": model_id,
                        "query_name": query_name,
                        "from_table": from_table,
                        "name": name,
                        "qualified_name": qualified_name,
                        "data_type": data_type,
                        "line_start": line_start,
                        "line_end": line_end,
                        "context": context,
                        "description": description,
                        "snapshot_hash": digest,
                    }
                )
            columns_snapshot[qualified_name] = {
                "id": column_id,
                "snapshot_hash": digest,
                "seen": True,
            }

    def _sync_column_lineage(
        self,
        model: Model,
        models_snapshot: dict[str, ModelSnapshot],
        columns_snapshot: dict[str, ColumnSnapshot],
        column_lineage_snapshot: dict[str, ColumnLineageSnapshot],
    ) -> None:
        model_id = models_snapshot[model.fqn]["id"]
        model_name_to_id = {
            synced.name: models_snapshot[synced.fqn]["id"]
            for synced in self.context.models.values()
            if synced.fqn in models_snapshot
        }
        for reference in extract_model_column_references(model):
            ref_query_name = reference["ref_column_query_name"]
            ref_qn = reference["ref_column_qualified_name"]
            source_query_name = reference["source_query_name"]
            source_qn = reference["source_column_qualified_name"]
            source_line = reference["source_line"]
            ref_kind = reference["ref_kind"]
            context = reference["context"]
            if source_qn not in columns_snapshot:
                continue
            ref_column_id = columns_snapshot[ref_qn]["id"]
            source_column_id = columns_snapshot[source_qn]["id"]
            source_models_id = model_id
            matched_name = ""
            for name, mid in model_name_to_id.items():
                if (source_qn == name or source_qn.startswith(f"{name}.")) and len(name) > len(
                    matched_name
                ):
                    matched_name = name
                    source_models_id = mid
            digest = snapshot_hash(
                [
                    ref_column_id,
                    model_id,
                    ref_query_name,
                    ref_qn,
                    source_column_id,
                    source_models_id,
                    source_query_name,
                    source_qn,
                    source_line,
                    ref_kind,
                    context,
                ]
            )
            key = self.db._column_lineage_key(ref_qn, source_qn, source_line, ref_kind)
            prior = column_lineage_snapshot.get(key)
            if prior is None:
                lineage_id = self.assigner.reserve("column_lineage", 1)[0]
                self.batches["column_lineage"].append(
                    {
                        "id": lineage_id,
                        "ref_column_id": ref_column_id,
                        "ref_column_model_id": model_id,
                        "ref_column_query_name": ref_query_name,
                        "ref_column_qualified_name": ref_qn,
                        "source_column_id": source_column_id,
                        "source_models_id": source_models_id,
                        "source_query_name": source_query_name,
                        "source_column_qualified_name": source_qn,
                        "source_line": source_line,
                        "ref_kind": ref_kind,
                        "context": context,
                        "snapshot_hash": digest,
                    }
                )
                column_lineage_snapshot[key] = {
                    "id": lineage_id,
                    "snapshot_hash": digest,
                    "seen": True,
                }
                continue
            lineage_id = prior["id"]
            if prior["snapshot_hash"] != digest:
                self.batches["column_lineage"].append(
                    {
                        "id": lineage_id,
                        "ref_column_id": ref_column_id,
                        "ref_column_model_id": model_id,
                        "ref_column_query_name": ref_query_name,
                        "ref_column_qualified_name": ref_qn,
                        "source_column_id": source_column_id,
                        "source_models_id": source_models_id,
                        "source_query_name": source_query_name,
                        "source_column_qualified_name": source_qn,
                        "source_line": source_line,
                        "ref_kind": ref_kind,
                        "context": context,
                        "snapshot_hash": digest,
                    }
                )
            column_lineage_snapshot[key] = {
                "id": lineage_id,
                "snapshot_hash": digest,
                "seen": True,
            }

    def _sync_tests(
        self,
        files_snapshot: dict[str, FileSnapshot],
        models_snapshot: dict[str, ModelSnapshot],
        columns_snapshot: dict[str, ColumnSnapshot],
        tests_snapshot: dict[str, TestSnapshot],
        test_references_snapshot: dict[str, TestReferenceSnapshot],
    ) -> None:
        for metadata in self.context._model_test_metadata:
            file_id = self._file_id(Path(str(metadata.path)), files_snapshot)
            model = self.context.get_model(metadata.model_name)
            if model is None or model.fqn not in models_snapshot:
                continue
            model_id = models_snapshot[model.fqn]["id"]
            name = metadata.test_name
            key = f"{file_id}:{name}"
            prior = tests_snapshot.get(key)
            test_id = self.assigner.reserve("tests", 1)[0] if prior is None else prior["id"]
            self.batches["tests"].append(
                {
                    "id": test_id,
                    "file_id": file_id,
                    "model_id": model_id,
                    "name": name,
                }
            )
            tests_snapshot[key] = {
                "id": test_id,
                "file_id": file_id,
                "name": name,
                "seen": True,
            }
            body = metadata.body if isinstance(metadata.body, dict) else {}
            column_qns: list[str] = []
            for input_name, values in (body.get("inputs") or {}).items():
                input_model = self.context.get_model(input_name)
                if input_model is None:
                    continue
                for column_name in fixture_column_names(values):
                    column_qns.append(f"{input_model.name}.{column_name}")
            outputs = body.get("outputs") or {}
            for column_name in fixture_column_names(outputs.get("query")):
                column_qns.append(f"{model.name}.{column_name}")
            for cte_name, values in (outputs.get("ctes") or {}).items():
                for column_name in fixture_column_names(values):
                    column_qns.append(f"{model.name}.{cte_name}.{column_name}")
            for column_qn in column_qns:
                if column_qn not in columns_snapshot:
                    continue
                column_id = columns_snapshot[column_qn]["id"]
                ref_key = f"{test_id}:{column_id}"
                prior_ref = test_references_snapshot.get(ref_key)
                if prior_ref is None:
                    self.batches["test_references"].append(
                        {"test_id": test_id, "column_id": column_id}
                    )
                    test_references_snapshot[ref_key] = {
                        "test_id": test_id,
                        "column_id": column_id,
                        "seen": True,
                    }
                    continue
                test_references_snapshot[ref_key] = {
                    "test_id": test_id,
                    "column_id": column_id,
                    "seen": True,
                }

    def _file_id(self, path: Path, files_snapshot: dict[str, FileSnapshot]) -> int:
        relative = path.resolve().relative_to(self.root).as_posix()
        return files_snapshot[relative]["id"]
