import inspect
from pathlib import Path
from typing import Any, TypedDict, cast

from sqlmesh.core import constants as sqlmesh_constants
from sqlmesh.core.context import Context
from sqlmesh.utils.jinja import MacroExtractor


class MacroLocation(TypedDict):
    path: Path
    kind: str
    line_start: int
    line_end: int


def _jinja_macro_span(text: str, name: str) -> tuple[int, int]:
    marker = "{% macro " + name
    start_offset = text.find(marker)
    end_marker = "{% endmacro %}"
    end_offset = text.find(end_marker, start_offset) + len(end_marker)
    line_start = text.count("\n", 0, start_offset) + 1
    line_end = line_start + text[start_offset:end_offset].count("\n")
    return line_start, line_end


def _python_macro_span(registered: object) -> tuple[int, int]:
    lines, line_start = inspect.getsourcelines(cast(Any, registered).func)
    line_end = line_start + len(lines) - 1
    return line_start, line_end


def macro_locations(context: Context) -> dict[str, MacroLocation]:
    extractor = MacroExtractor()
    locations: dict[str, MacroLocation] = {}
    python_files: dict[Path, Path] = {}
    for loader in context._loaders:
        dialect = loader.config.model_defaults.dialect
        macros_root = loader.config_path / sqlmesh_constants.MACROS
        for path in loader._glob_paths(
            macros_root,
            ignore_patterns=loader.config.ignore_patterns,
            extension=".sql",
        ):
            text = path.read_text(encoding="utf-8")
            for name in extractor.extract(text, dialect=dialect):
                line_start, line_end = _jinja_macro_span(text, name)
                locations[name] = {
                    "path": path,
                    "kind": "jinja",
                    "line_start": line_start,
                    "line_end": line_end,
                }
        for path in loader._glob_paths(
            macros_root,
            ignore_patterns=loader.config.ignore_patterns,
            extension=".py",
        ):
            python_files[path.resolve()] = path
    for name, registered in context._macros.items():
        if not getattr(registered, "__sqlmesh__builtin__", False):
            resolved = Path(inspect.getfile(cast(Any, registered).func)).resolve()
            line_start, line_end = _python_macro_span(registered)
            locations[name] = {
                "path": python_files[resolved],
                "kind": "python",
                "line_start": line_start,
                "line_end": line_end,
            }
    return locations
