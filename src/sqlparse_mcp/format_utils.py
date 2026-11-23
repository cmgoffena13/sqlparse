def line_span(start_line: int, end_line: int) -> str:
    loc = f"L{start_line}-{end_line}"
    if start_line == end_line:
        loc = f"L{start_line}"
    return loc


def path_label(*parts: str) -> str:
    return "/".join(parts)


def bullet(text: str, lead: str = "") -> str:
    return f"  {lead}• {text}"


def gutter_width(numbers: list[int]) -> int:
    return max((len(str(number)) for number in numbers), default=1)


def file_label(name: str, line_count: int) -> str:
    label = name or "(unknown path)"
    if line_count > 0:
        label = f"{label} ({line_count}L)"
    return label


def tree_glyphs(is_last: bool, *, wide: bool = False) -> tuple[str, str]:
    narrow = (("├─ ", "│  "), ("└─ ", "   "))
    wide_glyphs = (("├── ", "│   "), ("└── ", "    "))
    glyphs = wide_glyphs if wide else narrow
    return glyphs[int(is_last)]


def page_window(total: int, page: int, page_size: int, *, label: str) -> tuple[int, int, int] | str:
    page_count = (total + page_size - 1) // page_size if total else 0
    result: tuple[int, int, int] | str
    if page < 1:
        result = "Invalid page; pass page >= 1."
    elif page_count == 0 or page > page_count:
        result = f"No more {label}; page {page} is past {max(page_count, 1)}."
    else:
        start = (page - 1) * page_size
        result = (start, min(start + page_size, total), page_count)
    return result


def page_footer(page: int, page_count: int, shown: int, total: int, label: str) -> str:
    return f"… page {page} of {page_count} ({shown} of {total} {label})"


def with_page_footer(
    body: str, page: int, page_count: int, shown: int, total: int, label: str
) -> str:
    result = body
    if page_count > 1:
        footer = page_footer(page, page_count, shown, total, label)
        result = body.rstrip("\n") + "\n\n" + footer + "\n"
    return result
