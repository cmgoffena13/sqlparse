from src.db import ProjectDB
from src.sqlparse_mcp.sql_tree import _normalize_file_path

_TEST_SQL = """
SELECT
    tests.name,
    tests.line_start,
    tests.line_end,
    models.qualified_name
FROM tests
INNER JOIN files
    ON files.id = tests.file_id
INNER JOIN models
    ON models.id = tests.model_id
WHERE files.path = ?
  AND tests.name = ?
"""


def get_test(db: ProjectDB, file_path: str, test_name: str) -> str:
    path_key = file_path.strip()
    name = test_name.strip()
    result = "No file path given; pass a test file path."
    if path_key and not name:
        result = "No test name given; pass a test name."
    if path_key and name:
        path = _normalize_file_path(path_key, db.root)
        row = db.connection.execute(_TEST_SQL, (path, name)).fetchone()
        result = "No test found."
        if row is not None:
            text = (db.root / path).read_text(encoding="utf-8")
            start = int(row["line_start"])
            end = int(row["line_end"])
            gutter = len(str(end))
            body = [
                f"L{lineno:<{gutter}} | {line}"
                for lineno, line in enumerate(text.splitlines()[start - 1 : end], start)
            ]
            header = f"Model: {row['qualified_name']}"
            result = "\n".join([header, "", *body]) + "\n"
    return result
