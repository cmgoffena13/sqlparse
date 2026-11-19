import csv
import io
from pathlib import Path

from sqlglot import exp


def fixture_column_names(
    values: object,
    *,
    dialect: str | None = None,
    base_path: Path | None = None,
) -> list[str]:
    names: list[str] = []
    if isinstance(values, dict):
        columns = values.get("columns")
        names = list(columns) if isinstance(columns, dict) else names
        query = values.get("query")
        parsed = exp.maybe_parse(query, dialect=dialect) if isinstance(query, str) else None
        names = list(parsed.named_selects) if not names and parsed is not None else names
        fmt = values.get("format")
        path_value = values.get("path")
        rows = values.get("rows")
        csv_path = Path(str(path_value)) if path_value is not None else None
        csv_path = (
            base_path / csv_path
            if csv_path is not None and not csv_path.is_absolute() and base_path is not None
            else csv_path
        )
        raw_csv_settings = values.get("csv_settings")
        csv_settings = raw_csv_settings if isinstance(raw_csv_settings, dict) else {}
        delimiter = str(csv_settings.get("delimiter", ","))
        csv_text = (
            csv_path.read_text(encoding="utf-8")
            if fmt == "csv" and csv_path is not None
            else (rows if fmt == "csv" and isinstance(rows, str) else "")
        )
        csv_names = (
            list(next(csv.reader(io.StringIO(csv_text), delimiter=delimiter))) if csv_text else []
        )
        names = csv_names if not names and csv_names else names
        row_names: list[str] = []
        if isinstance(rows, list):
            for row in rows:
                row_names = (
                    row_names + [key for key in row if key not in row_names]
                    if isinstance(row, dict)
                    else row_names
                )
        names = names if names else row_names
    return names


def test_line_span(path: Path, test_name: str) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    marker = f"{test_name}:"
    line_start = next(i for i, line in enumerate(lines, start=1) if line.startswith(marker))
    line_end = len(lines)
    for index in range(line_start, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and line.endswith(":"):
            line_end = index
            break
    return line_start, line_end
