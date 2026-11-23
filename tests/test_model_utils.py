from pathlib import Path

import pytest
from sqlmesh.core.context import Context

from src.parse.model_utils import model_config_lines
from src.parse.parse_only import install_parse_only_engine_support

BIGQUERY_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bigquery_project"


def test_model_config_lines_parses_with_the_model_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_parse_only_engine_support()
    context = Context(paths=BIGQUERY_FIXTURE, load=False)
    context.load(update_schemas=True)
    model = next(model for model in context.models.values() if model.name.endswith("subscriptions"))
    seen: dict[str, str | None] = {}

    def tracking_parse(
        text: str,
        default_dialect: str | None = None,
        match_dialect: bool = True,
    ) -> list:
        from sqlmesh.core.dialect import parse as real_parse

        seen["default_dialect"] = default_dialect
        return real_parse(text, default_dialect=default_dialect, match_dialect=match_dialect)

    monkeypatch.setattr("src.parse.model_utils.sqlmesh_parse", tracking_parse)
    start_line, end_line = model_config_lines(model)
    assert seen["default_dialect"] == "bigquery"
    assert start_line == 1
    assert end_line == 5
