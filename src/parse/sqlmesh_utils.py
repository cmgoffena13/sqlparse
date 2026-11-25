import importlib
import sys
import types

from sqlglot import exp
from sqlglot.dialects.dialect import DialectType
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlmesh.core.config.connection import ConnectionConfig
from sqlmesh.core.config.scheduler import BuiltInSchedulerConfig
from sqlmesh.core.context import GenericContext
from sqlmesh.core.dialect import set_default_catalog

from src.utils import silence_grpc_logs

_ENGINE_IMPORT_NAMES = (
    "snowflake.connector.network",
    "databricks",
    "google.cloud.bigquery",
    "google.cloud.sql",
    "redshift_connector",
    "psycopg2",
    "pymysql",
    "pymssql",
    "pyodbc",
    "mssql_python",
    "pyspark",
    "trino",
    "clickhouse_connect",
    "pyathena",
    "ibm_db",
)


def _ensure_stub_module(name: str) -> types.ModuleType:
    parts = name.split(".")
    for index in range(1, len(parts) + 1):
        module_name = ".".join(parts[:index])
        if module_name not in sys.modules:
            module = types.ModuleType(module_name)
            sys.modules[module_name] = module
            if index > 1:
                parent = sys.modules[".".join(parts[: index - 1])]
                setattr(parent, parts[index - 1], module)
    return sys.modules[name]


def _install_missing_engine_stubs() -> None:
    for name in _ENGINE_IMPORT_NAMES:
        try:
            importlib.import_module(name)
        except ImportError:
            _ensure_stub_module(name)


def catalog_for_connection(connection: ConnectionConfig) -> str:
    catalog = connection.get_catalog()
    result = "memory"
    if catalog is not None:
        result = catalog
    return result


def _catalog_for_connection(connection: ConnectionConfig) -> str:
    return catalog_for_connection(connection)


def _default_catalog_per_gateway(
    self: BuiltInSchedulerConfig, context: GenericContext
) -> dict[str, str]:
    del self
    catalogs: dict[str, str] = {}
    for config in context.configs.values():
        for gateway_name in config.gateways:
            catalog = _catalog_for_connection(config.get_connection(gateway_name))
            if catalog:
                catalogs[gateway_name] = catalog
    selected = context.selected_gateway
    if selected not in catalogs:
        catalog = _catalog_for_connection(context.connection_config)
        if catalog:
            catalogs[selected] = catalog
    return catalogs


def normalized_model_name(
    table: str | exp.Table | exp.Column,
    default_catalog: str | None,
    dialect: DialectType = None,
) -> str:
    if isinstance(table, exp.Column):
        parsed = exp.table_(
            table.this,
            db=table.args.get("table"),
            catalog=table.args.get("db"),
        )
    else:
        parsed = exp.to_table(table, dialect=dialect)
    parsed = set_default_catalog(parsed, default_catalog)
    parsed = normalize_identifiers(parsed, dialect=dialect)
    parts = [
        part.name
        for part in (parsed.args.get("catalog"), parsed.args.get("db"), parsed.this)
        if part is not None
    ]
    return ".".join(parts)


def column_label(from_table: str | None, name: str, dialect: DialectType = None) -> str:
    leaf = normalize_identifiers(exp.to_identifier(name), dialect=dialect).name
    label = leaf
    if from_table is not None:
        label = f"{from_table}.{leaf}"
    return label


def normalized_column_name(
    name: str,
    default_catalog: str | None,
    dialect: DialectType = None,
) -> str:
    key = name.strip()
    if key.startswith("$") and "." in key:
        left, _, right = key.partition(".")
        normalized = f"{left}.{column_label(None, right, dialect)}"
    elif key.startswith("$") or not key:
        normalized = key
    elif "." not in key:
        normalized = column_label(None, key, dialect)
    else:
        col = exp.to_column(key, dialect=dialect)
        if (
            default_catalog
            and col.args.get("db") is not None
            and col.args.get("table") is not None
            and col.args.get("catalog") is None
        ):
            col.set("catalog", exp.parse_identifier(default_catalog))
        col = normalize_identifiers(col, dialect=dialect)
        for ident in col.find_all(exp.Identifier):
            ident.set("quoted", False)
        normalized = col.sql(dialect=dialect, identify=False)
    return normalized


def install_parse_only_engine_support() -> None:
    silence_grpc_logs()
    _install_missing_engine_stubs()
    BuiltInSchedulerConfig.get_default_catalog_per_gateway = _default_catalog_per_gateway
