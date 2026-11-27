import logging
from pathlib import Path

from src.parse.query_spans import source_query_spans

MACRO_CTE_QUERY = Path(__file__).resolve().parent / "fixtures" / "macro_cte_query.sql"


def test_source_query_spans_includes_macro_func_cte_without_sqlglot_warning(
    caplog,
) -> None:
    text = MACRO_CTE_QUERY.read_text(encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        spans = source_query_spans(text, "duckdb")
    assert "$classified" in spans
    assert "$other" in spans
    assert "$" in spans
    assert not any("Cannot traverse scope" in message for message in caplog.messages)
