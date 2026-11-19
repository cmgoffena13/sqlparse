import sqlite3
from collections import OrderedDict

from src.db import ProjectDB

_SEARCH_SQL = """
SELECT
    model_name,
    query_name,
    column_name,
    bm25(search_fts, 10.0, 5.0, 10.0) AS rank
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
            models: OrderedDict[str, int] = OrderedDict()
            queries: OrderedDict[str, int] = OrderedDict()
            columns: list[tuple[int, str]] = []
            for rank, row in enumerate(rows, start=1):
                model_name = str(row["model_name"])
                query_name = str(row["query_name"])
                column_name = str(row["column_name"])
                models.setdefault(model_name, rank)
                if query_name:
                    queries.setdefault(f"{model_name} / {query_name}", rank)
                column_label = (
                    f"{model_name} / {query_name} / {column_name}"
                    if query_name
                    else f"{model_name} / {column_name}"
                )
                columns.append((rank, column_label))
            lines: list[str] = []
            if models:
                lines.append("models")
                for label, rank in models.items():
                    lines.append(f"  #{rank} {label}")
            if queries:
                if lines:
                    lines.append("")
                lines.append("queries")
                for label, rank in queries.items():
                    lines.append(f"  #{rank} {label}")
            if columns:
                if lines:
                    lines.append("")
                lines.append("columns")
                for rank, label in columns:
                    lines.append(f"  #{rank} {label}")
            result = "No matches."
            if lines:
                result = "\n".join(lines)
        except sqlite3.OperationalError as e:
            result = f"Search failed for {query!r} ({fts_query!r}): {e}"
    return result
