import os
import site
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlmesh.core.config import Config
from sqlmesh.core.config.loader import load_configs
from sqlmesh.utils.errors import ConfigError


def project_site_packages(root: Path) -> list[Path]:
    candidates = [
        root / name for name in (".venv", "venv") if (root / name / "pyvenv.cfg").is_file()
    ]
    venv_root = candidates[0] if candidates else None
    tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    direct = (
        []
        if venv_root is None
        else [venv_root / "lib" / tag / "site-packages", venv_root / "Lib" / "site-packages"]
    )
    packages = [path for path in direct if path.is_dir()]
    if venv_root is not None and not packages:
        packages = sorted(
            path for path in (venv_root / "lib").glob("python*/site-packages") if path.is_dir()
        )
    return packages


def use_project_venv(root: Path) -> None:
    for package in project_site_packages(root):
        site.addsitedir(str(package.absolute()))


@contextmanager
def project_cwd(root: Path) -> Generator[None]:
    previous = Path.cwd()
    os.chdir(root.resolve())
    try:
        yield
    finally:
        os.chdir(previous)


def is_sqlmesh_project(root: Path) -> bool:
    use_project_venv(root)
    with project_cwd(root):
        try:
            load_configs("config", Config, root)
        except ConfigError:
            project = False
        else:
            project = True
    return project
