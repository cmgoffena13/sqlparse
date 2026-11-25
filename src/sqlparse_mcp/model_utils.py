import sqlite3

from src.db import ProjectDB
from src.parse.column_lineage import FINAL_QUERY
from src.parse.sqlmesh_utils import normalized_column_name, normalized_model_name

_MODEL_BY_QN_SQL = "SELECT qualified_name FROM models WHERE qualified_name = ?"

_GATEWAYS_SQL = """
SELECT DISTINCT
    project_gateways.catalog_name,
    project_gateways.dialect
FROM project_gateways
"""

_COLUMN_RESOLVE_SQL = """
SELECT
    columns.id,
    columns.name,
    columns.column_name,
    project_gateways.catalog_name,
    project_gateways.dialect
FROM columns
INNER JOIN queries
    ON queries.id = columns.query_id
INNER JOIN models
    ON models.id = columns.model_id
INNER JOIN project_gateways
    ON project_gateways.id = models.gateway_id
WHERE models.qualified_name = ?
  AND queries.name = ?
"""

_NOT_FOUND = (
    "No model found; pass catalog.schema.table unquoted "
    "(schema.table uses the gateway default catalog)."
)


def model_not_found_message() -> str:
    return _NOT_FOUND


def resolve_model_qualified_name_on(connection: sqlite3.Connection, name: str) -> str | None:
    key = name.strip()
    resolved: str | None = None
    row = connection.execute(_MODEL_BY_QN_SQL, (key,)).fetchone()
    if row is not None:
        resolved = str(row["qualified_name"])
    if resolved is None:
        for gateway in connection.execute(_GATEWAYS_SQL):
            candidate = normalized_model_name(key, gateway["catalog_name"], gateway["dialect"])
            if candidate != key:
                hit = connection.execute(_MODEL_BY_QN_SQL, (candidate,)).fetchone()
                if hit is not None:
                    resolved = str(hit["qualified_name"])
                    break
    return resolved


def resolve_model_qualified_name(db: ProjectDB, name: str) -> str | None:
    return resolve_model_qualified_name_on(db.connection, name)


def resolve_column_ids(
    db: ProjectDB,
    model_qualified_name: str,
    query_relative: str,
    column_input: str,
) -> list[int]:
    key = column_input.strip()
    rows = list(db.connection.execute(_COLUMN_RESOLVE_SQL, (model_qualified_name, query_relative)))
    labels = {key}
    if rows:
        catalog = rows[0]["catalog_name"]
        dialect = rows[0]["dialect"]
        labels.add(normalized_column_name(key, catalog, dialect))
        if "." in key:
            left, _, right = key.rpartition(".")
            if "." not in left and not left.startswith(FINAL_QUERY):
                labels.add(normalized_column_name(f"{FINAL_QUERY}{left}.{right}", catalog, dialect))
    return [
        int(row["id"])
        for row in rows
        if str(row["column_name"]) in labels or str(row["name"]) == key
    ]
