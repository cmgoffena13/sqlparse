from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import bullet, model_display_label
from src.sqlparse_mcp.model_utils import default_catalog

_CATALOGS_SQL = """
SELECT
    project_gateways.catalog_name,
    MAX(project_gateways.is_default) AS is_default,
    COUNT(DISTINCT models.schema_name) AS schema_count,
    COUNT(models.id) AS table_count
FROM project_gateways
LEFT JOIN models
    ON models.gateway_id = project_gateways.id
GROUP BY project_gateways.catalog_name
ORDER BY project_gateways.catalog_name
"""

_SCHEMAS_SQL = """
SELECT
    models.schema_name,
    MIN(models.kind = 'EXTERNAL') AS external,
    COUNT(models.id) AS table_count
FROM models
INNER JOIN project_gateways
    ON project_gateways.id = models.gateway_id
WHERE project_gateways.catalog_name = ?
GROUP BY models.schema_name
ORDER BY models.schema_name
"""

_MODELS_SQL = """
SELECT
    models.qualified_name,
    models.kind,
    models.is_blueprint
FROM models
INNER JOIN project_gateways
    ON project_gateways.id = models.gateway_id
WHERE project_gateways.catalog_name = ?
  AND models.schema_name = ?
ORDER BY models.qualified_name
"""


def _bullets(names: list[str], singular: str, empty: str) -> str:
    label = singular
    if len(names) != 1:
        label = f"{singular}s"
    result = empty
    if names:
        result = f"{len(names)} {label}\n\n" + "\n".join(bullet(name) for name in names) + "\n"
    return result


def _resolved_catalog(db: ProjectDB, catalog: str | None) -> str | None:
    key = None if catalog is None else catalog.strip()
    return key if key else default_catalog(db)


def list_catalogs(db: ProjectDB) -> str:
    names = [
        (
            f"{row['catalog_name']} (DEFAULT) - {int(row['schema_count'])} schemas, "
            f"{int(row['table_count'])} tables"
            if row["is_default"]
            else (
                f"{row['catalog_name']} - {int(row['schema_count'])} schemas, "
                f"{int(row['table_count'])} tables"
            )
        )
        for row in db.connection.execute(_CATALOGS_SQL)
    ]
    return _bullets(names, "Catalog", "No catalogs found.")


def list_schemas(db: ProjectDB, catalog: str | None = None) -> str:
    resolved = _resolved_catalog(db, catalog)
    result = "No catalogs found."
    if resolved is not None:
        names = [
            (
                f"{row['schema_name']} (EXTERNAL) - {int(row['table_count'])} tables"
                if row["external"]
                else f"{row['schema_name']} - {int(row['table_count'])} tables"
            )
            for row in db.connection.execute(_SCHEMAS_SQL, (resolved,))
        ]
        result = _bullets(names, "Schema", "No schemas found.")
    return result


def list_models(db: ProjectDB, schema: str, catalog: str | None = None) -> str:
    key = schema.strip()
    result = "No schema given; pass a schema name."
    if key:
        resolved = _resolved_catalog(db, catalog)
        result = "No catalogs found."
        if resolved is not None:
            rows = list(db.connection.execute(_MODELS_SQL, (resolved, key)))
            catalog = default_catalog(db)
            names = [
                model_display_label(
                    str(row["qualified_name"]),
                    is_blueprint=bool(row["is_blueprint"]),
                    default_catalog=catalog,
                )
                for row in rows
            ]
            result = _bullets(names, "Model", "No models found.")
            if rows and all(row["kind"] == "EXTERNAL" for row in rows):
                count, body = result.split("\n\n", 1)
                result = f"{count}\n\nEXTERNAL SCHEMA\n\n{body}"
    return result
