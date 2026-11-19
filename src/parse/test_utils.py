from pathlib import Path


def fixture_column_names(values: object) -> list[str]:
    names: list[str] = []
    if isinstance(values, dict):
        columns = values.get("columns")
        rows = values.get("rows")
        names = list(columns) if isinstance(columns, dict) else names
        names = (
            list(rows[0])
            if not names and isinstance(rows, list) and rows and isinstance(rows[0], dict)
            else names
        )
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
