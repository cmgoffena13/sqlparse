import sqlite3
from collections import OrderedDict

from src.db import ProjectDB
from src.sqlparse_mcp.format_utils import bullet, gutter_width

_SEARCH_SQL = """
SELECT
    model_name,
    query_name,
    column_name,
    bm25(search_fts, 10.0, 10.0, 10.0) AS rank
FROM search_fts
WHERE search_fts MATCH ?
ORDER BY rank
LIMIT ?
"""


def _fts_term(token: str) -> str:
    term = f'"{token.replace(chr(34), chr(34) * 2)}"'
    if token.isidentifier():
        term = token
    return term


def _word_clause(word: str) -> str:
    term = _fts_term(word)
    return f"(model_name: {term} OR query_name: {term} OR column_name: {term})"


def build_fts_query(user_input: str) -> str:
    clauses = [_word_clause(word) for word in user_input.split() if word]
    query = ""
    if clauses:
        query = " OR ".join(clauses)
    return query


def search(db: ProjectDB, query: str, limit: int) -> str:
    stripped = query.strip().replace("-", " ")
    fts_query = build_fts_query(stripped)
    result = "No search text given; pass a non-empty query."
    if fts_query:
        try:
            rows = db.connection.execute(_SEARCH_SQL, (fts_query, limit)).fetchall()
            hits: OrderedDict[str, str] = OrderedDict()
            for row in rows:
                model_name = str(row["model_name"])
                query_name = str(row["query_name"])
                column_name = str(row["column_name"])
                query_label = query_name if query_name else "$"
                for section, label in (
                    ("models", model_name),
                    ("queries", f"{model_name} / {query_label}"),
                    ("columns", f"{model_name} / {query_label} / {column_name}"),
                ):
                    if label not in hits:
                        hits[label] = section
                    if len(hits) >= limit:
                        break
                if len(hits) >= limit:
                    break
            models: OrderedDict[str, int] = OrderedDict()
            queries: OrderedDict[str, int] = OrderedDict()
            columns: OrderedDict[str, int] = OrderedDict()
            for rank, (label, section) in enumerate(hits.items(), start=1):
                if section == "models":
                    models[label] = rank
                elif section == "queries":
                    queries[label] = rank
                else:
                    columns[label] = rank
            width = gutter_width([*models.values(), *queries.values(), *columns.values()])
            lines: list[str] = []
            if models:
                lines.append("## Models")
                for label, rank in models.items():
                    lines.append(bullet(label, f"#{rank:<{width}} "))
            if queries:
                if lines:
                    lines.append("")
                lines.append("## Queries")
                for label, rank in queries.items():
                    lines.append(bullet(label, f"#{rank:<{width}} "))
            if columns:
                if lines:
                    lines.append("")
                lines.append("## Columns")
                for label, rank in columns.items():
                    lines.append(bullet(label, f"#{rank:<{width}} "))
            result = "No matches."
            if lines:
                result = "\n".join(lines)
        except sqlite3.OperationalError as e:
            result = f"Search failed for {query!r} ({fts_query!r}): {e}"
    return result
