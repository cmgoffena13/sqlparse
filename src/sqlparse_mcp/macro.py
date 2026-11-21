from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import bullet
from src.sqlparse_mcp.model import _normalize_file_path

_MACRO_SQL = """
SELECT
    macros.line_start,
    macros.line_end,
    models.qualified_name
FROM macros
INNER JOIN files
    ON files.id = macros.file_id
LEFT JOIN model_macros
    ON model_macros.macro_name = macros.name
LEFT JOIN models
    ON models.id = model_macros.model_id
WHERE files.path = ?
  AND macros.name = ?
ORDER BY models.qualified_name
"""


def get_macro(db: ProjectDB, file_path: str, macro_name: str) -> str:
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
            models = [
                str(row["qualified_name"]) for row in rows if row["qualified_name"] is not None
            ]
            footer = ["", "## Models", "", *[bullet(model) for model in models]]
            lines = [*body, *footer] if models else body
            result = "\n".join(lines) + "\n"
    return result
