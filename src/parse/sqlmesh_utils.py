import importlib
import sys
import types

from sqlmesh.core.config.connection import ConnectionConfig
from sqlmesh.core.config.scheduler import BuiltInSchedulerConfig
from sqlmesh.core.context import GenericContext

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


def _catalog_for_connection(connection: ConnectionConfig) -> str | None:
    catalog = connection.get_catalog()
    result = catalog
    if catalog is None and connection.type_ == "duckdb":
        result = "memory"
    return result


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


def install_parse_only_engine_support() -> None:
    silence_grpc_logs()
    _install_missing_engine_stubs()
    BuiltInSchedulerConfig.get_default_catalog_per_gateway = _default_catalog_per_gateway
