from pathlib import Path

from src.parse.test_utils import fixture_column_names

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "test_utils"


def test_fixture_column_names_from_columns_mapping() -> None:
    assert fixture_column_names({"columns": {"customer_id": "INT", "status": "TEXT"}}) == [
        "customer_id",
        "status",
    ]


def test_fixture_column_names_unions_keys_across_rows() -> None:
    assert fixture_column_names(
        {
            "rows": [
                {"customer_id": 1},
                {"customer_id": 2, "status": "active"},
            ]
        }
    ) == ["customer_id", "status"]


def test_fixture_column_names_from_inline_csv() -> None:
    assert fixture_column_names(
        {
            "format": "csv",
            "rows": "customer_id,status\n1,active\n",
        }
    ) == ["customer_id", "status"]


def test_fixture_column_names_from_csv_path() -> None:
    assert fixture_column_names(
        {"format": "csv", "path": "customers.csv"},
        base_path=FIXTURES,
    ) == ["customer_id", "status"]


def test_fixture_column_names_from_sql_query() -> None:
    assert fixture_column_names(
        {"query": "SELECT 1 AS customer_id, 'active' AS status"},
        dialect="duckdb",
    ) == ["customer_id", "status"]
