from src.sqlparse_mcp.format_utils import bullet, file_label, gutter_width, line_span, tree_glyphs


def test_bullet_default_lead() -> None:
    assert bullet("sushi.customers") == "  • sushi.customers"


def test_bullet_with_rank_lead() -> None:
    assert bullet("sushi.customers / cte", "#1 ") == "  #1 • sushi.customers / cte"


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
    assert file_label("customers.sql", 18, ["sushi.customers"]) == (
        "customers.sql (18L) — sushi.customers"
    )


def test_line_span_collapses_a_single_line() -> None:
    assert line_span(12, 12) == "L12"
    assert line_span(14, 15) == "L14-15"


def test_tree_glyphs_wide() -> None:
    assert tree_glyphs(False, wide=True) == ("├── ", "│   ")
    assert tree_glyphs(True, wide=True) == ("└── ", "    ")
