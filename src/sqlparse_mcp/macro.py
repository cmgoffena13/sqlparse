from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import bullet, omit_default_catalog
from src.sqlparse_mcp.model import _normalize_file_path
from src.sqlparse_mcp.model_utils import default_catalog

_MACRO_SQL = """
SELECT
    macros.kind,
    macros.line_start,
    macros.line_end,
    models.qualified_name,
    queries.name AS query_name
FROM macros
INNER JOIN files
    ON files.id = macros.file_id
LEFT JOIN model_macros
    ON model_macros.macro_name = macros.name
LEFT JOIN models
    ON models.id = model_macros.model_id
LEFT JOIN queries
    ON queries.id = model_macros.query_id
WHERE files.path = ?
  AND macros.name = ?
ORDER BY models.qualified_name, queries.name
"""


def get_macro(
    db: ProjectDB, file_path: str, macro_name: str, include_call_sites: bool = False
) -> str:
    path_key = file_path.strip()
    name = macro_name.strip()
    result = "No file path given; pass a macro file path."
    if path_key and not name:
        result = "No macro name given; pass a macro name."
    if path_key and name:
        path = _normalize_file_path(path_key, db.root)
        rows = list(db.connection.execute(_MACRO_SQL, (path, name)))
        result = "No macro found."
        if rows:
            text = (db.root / path).read_text(encoding="utf-8")
            start = int(rows[0]["line_start"])
            end = int(rows[0]["line_end"])
            gutter = len(str(end))
            body = [
                f"L{lineno:<{gutter}} | {line}"
                for lineno, line in enumerate(text.splitlines()[start - 1 : end], start)
            ]
            header = [f"Type: {rows[0]['kind']}", ""]
            lines = [*header, *body]
            if include_call_sites:
                catalog = default_catalog(db)
                sites = [
                    (
                        f"{omit_default_catalog(str(row['qualified_name']), catalog)}"
                        f"/{row['query_name']}"
                    )
                    for row in rows
                    if row["qualified_name"] is not None and row["query_name"] is not None
                ]
                if sites:
                    lines.extend(["", "## Model Queries", "", *[bullet(site) for site in sites]])
            result = "\n".join(lines) + "\n"
    return result
