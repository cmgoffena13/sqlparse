from src.sqlparse_mcp.format_utils import bullet, gutter_width


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
