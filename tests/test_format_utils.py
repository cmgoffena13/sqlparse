from src.sqlparse_mcp.format_utils import (
    bullet,
    file_label,
    gutter_width,
    kind_counts_label,
    kind_label,
    line_span,
    path_label,
    tree_glyphs,
)


def test_bullet_default_lead() -> None:
    assert bullet("sushi.customers") == "  • sushi.customers"


def test_bullet_with_rank_lead() -> None:
    assert bullet("sushi.customers/$cte", "#1 ") == "  #1 • sushi.customers/$cte"


def test_path_label_joins_model_query_column() -> None:
    assert path_label("sushi.customers", "$cte", "raw.orders.amount_cents") == (
        "sushi.customers/$cte/raw.orders.amount_cents"
    )


def test_gutter_width_pads_to_widest_rank() -> None:
    assert gutter_width([1, 9, 10, 20]) == 2
    assert gutter_width([1]) == 1
    assert gutter_width([]) == 1
    assert bullet("sushi.customers", f"#{1:<{gutter_width([1, 20])}} ") == (
        "  #1  • sushi.customers"
    )


def test_file_label_lines_and_models_without_symbol_count() -> None:
    assert file_label("empty.sql", 0) == "empty.sql"
    assert file_label("customers.sql", 18) == "customers.sql (18L)"


def test_line_span_collapses_a_single_line() -> None:
    assert line_span(12, 12) == "L12"
    assert line_span(14, 15) == "L14-15"


def test_tree_glyphs_wide() -> None:
    assert tree_glyphs(False, wide=True) == ("├── ", "│   ")
    assert tree_glyphs(True, wide=True) == ("└── ", "    ")


def test_kind_label_orders_by_sql_logical_order() -> None:
    assert (
        kind_label(["order", "expression", "alias", "select", "having", "group", "where", "join"])
        == "J, W, G, H, E, A, S, O"
    )


def test_kind_counts_label_keeps_required_select() -> None:
    assert (
        kind_counts_label(
            {"select": 3, "expression": 1, "join": 1, "where": 0},
            always=frozenset({"select"}),
        )
        == "1J, 1E, 3S"
    )
