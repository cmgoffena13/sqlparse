from src.sqlparse_mcp.format_utils import (
    bullet,
    file_label,
    from_table_reads_models,
    gutter_width,
    kind_counts_label,
    kind_label,
    line_span,
    model_display_label,
    omit_default_catalog,
    path_label,
    tree_glyphs,
    with_reads_models_count,
    with_reads_models_flag,
)


def test_bullet_default_lead() -> None:
    assert bullet("sushi.customers") == "  • sushi.customers"


def test_bullet_with_rank_lead() -> None:
    assert bullet("sushi.customers/$cte", "#1 ") == "  #1 • sushi.customers/$cte"


def test_path_label_joins_model_query_column() -> None:
    assert path_label("sushi.customers", "$cte", "raw.orders.amount_cents") == (
        "sushi.customers/$cte/raw.orders.amount_cents"
    )


def test_omit_default_catalog_strips_only_the_default_prefix() -> None:
    assert omit_default_catalog("memory.sushi.customers", "memory") == "sushi.customers"
    assert omit_default_catalog("other.sushi.customers", "memory") == "other.sushi.customers"
    assert omit_default_catalog("$cte.customer_id", "memory") == "$cte.customer_id"
    assert omit_default_catalog("memory.sushi.customers", None) == "memory.sushi.customers"
    assert (
        model_display_label(
            "memory.raw.customers",
            kind="EXTERNAL",
            mark_external=True,
            default_catalog="memory",
        )
        == "raw.customers (EXTERNAL)"
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
        kind_label(
            [
                "order",
                "expression",
                "alias",
                "select",
                "qualify",
                "having",
                "group",
                "where",
                "join",
            ]
        )
        == "J, W, G, H, Q, E, A, S, O"
    )


def test_kind_counts_label_keeps_required_select() -> None:
    assert (
        kind_counts_label(
            {"select": 3, "expression": 1, "join": 1, "where": 0},
            always=frozenset({"select"}),
        )
        == "1J, 1E, 3S"
    )


def test_from_table_reads_models_ignores_query_sources() -> None:
    assert from_table_reads_models("raw.customers") is True
    assert from_table_reads_models("$cte") is False
    assert from_table_reads_models(None) is False


def test_with_reads_models_flag_appends_m() -> None:
    assert with_reads_models_flag("1J, 4S", True) == "1J, 4S, M"
    assert with_reads_models_flag("J, S", True) == "J, S, M"
    assert with_reads_models_flag("", True) == "M"
    assert with_reads_models_flag("1E, 3S", False) == "1E, 3S"


def test_with_reads_models_count_appends_count() -> None:
    assert with_reads_models_count("1J, 4S", 2) == "1J, 4S, 2M"
    assert with_reads_models_count("", 1) == "1M"
    assert with_reads_models_count("1E, 3S", 0) == "1E, 3S"
