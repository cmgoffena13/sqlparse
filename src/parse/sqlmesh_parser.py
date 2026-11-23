import os
import site
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlmesh.core.config import Config
from sqlmesh.core.config.loader import load_configs
from sqlmesh.core.context import Context
from sqlmesh.core.model import Model
from sqlmesh.utils.errors import ConfigError

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
    ProjectGatewaySnapshot,
    ProjectSnapshot,
    QuerySnapshot,
    SearchDocSnapshot,
    TestReferenceSnapshot,
    TestSnapshot,
)
from src.parse.audit_utils import audit_line_span, not_null_column_names
from src.parse.column_lineage import (
    _columns_named,
    _stored_qualified_name,
    extract_model_column_references,
    extract_model_columns,
    extract_model_queries,
    final_query_name,
    model_query_name,
)
from src.parse.macro_utils import macro_locations
from src.parse.model_utils import model_config_lines, model_grain, model_time_column
from src.parse.parse_only import install_parse_only_engine_support
from src.parse.test_utils import fixture_column_names, test_line_span
from src.utils import snapshot_hash


def project_site_packages(root: Path) -> list[Path]:
    candidates = [
        root / name for name in (".venv", "venv") if (root / name / "pyvenv.cfg").is_file()
    ]
    venv_root = candidates[0] if candidates else None
    tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    direct = (
        []
        if venv_root is None
        else [venv_root / "lib" / tag / "site-packages", venv_root / "Lib" / "site-packages"]
    )
    packages = [path for path in direct if path.is_dir()]
    if venv_root is not None and not packages:
        packages = sorted(
            path for path in (venv_root / "lib").glob("python*/site-packages") if path.is_dir()
        )
    return packages


def use_project_venv(root: Path) -> None:
    for package in project_site_packages(root):
        site.addsitedir(str(package.absolute()))


@contextmanager
def project_cwd(root: Path) -> Generator[None]:
    previous = Path.cwd()
    os.chdir(root.resolve())
    try:
        yield
    finally:
        os.chdir(previous)


def is_sqlmesh_project(root: Path) -> bool:
    use_project_venv(root)
    with project_cwd(root):
        try:
            load_configs("config", Config, root)
        except ConfigError:
            project = False
        else:
            project = True
    return project


