def bullet(text: str, lead: str = "") -> str:
    return f"  {lead}• {text}"


def gutter_width(numbers: list[int]) -> int:
    return max((len(str(number)) for number in numbers), default=1)


def file_label(name: str, line_count: int, model_names: list[str] | None = None) -> str:
    label = name or "(unknown path)"
    if line_count > 0:
        label = f"{label} ({line_count}L)"
    if model_names:
        label = f"{label} — {', '.join(model_names)}"
    return label


def tree_glyphs(is_last: bool, *, wide: bool = False) -> tuple[str, str]:
    narrow = (("├─ ", "│  "), ("└─ ", "   "))
    wide_glyphs = (("├── ", "│   "), ("└── ", "    "))
    glyphs = wide_glyphs if wide else narrow
    return glyphs[int(is_last)]
