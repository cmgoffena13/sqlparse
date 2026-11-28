KIND_ORDER = (
    "join",
    "where",
    "group",
    "having",
    "qualify",
    "expression",
    "alias",
    "select",
    "order",
)
KIND_LETTER = {
    "join": "J",
    "where": "W",
    "group": "G",
    "having": "H",
    "qualify": "Q",
    "select": "S",
    "alias": "A",
    "expression": "E",
    "order": "O",
}
READS_MODELS_LETTER = "M"


def kind_label(kinds: list[str]) -> str:
    present = set(kinds)
    parts = [KIND_LETTER[kind] for kind in KIND_ORDER if kind in present]
    parts.extend(kind for kind in kinds if kind not in KIND_LETTER)
    return ", ".join(parts)


def kind_counts_label(
    counts: dict[str, int],
    *,
    always: frozenset[str] = frozenset(),
) -> str:
    parts: list[str] = []
    for kind in KIND_ORDER:
        count = counts.get(kind, 0)
        if count or kind in always:
            parts.append(f"{count}{KIND_LETTER[kind]}")
    for kind, count in counts.items():
        if kind not in KIND_LETTER and count:
            parts.append(f"{count}{kind}")
    return ", ".join(parts)


def from_table_reads_models(from_table: str | None) -> bool:
    return from_table is not None and not from_table.startswith("$")


def with_reads_models_flag(label: str, reads_models: bool) -> str:
    result = label
    if reads_models:
        result = f"{label}, {READS_MODELS_LETTER}" if label else READS_MODELS_LETTER
    return result


def with_reads_models_count(label: str, reads_models: int) -> str:
    result = label
    if reads_models:
        marker = f"{reads_models}{READS_MODELS_LETTER}"
        result = f"{label}, {marker}" if label else marker
    return result


def line_span(start_line: int, end_line: int) -> str:
    loc = f"L{start_line}-{end_line}"
    if start_line == end_line:
        loc = f"L{start_line}"
    return loc


def path_label(*parts: str) -> str:
    return "/".join(parts)


def bullet(text: str, lead: str = "") -> str:
    return f"  {lead}• {text}"


def omit_default_catalog(name: str, default_catalog: str | None) -> str:
    label = name
    if default_catalog:
        prefix = f"{default_catalog}."
        if name.startswith(prefix):
            label = name[len(prefix) :]
    return label


def model_display_label(
    name: str,
    *,
    kind: str | None = None,
    is_blueprint: bool = False,
    mark_external: bool = False,
    default_catalog: str | None = None,
) -> str:
    label = omit_default_catalog(name, default_catalog)
    if mark_external and kind == "EXTERNAL":
        label = f"{label} (EXTERNAL)"
    elif is_blueprint:
        label = f"{label} (BLUEPRINT)"
    return label


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
