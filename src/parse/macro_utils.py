import inspect
from pathlib import Path
from typing import Any, cast

from sqlmesh.core import constants as sqlmesh_constants
from sqlmesh.core.context import Context
from sqlmesh.utils.jinja import MacroExtractor


def macro_paths(context: Context) -> dict[str, Path]:
    extractor = MacroExtractor()
    paths: dict[str, Path] = {}
    python_files: dict[Path, Path] = {}
    for loader in context._loaders:
        dialect = loader.config.model_defaults.dialect
        macros_root = loader.config_path / sqlmesh_constants.MACROS
        for path in loader._glob_paths(
            macros_root,
            ignore_patterns=loader.config.ignore_patterns,
            extension=".sql",
        ):
            for name in extractor.extract(path.read_text(encoding="utf-8"), dialect=dialect):
                paths[name] = path
        for path in loader._glob_paths(
            macros_root,
            ignore_patterns=loader.config.ignore_patterns,
            extension=".py",
        ):
            python_files[path.resolve()] = path
    for name, registered in context._macros.items():
        if not getattr(registered, "__sqlmesh__builtin__", False):
            resolved = Path(inspect.getfile(cast(Any, registered).func)).resolve()
            paths[name] = python_files[resolved]
    return paths
