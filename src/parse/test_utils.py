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
