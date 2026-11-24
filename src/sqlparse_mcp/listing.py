from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import bullet, model_display_label

_SCHEMAS_SQL = """
SELECT
    models.schema_name,
    MIN(models.kind = 'EXTERNAL') AS external
FROM models
GROUP BY models.schema_name
ORDER BY models.schema_name
"""

_MODELS_SQL = """
SELECT
    models.qualified_name,
    models.kind,
    models.is_blueprint
FROM models
WHERE models.schema_name = ?
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


def list_schemas(db: ProjectDB) -> str:
    names = [
        f"{row['schema_name']} (EXTERNAL)" if row["external"] else str(row["schema_name"])
        for row in db.connection.execute(_SCHEMAS_SQL)
    ]
    return _bullets(names, "Schema", "No schemas found.")


def list_models(db: ProjectDB, schema: str) -> str:
    key = schema.strip()
    result = "No schema given; pass a schema name."
    if key:
        rows = list(db.connection.execute(_MODELS_SQL, (key,)))
        names = [
            model_display_label(
                str(row["qualified_name"]),
                is_blueprint=bool(row["is_blueprint"]),
            )
            for row in rows
        ]
        result = _bullets(names, "Model", "No models found.")
        if rows and all(row["kind"] == "EXTERNAL" for row in rows):
            count, body = result.split("\n\n", 1)
            result = f"{count}\n\nEXTERNAL SCHEMA\n\n{body}"
    return result
