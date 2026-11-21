from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import bullet

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
    models.kind
FROM models
WHERE models.schema_name = ?
ORDER BY models.qualified_name
"""


def _bullets(names: list[str], empty: str) -> str:
    result = empty
    if names:
        result = "\n".join(bullet(name) for name in names) + "\n"
    return result


def list_schemas(db: ProjectDB) -> str:
    names = [
        f"{row['schema_name']} (EXTERNAL)" if row["external"] else str(row["schema_name"])
        for row in db.connection.execute(_SCHEMAS_SQL)
    ]
    return _bullets(names, "No schemas found.")


def list_models(db: ProjectDB, schema: str) -> str:
    key = schema.strip()
    result = "No schema given; pass a schema name."
    if key:
        rows = list(db.connection.execute(_MODELS_SQL, (key,)))
        names = [str(row["qualified_name"]) for row in rows]
        result = _bullets(names, "No models found.")
        if rows and all(row["kind"] == "EXTERNAL" for row in rows):
            result = f"EXTERNAL SCHEMA\n\n{result}"
    return result