class SQLMeshParser:
    def __init__(self, db: ProjectDB, assigner: GlobalIDAssigner, root: Path) -> None:
        self.db = db
        self.assigner = assigner
        self.root = root
        use_project_venv(self.root)
        install_parse_only_engine_support()
        with project_cwd(self.root):
            self.context = Context(paths=self.root, load=False)
            self.context.load(update_schemas=True)
        self.batches = self._new_batches()
        self._gateway_ids: dict[tuple[str, str], int] = {}
        self._project_defaults: dict[str, str] = {}
        self._query_ids: dict[str, int] = {}

    def _new_batches(self) -> dict[str, list[dict[str, object]]]:
        return {table: [] for table in BATCH_TABLES}

    def _flush(self) -> None:
        self.db.bulk_insert(self.batches)
        self.batches = self._new_batches()

    def sync(self, files_snapshot: dict[str, FileSnapshot]) -> None:
        projects_snapshot = self.db.get_projects_snapshot()
        gateways_snapshot = self.db.get_project_gateways_snapshot()
        self._sync_projects(projects_snapshot, gateways_snapshot)
        self._flush()

        macros_snapshot = self.db.get_macros_snapshot()
        self._sync_macros(files_snapshot, macros_snapshot)
        audits_snapshot = self.db.get_audits_snapshot()
        self._sync_audits(files_snapshot, audits_snapshot)
        self._flush()

        models_snapshot = self.db.get_models_snapshot()
        model_macros_snapshot = self.db.get_model_macros_snapshot()
        model_audits_snapshot = self.db.get_model_audits_snapshot()
        columns_snapshot = self.db.get_columns_snapshot()
        search_docs_snapshot = self.db.get_search_docs_snapshot()
        queries_snapshot = self.db.get_queries_snapshot()
        for prior_query in queries_snapshot.values():
            self._query_ids[prior_query["query_name"]] = prior_query["id"]
        for model in self.context.models.values():
            self._sync_model(model, files_snapshot, models_snapshot)
            self._sync_model_macros(model, models_snapshot, macros_snapshot, model_macros_snapshot)
            self._sync_model_audits(model, models_snapshot, audits_snapshot, model_audits_snapshot)
            self._sync_queries(model, files_snapshot, models_snapshot, queries_snapshot)
            self._sync_columns(
                model, files_snapshot, models_snapshot, columns_snapshot, search_docs_snapshot
            )
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
        self.db.delete_search_docs(search_docs_snapshot)
        self.db.delete_columns(columns_snapshot)
        self.db.delete_queries(queries_snapshot)
        self.db.delete_models(models_snapshot)
        self.db.delete_project_gateways(gateways_snapshot)
        self.db.delete_projects(projects_snapshot)

    def _sync_macros(
        self,
        files_snapshot: dict[str, FileSnapshot],
        macros_snapshot: dict[str, MacroSnapshot],
    ) -> None:
        for name, location in macro_locations(self.context).items():
            file_id = self._file_id(location["path"], files_snapshot)
            kind = location["kind"]
            line_start = location["line_start"]
            line_end = location["line_end"]
            digest = snapshot_hash([file_id, name, kind, line_start, line_end])
            prior = macros_snapshot.get(name)
            if prior is None:
                macro_id = self.assigner.reserve("macros", 1)[0]
                self.batches["macros"].append(
                    {
                        "id": macro_id,
                        "file_id": file_id,
                        "name": name,
                        "kind": kind,
                        "line_start": line_start,
                        "line_end": line_end,
                        "snapshot_hash": digest,
                    }
                )
                macros_snapshot[name] = {"id": macro_id, "snapshot_hash": digest, "seen": True}
                continue
            macro_id = prior["id"]
            if prior["snapshot_hash"] != digest:
                self.batches["macros"].append(
                    {
                        "id": macro_id,
                        "file_id": file_id,
                        "name": name,
                        "kind": kind,
                        "line_start": line_start,
                        "line_end": line_end,
                        "snapshot_hash": digest,
                    }
                )
            macros_snapshot[name] = {"id": macro_id, "snapshot_hash": digest, "seen": True}

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
            path = Path(str(audit._path))
            file_id = self._file_id(path, files_snapshot)
            line_start, line_end = audit_line_span(path, audit.dialect, name)
            digest = snapshot_hash([file_id, name, line_start, line_end])
            prior = audits_snapshot.get(name)
            if prior is None:
                audit_id = self.assigner.reserve("audits", 1)[0]
                self.batches["audits"].append(
                    {
                        "id": audit_id,
                        "file_id": file_id,
                        "name": name,
                        "line_start": line_start,
                        "line_end": line_end,
                        "snapshot_hash": digest,
                    }
                )
                audits_snapshot[name] = {"id": audit_id, "snapshot_hash": digest, "seen": True}
                continue
            audit_id = prior["id"]
            if prior["snapshot_hash"] != digest:
                self.batches["audits"].append(
                    {
                        "id": audit_id,
                        "file_id": file_id,
                        "name": name,
                        "line_start": line_start,
                        "line_end": line_end,
                        "snapshot_hash": digest,
                    }
                )
            audits_snapshot[name] = {"id": audit_id, "snapshot_hash": digest, "seen": True}

    def _sync_projects(
        self,
        projects_snapshot: dict[str, ProjectSnapshot],
        gateways_snapshot: dict[str, ProjectGatewaySnapshot],
    ) -> None:
        self._gateway_ids = {}
        self._project_defaults = {}
        for config_path, config in self.context.configs.items():
            project_name = config.project or Path(config_path).name
            self._project_defaults[project_name] = config.default_gateway
            prior_project = projects_snapshot.get(project_name)
            if prior_project is None:
                project_id = self.assigner.reserve("projects", 1)[0]
                self.batches["projects"].append({"id": project_id, "name": project_name})
            else:
                project_id = prior_project["id"]
                if prior_project["name"] != project_name:
                    self.batches["projects"].append({"id": project_id, "name": project_name})
            projects_snapshot[project_name] = {
                "id": project_id,
                "name": project_name,
                "seen": True,
            }
            for gateway_name, gateway in config.gateways.items():
                gateway_dialect = None
                if gateway.model_defaults is not None and gateway.model_defaults.dialect:
                    gateway_dialect = gateway.model_defaults.dialect
                catalog_name = None
                if gateway.connection is not None:
                    catalog_name = gateway.connection.get_catalog()
                key = f"{project_id}:{gateway_name}"
                prior_gateway = gateways_snapshot.get(key)
                if prior_gateway is None:
                    gateway_id = self.assigner.reserve("project_gateways", 1)[0]
                    self.batches["project_gateways"].append(
                        {
                            "id": gateway_id,
                            "project_id": project_id,
                            "name": gateway_name,
                            "catalog_name": catalog_name,
                            "dialect": gateway_dialect,
                        }
                    )
                else:
                    gateway_id = prior_gateway["id"]
                    if (
                        prior_gateway["project_id"] != project_id
                        or prior_gateway["name"] != gateway_name
                        or prior_gateway["catalog_name"] != catalog_name
                        or prior_gateway["dialect"] != gateway_dialect
                    ):
                        self.batches["project_gateways"].append(
                            {
                                "id": gateway_id,
                                "project_id": project_id,
                                "name": gateway_name,
                                "catalog_name": catalog_name,
                                "dialect": gateway_dialect,
                            }
                        )
                gateways_snapshot[key] = {
                    "id": gateway_id,
                    "project_id": project_id,
                    "name": gateway_name,
                    "catalog_name": catalog_name,
                    "dialect": gateway_dialect,
                    "seen": True,
                }
                self._gateway_ids[(project_name, gateway_name)] = gateway_id

    def _project_name_for_model(self, model: Model) -> str:
        project_name = model.project
        if not project_name:
            model_path = Path(str(model._path)).resolve()
            project_name = next(
                config.project or Path(config_path).name
                for config_path, config in self.context.configs.items()
                if model_path.is_relative_to(Path(config_path).resolve())
            )
        return project_name

    def _sync_model(
        self,
        model: Model,
        files_snapshot: dict[str, FileSnapshot],
        models_snapshot: dict[str, ModelSnapshot],
    ) -> None:
        qualified_name = model.name
        schema_name = model.schema_name
        kind = model.kind.name
        time_column = model_time_column(model)
        grain = model_grain(model)
        file_id = self._file_id(Path(str(model._path)), files_snapshot)
        project_name = self._project_name_for_model(model)
        gateway_name = model.gateway or self._project_defaults[project_name]
        gateway_id = self._gateway_ids[(project_name, gateway_name)]
        dialect = model.dialect
        config_start_line, config_end_line = model_config_lines(model)
        description = model.description
        digest = snapshot_hash(
            [
                file_id,
                gateway_id,
                dialect,
                schema_name,
                qualified_name,
                kind,
                time_column,
                grain,
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
                    "gateway_id": gateway_id,
                    "dialect": dialect,
                    "schema_name": schema_name,
                    "qualified_name": qualified_name,
                    "kind": kind,
                    "time_column": time_column,
                    "grain": grain,
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
                        "gateway_id": gateway_id,
                        "dialect": dialect,
                        "schema_name": schema_name,
                        "qualified_name": qualified_name,
                        "kind": kind,
                        "time_column": time_column,
                        "grain": grain,
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
        model_id = models_snapshot[model.name]["id"]
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
        model_id = models_snapshot[model.name]["id"]
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

    def _sync_queries(
        self,
        model: Model,
        files_snapshot: dict[str, FileSnapshot],
        models_snapshot: dict[str, ModelSnapshot],
        queries_snapshot: dict[str, QuerySnapshot],
    ) -> None:
        model_id = models_snapshot[model.name]["id"]
        file_id = self._file_id(Path(str(model._path)), files_snapshot)
        for query in extract_model_queries(model):
            name = query["name"]
            line_start = query["line_start"]
            line_end = query["line_end"]
            depth = query["depth"]
            select_col_count = query["select_col_count"]
            select_expr_count = query["select_expr_count"]
            select_alias_count = query["select_alias_count"]
            where_condition_count = query["where_condition_count"]
            join_statement_count = query["join_statement_count"]
            group_by_col_count = query["group_by_col_count"]
            having_condition_count = query["having_condition_count"]
            order_by_col_count = query["order_by_col_count"]
            rendered_sql = query["rendered_sql"]
            digest = snapshot_hash(
                [
                    model_id,
                    file_id,
                    name,
                    line_start,
                    line_end,
                    depth,
                    select_col_count,
                    select_expr_count,
                    select_alias_count,
                    where_condition_count,
                    join_statement_count,
                    group_by_col_count,
                    having_condition_count,
                    order_by_col_count,
                    rendered_sql,
                ]
            )
            key = f"{model_id}:{name}"
            prior = queries_snapshot.get(key)
            row: dict[str, object] = {
                "model_id": model_id,
                "name": name,
                "line_start": line_start,
                "line_end": line_end,
                "depth": depth,
                "file_id": file_id,
                "select_col_count": select_col_count,
                "select_expr_count": select_expr_count,
                "select_alias_count": select_alias_count,
                "where_condition_count": where_condition_count,
                "join_statement_count": join_statement_count,
                "group_by_col_count": group_by_col_count,
                "having_condition_count": having_condition_count,
                "order_by_col_count": order_by_col_count,
                "rendered_sql": rendered_sql,
                "snapshot_hash": digest,
            }
            if prior is None:
                query_id = self.assigner.reserve("queries", 1)[0]
                row["id"] = query_id
                self.batches["queries"].append(row)
            else:
                query_id = prior["id"]
                row["id"] = query_id
                if prior["snapshot_hash"] != digest:
                    self.batches["queries"].append(row)
            queries_snapshot[key] = {
                "id": query_id,
                "query_name": query["query_name"],
                "snapshot_hash": digest,
                "seen": True,
            }
            self._query_ids[query["query_name"]] = query_id

    def _sync_columns(
        self,
        model: Model,
        files_snapshot: dict[str, FileSnapshot],
        models_snapshot: dict[str, ModelSnapshot],
        columns_snapshot: dict[str, ColumnSnapshot],
        search_docs_snapshot: dict[str, SearchDocSnapshot],
    ) -> None:
        model_id = models_snapshot[model.name]["id"]
        model_name = model.name
        file_id = self._file_id(Path(str(model._path)), files_snapshot)
        column_descriptions = model.column_descriptions
        final_query = final_query_name(model_name)
        not_null_columns = not_null_column_names(model, self.context._audits)
        for column in extract_model_columns(model):
            query_name = column["query_name"]
            from_table = column["from_table"]
            name = column["name"]
            column_name = f"{from_table}.{name}" if from_table is not None else name
            qualified_name = column["qualified_name"]
            line_start = column["line_start"]
            line_end = column["line_end"]
            context = column["context"]
            is_select = column["is_select"]
            is_final = query_name == final_query
            description = column_descriptions.get(name) if is_final else None
            nullable = None if not is_final else name not in not_null_columns
            data_type = column["data_type"]
            query_id = self._query_ids[query_name]
            digest = snapshot_hash(
                [
                    model_id,
                    file_id,
                    query_id,
                    query_name,
                    from_table,
                    name,
                    column_name,
                    qualified_name,
                    data_type,
                    nullable,
                    line_start,
                    line_end,
                    context,
                    description,
                    is_select,
                ]
            )
            prior = columns_snapshot.get(qualified_name)
            if prior is None:
                column_id = self.assigner.reserve("columns", 1)[0]
                self.batches["columns"].append(
                    {
                        "id": column_id,
                        "file_id": file_id,
                        "query_id": query_id,
                        "model_id": model_id,
                        "from_table": from_table,
                        "name": name,
                        "column_name": column_name,
                        "qualified_name": qualified_name,
                        "data_type": data_type,
                        "nullable": nullable,
                        "line_start": line_start,
                        "line_end": line_end,
                        "context": context,
                        "description": description,
                        "is_select": is_select,
                        "snapshot_hash": digest,
                    }
                )
            else:
                column_id = prior["id"]
                if prior["snapshot_hash"] != digest:
                    self.batches["columns"].append(
                        {
                            "id": column_id,
                            "file_id": file_id,
                            "query_id": query_id,
                            "model_id": model_id,
                            "from_table": from_table,
                            "name": name,
                            "column_name": column_name,
                            "qualified_name": qualified_name,
                            "data_type": data_type,
                            "nullable": nullable,
                            "line_start": line_start,
                            "line_end": line_end,
                            "context": context,
                            "description": description,
                            "is_select": is_select,
                            "snapshot_hash": digest,
                        }
                    )
            columns_snapshot[qualified_name] = {
                "id": column_id,
                "snapshot_hash": digest,
                "seen": True,
            }
            relative = (
                query_name[len(model_name) + 1 :]
                if query_name.startswith(f"{model_name}/")
                else query_name
            )
            column_label = f"{from_table}.{name}" if from_table is not None else name
            model_kind = model.kind.name
            doc_digest = snapshot_hash([model_name, model_kind, relative, column_label])
            doc_prior = search_docs_snapshot.get(str(column_id))
            if doc_prior is None or doc_prior["snapshot_hash"] != doc_digest:
                self.batches["search_docs"].append(
                    {
                        "id": column_id,
                        "model_name": model_name,
                        "model_kind": model_kind,
                        "query_name": relative,
                        "column_name": column_label,
                        "snapshot_hash": doc_digest,
                    }
                )
            search_docs_snapshot[str(column_id)] = {
                "id": column_id,
                "snapshot_hash": doc_digest,
                "seen": True,
            }

    def _sync_column_lineage(
        self,
        model: Model,
        models_snapshot: dict[str, ModelSnapshot],
        columns_snapshot: dict[str, ColumnSnapshot],
        column_lineage_snapshot: dict[str, ColumnLineageSnapshot],
    ) -> None:
        model_id = models_snapshot[model.name]["id"]
        model_name_to_id = {
            synced.name: models_snapshot[synced.name]["id"]
            for synced in self.context.models.values()
            if synced.name in models_snapshot
        }
        for reference in extract_model_column_references(model):
            ref_query_name = reference["ref_column_query_name"]
            ref_qn = _stored_qualified_name(
                ref_query_name, reference["ref_column_qualified_name"], columns_snapshot
            )
            source_query_name = reference["source_query_name"]
            source_qn = _stored_qualified_name(
                source_query_name,
                reference["source_column_qualified_name"],
                columns_snapshot,
            )
            source_line = reference["source_line"]
            ref_line = reference["ref_line"]
            ref_kind = reference["ref_kind"]
            ref_context = reference["ref_context"]
            if source_qn not in columns_snapshot:
                continue
            ref_column_id = columns_snapshot[ref_qn]["id"]
            source_column_id = columns_snapshot[source_qn]["id"]
            source_models_id = model_id
            matched_name = ""
            for name, mid in model_name_to_id.items():
                prefix = source_qn == name or source_qn.startswith((f"{name}/", f"{name}."))
                if prefix and len(name) > len(matched_name):
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
                    ref_line,
                    ref_kind,
                    ref_context,
                ]
            )
            key = self.db._column_lineage_key(ref_qn, source_qn, source_line, ref_line, ref_kind)
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
                        "ref_line": ref_line,
                        "ref_kind": ref_kind,
                        "ref_context": ref_context,
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
                        "ref_line": ref_line,
                        "ref_kind": ref_kind,
                        "ref_context": ref_context,
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
            path = Path(str(metadata.path))
            file_id = self._file_id(path, files_snapshot)
            model = self.context.get_model(metadata.model_name)
            if model is None or model.name not in models_snapshot:
                continue
            model_id = models_snapshot[model.name]["id"]
            name = metadata.test_name
            line_start, line_end = test_line_span(path, name)
            digest = snapshot_hash([file_id, model_id, name, line_start, line_end])
            key = f"{file_id}:{name}"
            prior = tests_snapshot.get(key)
            if prior is None:
                test_id = self.assigner.reserve("tests", 1)[0]
                self.batches["tests"].append(
                    {
                        "id": test_id,
                        "file_id": file_id,
                        "model_id": model_id,
                        "name": name,
                        "line_start": line_start,
                        "line_end": line_end,
                        "snapshot_hash": digest,
                    }
                )
            else:
                test_id = prior["id"]
                if prior["snapshot_hash"] != digest:
                    self.batches["tests"].append(
                        {
                            "id": test_id,
                            "file_id": file_id,
                            "model_id": model_id,
                            "name": name,
                            "line_start": line_start,
                            "line_end": line_end,
                            "snapshot_hash": digest,
                        }
                    )
            tests_snapshot[key] = {"id": test_id, "snapshot_hash": digest, "seen": True}
            body = metadata.body if isinstance(metadata.body, dict) else {}
            column_qns: list[str] = []
            fixture_base = path.parent
            for input_name, values in (body.get("inputs") or {}).items():
                input_model = self.context.get_model(input_name)
                if input_model is None:
                    continue
                for column_name in fixture_column_names(
                    values,
                    dialect=input_model.dialect,
                    base_path=fixture_base,
                ):
                    column_qns.extend(
                        _columns_named(
                            final_query_name(input_model.name), column_name, columns_snapshot
                        )
                    )
            outputs = body.get("outputs") or {}
            for column_name in fixture_column_names(
                outputs.get("query"),
                dialect=model.dialect,
                base_path=fixture_base,
            ):
                column_qns.extend(
                    _columns_named(final_query_name(model.name), column_name, columns_snapshot)
                )
            for cte_name, values in (outputs.get("ctes") or {}).items():
                for column_name in fixture_column_names(
                    values,
                    dialect=model.dialect,
                    base_path=fixture_base,
                ):
                    column_qns.extend(
                        _columns_named(
                            model_query_name(model.name, cte_name), column_name, columns_snapshot
                        )
                    )
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
